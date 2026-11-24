// Vendor ONLY the OpenZeppelin files that chain/contracts/*.sol import (transitively) into
// chain/vendor/openzeppelin/contracts/, so `node chain/compile.js` stays offline and reproducible.
//
//   npm pack @openzeppelin/contracts@5.6.1 && tar -xzf openzeppelin-contracts-5.6.1.tgz
//   node chain/vendor_openzeppelin.js <path to the extracted "package" folder>
//
// Files are copied byte-for-byte except that line endings are normalised to LF (the source text is part of
// the bytecode metadata hash). The pinned version is recorded in chain/vendor/openzeppelin/VERSION.md.
"use strict";
const fs = require("fs");
const path = require("path");

const PREFIX = "@openzeppelin/contracts/";
const ROOT = __dirname;
const OUT = path.join(ROOT, "vendor", "openzeppelin", "contracts");

function importsOf(src) {
  const re = /import\s+(?:\{[^}]*\}\s+from\s+)?"([^"]+)"/g;
  const out = [];
  let m;
  while ((m = re.exec(src))) out.push(m[1]);
  return out;
}

function main() {
  const pkg = process.argv[2];
  if (!pkg || !fs.existsSync(path.join(pkg, "package.json"))) {
    console.error("usage: node chain/vendor_openzeppelin.js <extracted @openzeppelin/contracts package dir>");
    process.exit(2);
  }
  const version = JSON.parse(fs.readFileSync(path.join(pkg, "package.json"), "utf8")).version;
  const todo = [];
  for (const f of fs.readdirSync(path.join(ROOT, "contracts")).filter((f) => f.endsWith(".sol"))) {
    for (const imp of importsOf(fs.readFileSync(path.join(ROOT, "contracts", f), "utf8"))) {
      if (imp.startsWith(PREFIX)) todo.push(imp.slice(PREFIX.length));
    }
  }
  const seen = new Set();
  while (todo.length) {
    const rel = path.posix.normalize(todo.pop());
    if (seen.has(rel)) continue;
    seen.add(rel);
    const src = fs.readFileSync(path.join(pkg, rel), "utf8").replace(/\r\n/g, "\n");
    const dst = path.join(OUT, rel);
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.writeFileSync(dst, src);
    for (const imp of importsOf(src)) {
      todo.push(imp.startsWith(PREFIX) ? imp.slice(PREFIX.length) : path.posix.join(path.posix.dirname(rel), imp));
    }
  }
  console.log(`vendored ${seen.size} files of @openzeppelin/contracts@${version}:`);
  for (const f of [...seen].sort()) console.log("  " + f);
}

main();
