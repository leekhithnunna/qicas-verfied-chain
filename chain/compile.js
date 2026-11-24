// Reproducible solc-js compile of the contracts in chain/contracts (README section 9.3, option B).
//
//   node chain/compile.js            compile every contract below and write chain/build/<Name>.json
//   node chain/compile.js --check    compile and compare against chain/build/*.json; write nothing
//   node chain/compile.js --only PriceMarket   restrict to one contract (combinable with --check)
//
// Settings are fixed by README section 9.3: solc 0.8.24, optimizer 200 runs, viaIR, evmVersion paris.
// CarbonScheduleMarket.json (the V1 artifact) is never rewritten if its bytecode or ABI would change:
// the script refuses, because the default demo's seed-7 output depends on its deploy gas.
"use strict";
const fs = require("fs");
const path = require("path");
const solc = require("solc");

const EXPECTED_VERSION = "0.8.24+commit.e11b9ed9.Emscripten.clang";
const ROOT = __dirname;
// one contract per file, named like the file (chain/contracts/<Name>.sol -> chain/build/<Name>.json)
const CONTRACTS = fs.readdirSync(path.join(ROOT, "contracts")).filter((f) => f.endsWith(".sol")).map((f) => f.slice(0, -4)).sort();
const PROTECTED = new Set(["CarbonScheduleMarket"]);

// Phase 5: `@openzeppelin/contracts/...` imports resolve to the VENDORED copy in chain/vendor/openzeppelin
// (exact pinned version, see VERSION.md there; refreshed with chain/vendor_openzeppelin.js). No network access,
// no node_modules lookup. Contracts without imports (V1, V2, PriceMarket, CarbonOracle) never call this.
const OZ_PREFIX = "@openzeppelin/contracts/";
const OZ_DIR = path.join(ROOT, "vendor", "openzeppelin", "contracts");

function findImports(importPath) {
  if (!importPath.startsWith(OZ_PREFIX)) return { error: `unsupported import ${importPath} (only ${OZ_PREFIX}*)` };
  const file = path.join(OZ_DIR, importPath.slice(OZ_PREFIX.length));
  if (!fs.existsSync(file)) return { error: `${importPath} is not vendored; run chain/vendor_openzeppelin.js` };
  return { contents: fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n") };
}

function compileOne(name) {
  // Normalise line endings: the source text is hashed into the bytecode's metadata, and a Windows checkout
  // (core.autocrlf=true) would otherwise turn LF into CRLF and change the bytecode. Artifacts are built from LF.
  const src = fs.readFileSync(path.join(ROOT, "contracts", `${name}.sol`), "utf8").replace(/\r\n/g, "\n");
  const input = {
    language: "Solidity",
    sources: { [`${name}.sol`]: { content: src } },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      viaIR: true,
      evmVersion: "paris",
      outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
    },
  };
  const out = JSON.parse(solc.compile(JSON.stringify(input), { import: findImports }));
  const errors = (out.errors || []).filter((e) => e.severity === "error");
  for (const e of out.errors || []) console.error(e.formattedMessage);
  if (errors.length) throw new Error(`${name}: compilation failed`);
  const c = out.contracts[`${name}.sol`][name];
  return { contractName: name, compiler: solc.version(), abi: c.abi, bytecode: "0x" + c.evm.bytecode.object };
}

function main() {
  const args = process.argv.slice(2);
  const check = args.includes("--check");
  const onlyIdx = args.indexOf("--only");
  const names = onlyIdx >= 0 ? [args[onlyIdx + 1]] : CONTRACTS;
  if (solc.version() !== EXPECTED_VERSION) {
    console.error(`solc ${solc.version()} != ${EXPECTED_VERSION}; run: npm install (in chain/)`);
    process.exit(2);
  }
  let bad = 0;
  for (const name of names) {
    const art = compileOne(name);
    const file = path.join(ROOT, "build", `${name}.json`);
    const old = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
    const same = old && old.bytecode === art.bytecode && JSON.stringify(old.abi) === JSON.stringify(art.abi);
    const size = (art.bytecode.length - 2) / 2;
    if (check) {
      console.log(`${name}: ${same ? "IDENTICAL" : "DIFFERENT"} to chain/build/${name}.json (${size} bytes initcode)`);
      if (!same) bad++;
      continue;
    }
    if (PROTECTED.has(name) && old && !same) {
      console.error(`${name}: recompiled artifact differs from the committed one; refusing to overwrite (protected).`);
      bad++;
      continue;
    }
    if (same) {
      console.log(`${name}: unchanged (${size} bytes initcode)`);
      continue;
    }
    fs.writeFileSync(file, JSON.stringify(art, null, 2) + "\n");
    console.log(`${name}: wrote chain/build/${name}.json (${size} bytes initcode)`);
  }
  process.exit(bad ? 1 : 0);
}

main();
