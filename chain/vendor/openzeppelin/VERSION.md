# Vendored OpenZeppelin Contracts

- **Package:** `@openzeppelin/contracts` **5.4.0** (npm, released 2025-07-17), MIT licence (`LICENSE` here, from
  the `v5.4.0` git tag).
- **Tarball SHA-256:** `4e4d51f18935b32f0c877bf666ac37f5e5a98e75f03e7a77eb7569f84701f680`
  (`openzeppelin-contracts-5.4.0.tgz` from `npm pack @openzeppelin/contracts@5.4.0`).
- **What is here:** only the 21 files that `chain/contracts/QicasCredit.sol` and `ScheduleCertificate.sol`
  import (transitively), copied unmodified except line endings normalised to LF.
- **Why vendored:** `node chain/compile.js` must stay offline and reproducible (no `node_modules` lookup for
  Solidity sources). `compile.js` resolves `@openzeppelin/contracts/...` to `chain/vendor/openzeppelin/contracts/`.
- **Why 5.4.0 and not newer:** all contracts compile with solc 0.8.24, `evmVersion: paris` (README §9.3). From
  5.5.0 on, `utils/Strings.sol` imports `utils/Bytes.sol`, which uses the Cancun opcode `mcopy` and does not
  compile for paris. 5.4.0 is the newest 5.x release whose needed files compile for paris.
- **Refresh (only with a reason):**
  ```powershell
  npm pack @openzeppelin/contracts@5.4.0; tar -xzf openzeppelin-contracts-5.4.0.tgz
  node chain/vendor_openzeppelin.js package
  node chain/compile.js --check
  ```
