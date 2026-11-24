# Phase 4 — Trust layer (plan)

- **Status:** DONE (2026-11-19). Decisions assumed from the recommendations, confirmed by the user on 2026-11-19 (see below). Results: `docs/PROJECT_PLAN.md` → "Phase 4 results"; README §16.
- **Planned:** 2026-11-13
- **Parent:** `docs/PROJECT_PLAN.md` → Phase 4
- **Invariant:** V1 `CarbonScheduleMarket.sol` stays byte-identical; default demo unchanged.

## Prerequisites

| # | Prerequisite | Owner | Status |
|---|---|---|---|
| P1 | **Phase 3 implemented** (`PriceMarket.sol`; fraud proofs extend it) | Claude | done |
| P2 | **Working Node.js** (same blocker as Phase 3) | user | done (Node v20.20.2) |
| P3 | EIP-712 signing in Python | — | done: `eth_account 0.14.0` has `encode_typed_data`, no new dependency |
| P4 | Time control for challenge windows | — | done: in-memory chain `time_travel` tested (1-hour jump); Hardhat uses `evm_increaseTime` |
| P5 | Phase 1 snapshot to sign | — | optional: signers can sign config values until Phase 1 lands |
| P6 | Answers to the open decisions below | user | done (2026-11-19, assumed decisions confirmed) |

Block gas limit observed on the in-memory chain: ~30 M.

## Open decisions

1. Oracle consumer: **(a) V2 market reads the oracle, V1 frozen** (recommended), or (b) oracle feeds only
   `PriceMarket`?
2. Signer bonds and equivocation slashing: include now (recommended) or defer?
3. ~~Order of the queued phases~~ — resolved, see below (the suggested 3 → 4 → 2 → 1 is superseded).

## Decisions (approved)

Recorded 2026-11-13.

- **Open decision 3 — resolved (build order):** Phase 4 is built after Phase 3 and before Phase 5. Full
  order: Phase 2 → Phase 6-lite → Phase 1 → Phases 3, 4, 5 → full Phase 6.
- Open decisions 1 (oracle consumer: V2 market vs `PriceMarket` only) and 2 (signer bonds + equivocation
  slashing) are **still open**.

## Decisions (assumed, confirmed by the user 2026-11-19)

All four items below were confirmed by the user on 2026-11-19. Recorded 2026-11-19. Phase 4 was started automatically after Phase 3 (Phase 1 data still missing). The open
decisions were not answered, so the plan's recommended options were used:

- **Decision 1 → (a):** `CarbonScheduleMarketV2.sol` (copy of V1 whose `publish` reads region carbon from a
  finalised `CarbonOracle` snapshot); V1 stays frozen and byte-identical. `PriceMarket` checks its carbon values
  against the same snapshot with `bindOracle` (equality check) instead of a second `openMarket` signature.
- **Decision 2 → include now:** signer bonds (`depositBond`, anyone may fund a signer) and `proveEquivocation`
  (whole bond slashed, signer removed). Release of signer bonds is not implemented (Phase 5).
- **Assumed detail (deviation from §B.4):** Phase 3's `certifiedGapBps` keeps its meaning ("assuming an honest
  submitter"); the fraud-proof-certified gap is a new view `finalizedGapBps` that uses only finalised bounds.
  This keeps Phase 3 results and tests unchanged.
- **Assumed detail:** corrections (`challenge`) are also accepted when no claim is active (no reward); a claim
  window still closes challenges for that claim (`WindowClosed`) until `finalizeBound`.

---

## A. Multi-signer EIP-712 oracle: `chain/contracts/CarbonOracle.sol`

Single file, no dependencies (OpenZeppelin arrives in Phase 5).

```
Domain:  name "QICAS Carbon Oracle", version "1", chainId, verifyingContract
CarbonReport(uint256 requestId, bytes32 zone, uint64 hourStart, uint32 ciGPerKwh, bytes32 sourceHash, uint64 issuedAt)
```
`zone` = fixed code, e.g. `keccak256("SE-SE3")` (Phase 1 zones); `sourceHash` = SHA-256 of the raw file read.

**Flow:**
1. **`requestSnapshot(zones[], hourStart, deadline)`** (owner) → `requestId`.
2. **`submitReports(reports[], sigs[])`** (anyone relays; signature proves signer). Checks in order:
   1. signature format: length 65, v ∈ {27, 28}, **low-s** (s ≤ n/2), recovered address ≠ 0;
   2. registered signer;
   3. `requestId` and `hourStart` match the request (stops replayed snapshots / wrong hours);
   4. freshness: `issuedAt` ≤ block time and block time − `issuedAt` ≤ `maxAge`;
   5. before `deadline`;
   6. one report per (signer, request, zone).
3. **`finalizeSnapshot(requestId)`:** each zone needs ≥ `quorum` reports; value = **lower median**
   `sorted[(k−1)/2]`; also stores k and spread (max − min).
4. **Optional (recommended): signer bonds + `proveEquivocation(r1, sig1, r2, sig2)`** — same signer, same
   (request, zone), two different values → bond slashed.

**Defaults:** N = 5 signers, quorum 3, `maxAge` 6 h, test bond 1 ETH (parameters, not production values).

**Python:** `oracle/signer.py` (deterministic test keys = keccak of `"qicas-signer-i"`; signs config or
Phase 1 values via `eth_account.encode_typed_data`); `core/oracle_math.py` (`median_lower`, pure);
`chain/oracle_client.py`.

### Oracle consumer (open decision 1)

- **(a) recommended:** `CarbonScheduleMarketV2.sol` = copy of V1 whose `publish` takes a `requestId` and
  reads region carbon from the finalised snapshot. The 4 parity tests are **parametrised over V1 and V2**.
  `PriceMarket.openMarket` also reads the oracle, so UB, LB and baseline use the same certified data.
  Cost: ~350 duplicated Solidity lines, consolidated in Phase 5.
- **(b):** oracle feeds only `PriceMarket` — less code, but LB from oracle data vs UB from owner data, so the
  gap compares different inputs. Not recommended.

## B. Optimistic fraud proofs for lower-bound claims (added to `PriceMarket.sol`)

**Weakness fixed:** in Phase 3 a lone dishonest submitter can inflate a workflow's recorded minimum and
hence g(λ_k) (Phase 3 test 9).

1. **`claimBound(marketId, k)` + bond B** — anyone; starts challenge window W (default 1 h).
2. **`challenge(marketId, k, w, x′)`** in the window; contract computes V_w(x′, λ_k) with the
   parity-tested `workflowValue`.
   - **Lower than recorded min:** claim was false → min updated, g_k recomputed lower, claim cancelled,
     claimant bond 50 % to challenger / 50 % to slashed pool (self-challenge loses money); anyone may
     re-claim the corrected g_k.
   - **Otherwise:** revert, nothing changes.
3. **`finalizeBound(marketId, k)`** after the window with no successful challenge → certified LB =
   max(certified LB, g_k); bond withdrawable (pull payment, reentrancy-guarded).
4. `certifiedGapBps` uses **only finalised bounds**; pending claims shown as "claimed".

**Why one step suffices (no bisection):** a fraud proof is one cheaper assignment for one workflow, checked
in one call — so challengers need no bond (invalid challenges revert, costing the griefer gas). With ≤ 7
tasks per workflow any watcher can compute the exact min off-chain (4⁷ = 16,384 cases), so **any false
claim is detectable by one honest, live watcher** during the window.

**Price path vs validity:** correcting round k's min doesn't rewrite later prices; g(λ) is a valid bound
for any λ ≥ 0, so a sub-optimal price path only weakens the bound, never invalidates it.

## C. Attack tests: `tests/test_trust_layer.py`

| # | Attack | Expected |
|---|---|---|
| **Wrong signatures** | | |
| 1 | Unregistered key | revert `UnknownSigner` |
| 2 | Valid sig, relayer changes `ciGPerKwh` | different recovered address → `UnknownSigner` |
| 3 | Signed for another chainId / contract | `UnknownSigner` |
| 4 | Malformed sig (length, v ∉ {27, 28}) | `BadSignature` |
| 5 | High-s malleated copy | `BadSignature` |
| 6 | Same signature replayed | `DuplicateReport` |
| 7 | Signer equivocates | second rejected; `proveEquivocation` slashes bond |
| **Stale data** | | |
| 8 | Different hour | `WrongHour` |
| 9 | Earlier request replayed | `WrongRequest` |
| 10 | `issuedAt` older than `maxAge` | `Stale` |
| 11 | `issuedAt` in the future | `FutureReport` |
| 12 | After deadline | `Late` |
| 13 | Zone below quorum; consumer reads unfinalised snapshot | `NoQuorum` / `NotFinalized` |
| **Median robustness** | | |
| 14 | 2 of 5 report extreme values | median = honest median |
| 15 | 3 of 5 lie | median moves — **documents the honest-majority assumption** |
| **False bounds** | | |
| 16 | Lone dishonest submitter inflates g_k, then claims | challenger posts exact min → claim cancelled, bond paid, corrected g_k ≤ brute-force optimum (fixes Phase 3 weakness) |
| 17 | Challenge not cheaper | revert; claim unaffected |
| 18 | Challenge after window / finalise before end | `WindowClosed` / `WindowOpen` |
| 19 | Honest claim vs every attacker challenge | survives, finalised, bond refunded |
| 20 | Claim on unclosed round / double claim | revert |
| 21 | Reentrancy on bond withdrawal | blocked |
| 22 | Weak duality | certified LB ≤ every revealed feasible score and ≤ brute-force optimum (tiny instance) |

**Parity tests (one per new function):** `reportDigest` vs `eth_account.encode_typed_data` (incl. typehash
string); `recoverSigner` vs `Account.recover_message`; `medianLower` vs Python on 200 fuzzed arrays (odd/
even, duplicates); bound bookkeeping vs a Python simulation of the same event sequence; if (a), existing
parity tests also against V2.

**Gas** (`results/trust/gas.csv`): `submitReports` per report; `finalizeSnapshot` vs N; `claimBound`;
`challenge` by workflow size; `finalizeBound`. Extra overhead added to the PROJECT_PLAN table.

`experiments/trust_layer.py` runs honest flow + every attack → `results/trust/attacks.csv` (attack,
outcome, gas, slashed). Phase 6's attack table comes from this file.

## D. Honest claims

- **"Trust-minimised", not "trustless":** honest majority of signers; at least one honest, live watcher per
  challenge window (with ≤ 7-task workflows that watcher can always find the min).
- **Same-source risk:** removes single-*reporter* trust, not data-*source* trust.
- **Finality delay:** certified one window after the claim.
- **Parameters illustrative:** bonds, window, quorum not tuned for real economic security.

## E. After approval

1. Phase 3 implemented and Node working. 2. Implement `CarbonOracle.sol`, `PriceMarket.sol` additions, V2
(if (a)), clients, signer, tests, experiment. 3. Recompile (§9.3-B); V1 artifact guard green.
4. pytest, `demo.run_demo` (must match RUN_GUIDE.md), `experiments/trust_layer.py`.
5. Update README §7 and §11, PROJECT_PLAN.md status, AGENTS.md (EIP-712 digest added to rule 1's parity
list). 6. Commit, without pushing.
