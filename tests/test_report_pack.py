"""Report-pack tooling (scripts/report_diagrams.py, scripts/make_report_pack.py): offline, headless."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_diagrams_render_as_png(tmp_path):
    import report_diagrams
    paths = report_diagrams.make_all(tmp_path)
    assert len(paths) == 7
    for p in paths:
        assert p.suffix == ".png" and p.stat().st_size > 20_000, p


def test_pack_secret_scan_knows_the_test_keys():
    import make_report_pack as mrp
    keys = mrp.known_test_keys()
    assert len(keys) == 19 and all(len(k) == 64 for k in keys)
    fake = "EM_API" + "_KEY = " + '"' + "abcdefgh" + "ijklmnop1234" + '"'   # built at run time: repo scan stays clean
    assert any(p.search(fake) for p in mrp.SECRET_PATTERNS)


def test_pack_and_zip_are_git_ignored():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/report_pack/" in text and "/report_pack.zip" in text
