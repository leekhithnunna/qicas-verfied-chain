#!/usr/bin/env python
"""Create a compact, self-describing ZIP snapshot of this QICAS workspace."""

from __future__ import annotations

import csv
import datetime as dt
import heapq
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent  # scripts/ -> repo root
SNAPSHOT_DIR = ROOT / "_snapshot"
MAX_FILE_BYTES = 10_000_000
MAX_ARCHIVE_BYTES = 100_000_000
MAX_RESULT_IMAGE_BYTES = 3_000_000
MAX_ABI_BYTES = 1_000_000
EXCLUDED_DIRS = {
    ".venv",
    "venv",
    "env",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".ipynb_checkpoints",
    "node_modules",
}
SOURCE_SUFFIXES = {
    ".py", ".sol", ".js", ".ts", ".json", ".yaml", ".yml", ".toml",
    ".cfg", ".ini", ".sh", ".ps1", ".html", ".css", ".md", ".txt",
    ".rst", ".ipynb",
}
RESULT_SUFFIXES = {".csv", ".json", ".md", ".txt", ".png", ".jpg", ".svg"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".bmp"}
DROP_ORDER = (
    "results_images_over_500kb",
    "other_images",
    "large_data_files",
)
AGGREGATE_LARGEST_FILES: list[tuple[int, str]] = []


@dataclass
class FileRecord:
    path: Path
    size: int
    reason: str = ""
    included: bool = False
    dropped_category: str = ""
    counted_files: int = 1

    @property
    def relative(self) -> str:
        return self.path.relative_to(ROOT).as_posix()

    @property
    def extension(self) -> str:
        return self.path.suffix.lower() or "[none]"


def is_secret_path(relative: Path) -> bool:
    for part in relative.parts:
        lower = part.lower()
        if "secret" in lower or "private" in lower or "keystore" in lower:
            return True
        if lower == ".env" or lower.startswith(".env."):
            return True
        if Path(part).suffix.lower() in {".pem", ".key"}:
            return True
    return False


def is_aggregate_directory(relative: Path) -> bool:
    return bool(relative.parts) and relative.name.lower() in {
        ".venv", "venv", "env", "node_modules",
    }


def excluded_directory_reason(relative: Path) -> str:
    if relative.name.lower() == "cache" and relative.parts[:2] == ("chain", "hardhat"):
        return "excluded: build cache"
    if relative.name.lower() in EXCLUDED_DIRS:
        return f"excluded: directory ({relative.name})"
    if any("secret" in p.lower() or "private" in p.lower() or "keystore" in p.lower()
           for p in relative.parts):
        return "excluded: secret"
    return ""


def aggregate_directory(path: Path) -> tuple[int, int]:
    count = 0
    total = 0
    largest: list[tuple[int, str]] = []
    for current, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not Path(current, d).is_symlink())
        for name in files:
            file_path = Path(current, name)
            try:
                size = file_path.stat().st_size
                total += size
                count += 1
                relative = file_path.relative_to(ROOT).as_posix()
                item = (size, relative)
                if len(largest) < 10:
                    heapq.heappush(largest, item)
                elif item > largest[0]:
                    heapq.heapreplace(largest, item)
            except OSError:
                continue
    AGGREGATE_LARGEST_FILES.extend(largest)
    return count, total


def scan_project() -> tuple[list[FileRecord], dict[str, tuple[int, int]], set[str]]:
    records: list[FileRecord] = []
    folder_stats: dict[str, tuple[int, int]] = {"": (0, 0)}
    empty_folders: set[str] = set()

    for current, dirs, files in os.walk(ROOT, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(ROOT)
        relative_dir_text = relative_dir.as_posix() if relative_dir.parts else ""
        folder_stats.setdefault(relative_dir_text, (0, 0))
        retained_dirs: list[str] = []

        for name in sorted(dirs):
            child = current_path / name
            relative = child.relative_to(ROOT)
            relative_text = relative.as_posix()
            if name.lower() == "_snapshot":
                continue
            if child.is_symlink():
                try:
                    size = child.lstat().st_size
                except OSError:
                    size = 0
                records.append(FileRecord(child, size, "excluded: symbolic link"))
                continue
            if is_aggregate_directory(relative):
                count, total = aggregate_directory(child)
                records.append(FileRecord(
                    child, total,
                    f"excluded: directory aggregate ({count} files; contents not inventoried individually)",
                    counted_files=count,
                ))
                folder_stats[relative_text] = (count, total)
                continue
            retained_dirs.append(name)
            folder_stats.setdefault(relative_text, (0, 0))
            if excluded_directory_reason(relative):
                continue

        dirs[:] = retained_dirs
        if not dirs and not files:
            empty_folders.add(relative_dir_text or ".")

        for name in sorted(files):
            path = current_path / name
            relative = path.relative_to(ROOT)
            try:
                size = path.stat().st_size
            except OSError:
                records.append(FileRecord(path, 0, "excluded: could not read file metadata"))
                continue
            record = FileRecord(path, size)
            records.append(record)
            folder_stats[relative_dir_text] = (
                folder_stats[relative_dir_text][0] + 1,
                folder_stats[relative_dir_text][1] + size,
            )

    # Convert folder totals to recursive counts/sizes, preserving aggregates for
    # the intentionally unexpanded virtual-environment and node_modules entries.
    for relative in sorted(folder_stats, key=lambda value: value.count("/"), reverse=True):
        if not relative:
            continue
        parent = Path(relative).parent.as_posix()
        if parent == ".":
            parent = ""
        parent_count, parent_size = folder_stats.get(parent, (0, 0))
        own_count, own_size = folder_stats[relative]
        folder_stats[parent] = (parent_count + own_count, parent_size + own_size)

    return records, folder_stats, empty_folders


def is_abi_json(path: Path, size: int) -> bool:
    if size >= MAX_ABI_BYTES:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    entries = data.get("abi") if isinstance(data, dict) else data
    return (
        isinstance(entries, list)
        and all(isinstance(item, dict) and "type" in item for item in entries)
    )


def inclusion_decision(record: FileRecord) -> str:
    path = record.path
    relative = path.relative_to(ROOT)
    parts_lower = [part.lower() for part in relative.parts]

    if is_secret_path(relative):
        return "excluded: secret"
    if path.is_symlink():
        return "excluded: symbolic link"
    if path.suffix.lower() == ".pyc":
        return "excluded: compiled Python bytecode"
    for depth in range(1, len(relative.parts)):
        parent_path = Path(*relative.parts[:depth])
        reason = excluded_directory_reason(parent_path)
        if reason:
            return reason
    if record.size > MAX_FILE_BYTES:
        return "excluded: single file exceeds 10 MB"
    if path.suffix.lower() == ".log" and record.size > 1_000_000:
        return "excluded: log exceeds 1 MB"

    if len(parts_lower) >= 2 and parts_lower[0] == "chain" and any(
        part in {"build", "artifacts"} for part in parts_lower[1:-1]
    ):
        if path.suffix.lower() == ".json" and is_abi_json(path, record.size):
            return ""
        return "excluded: non-ABI build/artifact file"

    if parts_lower and parts_lower[0] == "results":
        if path.suffix.lower() not in RESULT_SUFFIXES:
            return "excluded: file type not selected from results"
        if path.suffix.lower() in IMAGE_SUFFIXES and record.size >= MAX_RESULT_IMAGE_BYTES:
            return "excluded: results image is 3 MB or larger"
        return ""

    if parts_lower and parts_lower[0] in {"tests", "scripts", "demo", "config", "core", "app"}:
        return ""
    if path.suffix.lower() in SOURCE_SUFFIXES:
        return ""
    return "excluded: file type not selected"


def run_capture(command: list[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Command failed: {exc}\n"
    output = result.stdout
    if result.stderr:
        output += ("\n" if output and not output.endswith("\n") else "") + result.stderr
    if result.returncode:
        output += f"\n[exit code: {result.returncode}]\n"
    return output or "(no output)\n"


def run_tests(python: Path) -> str:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "") + " -p no:cacheprovider").strip()
    command = [str(python), "-m", "pytest", "-q", "--maxfail=20"]
    header = f"Command: {python.name} -m pytest -q --maxfail=20\nTimeout: 300 seconds\n\n"
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors="replace",
            timeout=300, check=False,
        )
        body = result.stdout or "(no output)\n"
        return header + body + (f"\n[exit code: {result.returncode}]\n" if result.returncode else "")
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode(errors="replace")
        return header + partial + "\n[Timed out after 300 seconds]\n"
    except OSError as exc:
        return header + f"[Could not run tests: {exc}]\n"


def get_test_summary(output: str) -> str:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if any(word in stripped.lower() for word in ("passed", "failed", "error", "timed out")):
            return stripped
    return "No pytest summary line was produced."


def first_heading(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lstrip().startswith("#"):
                return line.strip()
    except OSError:
        pass
    return "(no heading)"


def folder_tree(folder_stats: dict[str, tuple[int, int]]) -> str:
    lines = ["Workspace folder tree (maximum depth 4; counts/sizes are recursive):"]
    aggregate_names = {".venv", "venv", "env", "node_modules"}
    for relative in sorted(folder_stats, key=lambda value: (value.count("/"), value.lower())):
        if relative and len(Path(relative).parts) > 4:
            continue
        count, total = folder_stats[relative]
        label = ROOT.name if not relative else Path(relative).name + "/"
        indent = "  " * len(Path(relative).parts) if relative else ""
        lines.append(f"{indent}{label} — {count} files, {total / 1_000_000:.3f} MB")
    return "\n".join(lines) + "\n"


def environment_report(python: Path) -> str:
    parts = [
        "Python",
        f"Executable: {python}",
        run_capture([str(python), "--version"]),
        "pip freeze",
        run_capture([str(python), "-m", "pip", "freeze"], timeout=90),
    ]
    for executable, version_args in (("node", ["--version"]), ("npm", ["--version"])):
        parts.extend((f"{executable} version", run_capture([executable, *version_args], timeout=20)))

    package_json = ROOT / "chain" / "hardhat" / "package.json"
    parts.append("chain/hardhat/package.json dependencies")
    if package_json.is_file():
        try:
            package_data = json.loads(package_json.read_text(encoding="utf-8"))
            parts.append(json.dumps({
                key: package_data.get(key, {})
                for key in ("dependencies", "devDependencies", "optionalDependencies")
            }, indent=2))
        except (OSError, json.JSONDecodeError) as exc:
            parts.append(f"Could not parse package.json: {exc}")
    else:
        parts.append("(not present)")
    return "\n".join(parts) + "\n"


def git_report() -> str:
    if not (ROOT / ".git").exists():
        return ""
    return (
        "Current branch\n"
        + run_capture(["git", "branch", "--show-current"])
        + "\ngit status --short\n"
        + run_capture(["git", "status", "--short"])
        + "\ngit log --oneline -n 30\n"
        + run_capture(["git", "log", "--oneline", "-n", "30"])
    )


def drop_category(record: FileRecord) -> str:
    relative = record.path.relative_to(ROOT)
    in_results = "results" in [part.lower() for part in relative.parts]
    suffix = record.path.suffix.lower()
    if in_results and suffix in IMAGE_SUFFIXES and record.size > 500_000:
        return "results_images_over_500kb"
    if in_results and suffix in IMAGE_SUFFIXES:
        return "other_images"
    if suffix in {".json", ".csv"} and record.size > 2_000_000:
        return "large_data_files"
    return ""


def strip_notebook(source: Path, destination: Path) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    for cell in data.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def copy_selected(records: Iterable[FileRecord], stage: Path) -> None:
    for record in records:
        if not record.included:
            continue
        relative = record.path.relative_to(ROOT)
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            if record.path.suffix.lower() == ".ipynb":
                strip_notebook(record.path, destination)
            else:
                shutil.copy2(record.path, destination)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            record.included = False
            record.reason = f"excluded: copy/parse failed ({exc})"
            destination.unlink(missing_ok=True)


def inventory_csv(records: list[FileRecord], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(("relative_path", "size_kb", "extension", "included_in_zip", "reason_if_excluded"))
        for record in sorted(records, key=lambda item: item.relative.lower()):
            writer.writerow((
                record.relative,
                f"{record.size / 1000:.3f}",
                record.extension,
                "True" if record.included else "False",
                "" if record.included else record.reason,
            ))


def top_level_descriptions(records: list[FileRecord]) -> list[str]:
    descriptions = []
    directories = sorted({
        record.path.relative_to(ROOT).parts[0]
        for record in records if len(record.path.relative_to(ROOT).parts) > 1
    }, key=str.lower)
    for directory in directories:
        children = [
            record for record in records
            if record.path.relative_to(ROOT).parts[0] == directory
        ]
        extensions: dict[str, int] = {}
        for child in children:
            if child.counted_files != 1 and child.path.is_dir():
                continue
            ext = child.extension
            extensions[ext] = extensions.get(ext, 0) + 1
        common = sorted(extensions.items(), key=lambda item: (-item[1], item[0]))[:3]
        detail = ", ".join(f"{ext} ({count})" for ext, count in common) or "no files found"
        descriptions.append(f"- {directory}/ — {len(children)} inventoried entries; mainly {detail}.")
    return descriptions


def snapshot_markdown(
    records: list[FileRecord],
    folder_stats: dict[str, tuple[int, int]],
    empty_folders: set[str],
    test_output: str,
    created: dt.datetime,
    zip_size: int | None,
) -> str:
    included = [record for record in records if record.included]
    excluded = [record for record in records if not record.included]
    total_count = sum(record.counted_files for record in records)
    project_bytes = folder_stats.get("", (0, 0))[1]
    notebooks = sorted(
        (record.path for record in records if record.path.suffix.lower() == ".ipynb"),
        key=lambda path: path.relative_to(ROOT).as_posix().lower(),
    )
    notebook_lines = [
        f"- {path.relative_to(ROOT).as_posix()} — {first_heading(path)}"
        for path in notebooks
    ] or ["- No notebooks found."]
    markdown_files = sorted(
        (
            record.path for record in records
            if record.path.suffix.lower() == ".md"
            and (record.path.parent == ROOT or record.path.parent == ROOT / "docs")
        ),
        key=lambda path: path.relative_to(ROOT).as_posix().lower(),
    )
    heading_lines = [
        f"- {path.relative_to(ROOT).as_posix()} — {first_heading(path)}"
        for path in markdown_files
    ] or ["- No root/docs Markdown files found."]
    top_level = top_level_descriptions(records) or ["- No top-level folders found."]

    issues: list[str] = []
    if empty_folders:
        issues.extend(f"Empty folder: {folder}" for folder in sorted(empty_folders))
    for name in ("app", "chain", "config", "core", "demo", "docs", "scripts", "tests"):
        folder = ROOT / name
        if folder.is_dir() and not (folder / "README.md").is_file():
            issues.append(f"{name}/ has no README.md.")
    if any(word in test_output.lower() for word in ("failed", "error", "timed out", "could not run")):
        issues.append("Pytest did not complete successfully; see TEST_RESULTS.txt.")
    if not issues:
        issues.append("No obvious empty-folder, README, or test issues detected.")

    lines = [
        "# QICAS Project Snapshot",
        "",
        f"- Created: {created.strftime('%Y-%m-%d %H:%M:%S %Z').strip()}",
        f"- Total project size: {project_bytes / 1_000_000:.3f} MB",
        f"- ZIP size: {f'{zip_size / 1_000_000:.3f} MB' if zip_size is not None else 'calculating'}",
        f"- Project files inventoried: {total_count}",
        f"- Project files included: {sum(record.counted_files for record in included)}",
        f"- Project files excluded: {sum(record.counted_files for record in excluded)}",
        "",
        "## Top-level folders",
        *top_level,
        "",
        "## Notebooks",
        *notebook_lines,
        "",
        "## Root and docs Markdown headings",
        *heading_lines,
        "",
        "## Test result",
        get_test_summary(test_output),
        "",
        "## Obvious issues",
        *(f"- {issue}" for issue in issues),
        "",
        "Inventory scope: existing workspace files outside `_snapshot`; large excluded directories "
        "(.venv, venv, env, node_modules) are represented by aggregate inventory rows.",
    ]
    return "\n".join(lines) + "\n"


def staged_size(stage: Path) -> int:
    total = 0
    for current, _, files in os.walk(stage):
        for name in files:
            try:
                total += (Path(current) / name).stat().st_size
            except OSError:
                continue
    return total


def write_zip(stage: Path, destination: Path) -> int:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for current, _, files in os.walk(stage):
            for name in sorted(files):
                file_path = Path(current) / name
                archive.write(file_path, file_path.relative_to(stage).as_posix())
    return destination.stat().st_size


def main() -> int:
    created = dt.datetime.now().astimezone()
    zip_path = SNAPSHOT_DIR / f"qicas_snapshot_{created.strftime('%Y%m%d_%H%M')}.zip"
    if zip_path.exists():
        raise FileExistsError(f"Refusing to overwrite an existing snapshot: {zip_path}")
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    records, folder_stats, empty_folders = scan_project()
    for record in records:
        if record.path.is_dir():
            record.reason = record.reason or "excluded: directory contents summarized"
            continue
        record.reason = inclusion_decision(record)
        record.included = not record.reason

    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise FileNotFoundError(f"Project virtual-environment Python not found: {python}")

    test_output = run_tests(python)
    with tempfile.TemporaryDirectory(prefix="snapshot_stage_", dir=SNAPSHOT_DIR) as temporary:
        stage = Path(temporary)
        copy_selected(records, stage)
        (stage / "FOLDER_TREE.txt").write_text(folder_tree(folder_stats), encoding="utf-8")
        (stage / "ENVIRONMENT.txt").write_text(environment_report(python), encoding="utf-8")
        (stage / "TEST_RESULTS.txt").write_text(test_output, encoding="utf-8")
        git_text = git_report()
        if git_text:
            (stage / "GIT_STATUS.txt").write_text(git_text, encoding="utf-8")

        inventory_path = stage / "FILE_INVENTORY.csv"
        snapshot_path = stage / "PROJECT_SNAPSHOT.md"
        for record in records:
            if record.included:
                record.size = (stage / record.path.relative_to(ROOT)).stat().st_size

        # Reserve a small margin for ZIP directory metadata; drop eligible files
        # in the specified order if the staged, uncompressed snapshot is too large.
        for record in records:
            record.dropped_category = drop_category(record) if record.included else ""
        safety_budget = MAX_ARCHIVE_BYTES - 1_000_000
        while True:
            inventory_csv(records, inventory_path)
            snapshot_path.write_text(
                snapshot_markdown(
                    records, folder_stats, empty_folders, test_output, created, None,
                ),
                encoding="utf-8",
            )
            total = staged_size(stage)
            if total <= safety_budget:
                break
            dropped = False
            for category in DROP_ORDER:
                options = sorted(
                    (record for record in records if record.included and record.dropped_category == category),
                    key=lambda item: item.size,
                    reverse=True,
                )
                for record in options:
                    if total <= safety_budget:
                        break
                    (stage / record.path.relative_to(ROOT)).unlink(missing_ok=True)
                    record.included = False
                    record.reason = f"excluded: size safety drop ({category})"
                    total -= record.size
                    dropped = True
                if total <= safety_budget:
                    break
            if not dropped:
                raise RuntimeError(
                    f"Snapshot contents exceed the safety budget ({total / 1_000_000:.2f} MB) "
                    "and no permitted size-priority files remain to drop."
                )

        inventory_csv(records, inventory_path)
        snapshot_path.write_text(
            snapshot_markdown(records, folder_stats, empty_folders, test_output, created, None),
            encoding="utf-8",
        )
        archive_size = write_zip(stage, zip_path)
        snapshot_path.write_text(
            snapshot_markdown(
                records, folder_stats, empty_folders, test_output, created, archive_size,
            ),
            encoding="utf-8",
        )
        archive_size = write_zip(stage, zip_path)

        while archive_size >= MAX_ARCHIVE_BYTES:
            dropped = False
            for category in DROP_ORDER:
                options = sorted(
                    (record for record in records if record.included and record.dropped_category == category),
                    key=lambda item: item.size,
                    reverse=True,
                )
                if options:
                    record = options[0]
                    (stage / record.path.relative_to(ROOT)).unlink(missing_ok=True)
                    record.included = False
                    record.reason = f"excluded: final ZIP size safety drop ({category})"
                    record.size = 0
                    dropped = True
                    break
            if not dropped:
                zip_path.unlink(missing_ok=True)
                raise RuntimeError("Final ZIP is at or above the 100 MB hard cap.")
            inventory_csv(records, inventory_path)
            snapshot_path.write_text(
                snapshot_markdown(records, folder_stats, empty_folders, test_output, created, archive_size),
                encoding="utf-8",
            )
            archive_size = write_zip(stage, zip_path)
        assert archive_size < MAX_ARCHIVE_BYTES, "Snapshot ZIP must be under 100 MB."

    included = [record for record in records if record.included]
    excluded = [record for record in records if not record.included]
    largest_excluded_files = [
        (record.size, record.relative, record.reason)
        for record in excluded if record.counted_files == 1
    ]
    largest_excluded_files.extend(
        (size, relative, "excluded: inside an aggregated environment/dependency folder")
        for size, relative in AGGREGATE_LARGEST_FILES
    )
    largest_excluded = sorted(largest_excluded_files, reverse=True)[:10]
    largest_included = sorted(included, key=lambda record: record.size, reverse=True)[:10]
    print("\nSNAPSHOT REPORT")
    print(f"ZIP: {zip_path}")
    print(f"ZIP size: {archive_size / 1_000_000:.3f} MB")
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive_file_count = len(archive.namelist())
    print(f"Included files in ZIP: {archive_file_count}")
    print(f"Excluded files: {sum(record.counted_files for record in excluded)}")
    print("10 largest excluded files:")
    for size, relative, reason in largest_excluded:
        print(f"  {size / 1_000_000:9.3f} MB  {relative} — {reason}")
    print("10 largest included files:")
    for record in largest_included:
        print(f"  {record.size / 1_000_000:9.3f} MB  {record.relative}")
    print(f"Test summary: {get_test_summary(test_output)}")
    print(f"Asserted ZIP under 100 MB: {archive_size < MAX_ARCHIVE_BYTES}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Snapshot creation failed: {exc}", file=sys.stderr)
        raise
