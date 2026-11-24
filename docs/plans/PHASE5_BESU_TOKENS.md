# Phase 5 — Consortium chain (Besu QBFT) + OpenZeppelin tokens (plan)

- **Status:** **DONE 2026-11-23** (results: README §18, PROJECT_PLAN.md "Phase 5 results"). All decisions approved
  2026-11-13 + build decisions 2026-11-23; build decisions A1–A10 **confirmed by the user 2026-11-23** (D2).
- **Planned:** 2026-11-13
- **Parent:** `docs/PROJECT_PLAN.md` → Phase 5
- **Invariant:** in-memory mode stays the default; V1 `CarbonScheduleMarket.sol` and its built-in minimal
  token stay byte-identical; default pytest stays offline.

## Prerequisites — what the user must install or do

| Item | Status (checked 2026-11-13) | Action |
|---|---|---|
| **Docker Desktop** (WSL2 backend) | ✔ installed: Docker 28.4.0, Compose v2.39.2, WSL2 distro `docker-desktop` | **Start Docker Desktop.** Engine was not running (`dockerDesktopLinuxEngine` pipe not found). Check `docker info` prints a server version. |
| Docker memory | 15.7 GB RAM | 4 Besu nodes need ~3–4 GB with `-Xmx768m` each; WSL2 default (~7.8 GB) is enough. |
| **Besu image** | not pulled | `docker pull hyperledger/besu:<tag>`; exact tag pinned in `docker-compose.yml` after checking Docker Hub **[VERIFY tag]**. ~500 MB. |
| **Node.js 20 LTS** | ✘ `node` → `C:\nvm4w\nodejs\node.ps1`, prints nothing | `nvm install 20`, `nvm use 20`, check `node --version`. **Required** for compiling OpenZeppelin imports with solc-js. |
| npm packages (`solc@0.8.24`, `@openzeppelin/contracts@5.x`, exact pins) | — | installed by Claude with `npm ci` in `chain/` after approval |
| Python packages | ✔ nothing new | web3 8.0.0 has `ExtraDataToPOAMiddleware` and `SignAndSendRawMiddlewareBuilder` (both checked) |

Other prerequisites:

| # | Prerequisite | Status |
|---|---|---|
| P1 | Phase 4 V2 market (or V2 created here if Phase 4 chose option (b)) | pending |
| P2 | Phases 3–4 contracts for the full V2 flow | pending |

## Open decisions

All three are resolved — see "Decisions (approved)" below.

1. ~~Certificates transferable or soulbound?~~ — resolved: **soulbound**.
2. ~~Include the validator-vote demo?~~ — resolved: **yes, as an optional test**.
3. ~~Order of the queued phases~~ — resolved (the suggested 3 → 4 → 5 → 2 → 1 is superseded).

## Decisions (approved)

Recorded 2026-11-13.

1. **Schedule certificates are SOULBOUND**, non-transferable ERC-721 attestations.
   **Credits remain a normal, transferable ERC-20** (`QicasCredit`, including `retire`).
   Effect on this plan:
   - `ScheduleCertificate.sol`: every transfer path (`transferFrom`, `safeTransferFrom`) and approval path
     (`approve`, `setApprovalForAll`) reverts; only minting to the winner is allowed. This replaces
     "transferable" in §3.
   - `tests/test_tokens.py` test 6: ERC-20 transfer/approve still tested as normal; for the certificate,
     transfer and approval attempts must **revert**, and `supportsInterface(0x80ac58cd)` still holds.
   - Honest-claims wording (§6): a certificate is an attestation bound to the winning address, not a
     tradeable asset.
2. **Include the validator add/remove vote test, marked optional** (`scripts/besu_validator_vote.py` and
   `tests/test_besu.py` item 5), so it does not gate the phase.
3. **Build order:** Phase 5 is built after Phases 3 and 4. Full order: Phase 2 → Phase 6-lite → Phase 1 →
   Phases 3, 4, 5 → full Phase 6.

Further decisions approved by the user for the build (2026-11-23, pre-approved in the build prompt):

4. **Validators:** 4 QBFT validators (tolerates 1 faulty), block period 2 s, test-only chainId, deterministic
   genesis and keys labelled TEST ONLY.
5. **Besu image:** an exact released `hyperledger/besu` tag (not `latest`), at least 2 weeks old; version and
   digest recorded in `docker-compose.yml` and the README.
6. **OpenZeppelin:** one exact 5.x version, **vendored** (only the needed files, with its LICENSE and a version
   note) in `chain/vendor/openzeppelin/`, so `chain/compile.js` stays offline; same compiler settings (solc
   0.8.24, paris, viaIR, 200 runs) and LF line endings. This replaces "resolve from `chain/node_modules`" in §3.
7. **Certificates soulbound** (all transfers + approvals revert), **credits a standard transferable ERC-20**;
   only the market (MINTER_ROLE) mints; include "admin renounced → no further minting".
8. **Validator add/remove vote test:** implemented, opt-in flag.
9. Any other decision: take this plan's recommendation and record it under "Decisions (assumed, please confirm)" (A1–A10 below, since confirmed).

## Decisions (approved) — build decisions A1–A10

Taken during the build (2026-11-23) under decision 9; each follows this plan's intent. **All ten confirmed by the user
on 2026-11-23 (decision D2)**; they were listed here as "assumed, please confirm" until then.

| # | Topic | Decision (approved) | Why |
|---|---|---|---|
| A1 | OpenZeppelin version | **5.4.0** (2025-07-17) | From 5.5.0 on, `Strings.sol` imports `Bytes.sol`, which uses the Cancun opcode `mcopy` and does not compile for `paris` (tried 5.6.1: compile error). 5.4.0 is the newest 5.x that compiles unchanged. |
| A2 | Token file location | `chain/contracts/QicasCredit.sol`, `chain/contracts/ScheduleCertificate.sol` (not a `tokens/` subfolder) | `chain/compile.js` compiles one contract per top-level file into `chain/build/<Name>.json`; keeps the toolchain unchanged. |
| A3 | Market integration | New **`CarbonScheduleMarketV3.sol`** = V2 (oracle-fed) + external tokens; V2 is **not** modified | §3 said "V2 `finalize` mints"; changing V2 would change the Phase 4 artifact and its recorded results. V3 drops the built-in minimal token (credits live in `QicasCredit`). V1 and V2 stay byte-identical. |
| A4 | "Admin renounced" | **The minter set is frozen** (no new minters can be granted): after `renounceRole(DEFAULT_ADMIN_ROLE)` on both tokens nobody can grant `MINTER_ROLE` again and the deployer can neither mint nor add minters. **The market contract keeps its minter role**, so protocol minting continues | Matches §3 step 6 ("renounce deployer admin") and the E3 row "minting after admin renounced". |
| A5 | Besu version | `hyperledger/besu:26.10.2` (2026-10-26), digest `sha256:bc599f5ef95a3d5d03f966cd2c1f7dfd7353834c84bc5651ffb4af884860a2c7` | Newest patch release that is ≥ 2 weeks old (26.11.1 is 5 days old). |
| A6 | RPC ports | All 4 validators publish JSON-RPC on `127.0.0.1:8545–8548` (loopback only) | The optional vote test needs `qbft_proposeValidatorVote` on a majority of validators; §1 had only validator1. |
| A7 | Certificate gap field | `certifiedGapBps` = `PriceMarket.finalizedGapBps(marketId)` of a market linked to the same V3 epoch (Phase 4 fraud-proof bound); **10000 = no certified bound** when none is given/finalised | The fraud-proof bound is the only trust-minimised gap; the Phase 3 `certifiedGapBps` assumes an honest submitter. |
| A8 | chainId | **1338** (§1), labelled TEST ONLY | Plan value; ≠ Hardhat 31337 / eth-tester 131277322940537. |
| A10 | Bound claim on Besu (§4 test 4) | `PriceMarket.CHALLENGE_WINDOW` is a **1-hour contract constant** (Phase 3/4 artifact). On Besu the test claims a bound and checks that an immediate `finalizeBound` reverts `WindowOpen` (window enforced in real time); claim → window → finalise runs in-memory with time travel | A 20 s window would need a Phase 4 contract change. |
| A9 | Opt-in flags | `QICAS_BESU=1` runs `tests/test_besu.py` (also skips cleanly if nothing answers on `127.0.0.1:8545`); `QICAS_BESU_VOTE=1` adds the validator vote test | Default pytest stays offline (invariant). |

---

## 1. Besu QBFT network: `chain/besu/`

| File | Contents |
|---|---|
| `qbftConfigFile.json` | input for `besu operator generate-blockchain-config`: 4 validators, `blockperiodseconds: 2`, `requesttimeoutseconds: 4`, `epochlength: 30000`, chainId **1338** (≠ Hardhat 31337) |
| `genesis.json` + `nodes/validator{1..4}/key` | generated once by a script and committed; **test-only keys** with a `TEST KEYS — NEVER USE ON A REAL NETWORK` README. Genesis `alloc` funds 10 deterministic test accounts (stakes/bonds are paid in ETH). |
| `docker-compose.yml` | 4 nodes, fixed IPs, bridge network; validator1 = bootnode; only validator1 publishes RPC on `127.0.0.1:8545`; `--min-gas-price=0`, `zeroBaseFee: true`, `--rpc-http-api=ETH,NET,WEB3,QBFT,TXPOOL`, `JAVA_OPTS=-Xmx768m`; named volumes |
| `scripts/besu_up.ps1` / `besu_down.ps1` / `besu_reset.ps1` | up: `docker compose up -d`, wait for block > 0 and 4 validators in `qbft_getValidatorsByBlockNumber`; down: stop; reset: wipe volumes |
| `README.md` | validator ↔ provider (provider-A…D), ports, troubleshooting |

**Optional (recommended):** `scripts/besu_validator_vote.py` adds a 5th validator via
`qbft_proposeValidatorVote`, then removes it ("the consortium governs who validates").

## 2. Python client: `besu` mode

- `Chain.start(mode="besu", rpc_url=…)` injects `ExtraDataToPOAMiddleware` and
  `SignAndSendRawMiddlewareBuilder` with the deterministic test keys (existing `transact({"from": …})`
  works unchanged); `gasPrice=0`.
- `memory` (default) and `rpc` (Hardhat) branches unchanged → default output byte-identical.
- `demo/run_demo.py`: `--mode` accepts `besu`. `config/besu.yaml`: `chain.mode: besu`.
- Time-based tests (challenge windows) **stay in-memory**; on Besu `config/besu.yaml` sets a 20 s window and
  the smoke test really waits.

## 3. OpenZeppelin tokens: `chain/contracts/tokens/`

One pinned OpenZeppelin 5.x version, `pragma ^0.8.24`, same compiler settings.

**`QicasCredit.sol` (ERC-20):** `ERC20` + `ERC20Burnable` + `AccessControl`, `decimals() = 0`
(1 token = 1 g CO₂e **net** verified saving). `MINTER_ROLE` held only by V2. `retire(amount, beneficiary,
reason)` burns and emits `Retired` (prevents double counting; a transfer doesn't).

**`ScheduleCertificate.sol` (ERC-721):** `ERC721` + `AccessControl`; one per finalised epoch,
`tokenId = epochId`, minted to the winner. On-chain data: Merkle root, instance hash, baseline carbon,
winner carbon, net saving µg, `certifiedGapBps`, oracle `requestId`, market address. `tokenURI()` returns
on-chain `data:application/json;base64,…` via OpenZeppelin `Base64` (no IPFS).

**`CarbonScheduleMarketV2.sol`:** `finalize` calls `credit.mint(winner, netGrams)` and
`cert.mint(winner, epochId, data)`. Token addresses fixed in the constructor. `chain/deploy_v2.py`:
1. oracle; 2. credit + certificate; 3. V2 market; 4. `PriceMarket`; 5. grant `MINTER_ROLE` on both tokens to
V2; 6. (flag) renounce deployer admin.

**V1 + built-in token stay byte-identical** and remain the default demo; Phase 3's artifact guard keeps
checking.

**Compile:** `chain/compile.js` import callback resolves `@openzeppelin/…` from `chain/node_modules`. New
artifacts `chain/build/{QicasCredit, ScheduleCertificate, CarbonScheduleMarketV2}.json`.
`chain/package.json` + `package-lock.json` committed (exact versions); `chain/node_modules/` git-ignored.

## 4. Tests

**`tests/test_tokens.py` (in-memory, default pytest):**
1. Only V2 can mint; others → AccessControl revert.
2. After V2 `finalize`: credit balance = ⌊net saving µg / 10⁶⌋ = V1's credits on the same instance.
3. Certificate owner = winner; on-chain data = Python values (Merkle root vs `core/merkle.py`, gap vs
   `gap_bps`).
4. `tokenURI` decodes to valid JSON with the same fields; `Retired` reduces supply and emits.
5. No second certificate for the same epoch.
6. ERC-20/721 standard behaviour: transfer, approve, `supportsInterface(0x80ac58cd)`.
7. V1 artifact unchanged; existing tests pass.

**`tests/test_besu.py` (`@pytest.mark.besu`, auto-skipped when nothing answers on `127.0.0.1:8545`; run with
`.\.venv\Scripts\python.exe -m pytest -q -m besu`):**
1. 4 validators active, blocks produced.
2. **V1 demo on Besu = in-memory scores:** same 4 accepted scores, same 3 attacker outcomes, same winner and
   Merkle root (gas reported, not asserted).
3. V2 flow: oracle snapshot → market → finalise → ERC-20 balance + ERC-721 certificate correct.
4. Short-window bound claim finalised after a real wait.
5. Optional: validator vote add/remove.

## 5. Measurements: `experiments/besu_vs_memory.py` → `results/besu/`

Per chain, seed-7 instance: gas per tx type; send-to-confirmation time; total demo wall-clock; blocks
produced; carbon overhead at existing sensitivity parameters. Extra report row: **block energy of a
4-validator PoA network** = node count × assumed W per node — labelled a parameter, not a measurement.

## 6. Honest claims

- A local 4-validator QBFT network on one laptop *models* a provider consortium; not production, says
  nothing about real providers' willingness.
- Test keys and zero gas price are test-network only.
- Credits/certificates are only as good as the verification behind them (oracle honest majority, a watcher
  per window). Retirement prevents double counting **within this ledger only**.

## 7. After approval

1. User: start Docker Desktop, fix Node, pull Besu image.
2. Generate genesis + keys; compose file; tokens; V2 (if not already); deploy script; client mode; tests.
3. Compile (§9.3-B, OpenZeppelin imports); confirm V1 artifact unchanged.
4. Default pytest → `demo.run_demo` (must match RUN_GUIDE.md) → Besu up → `pytest -m besu` →
   `run_demo --mode besu` → experiment.
5. Update README §9 (new §9.4 Besu), RUN_GUIDE.md, PROJECT_PLAN.md status, CLAUDE.md commands.
6. Commit, without pushing.
