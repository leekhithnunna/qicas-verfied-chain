# Besu QBFT test network (QICAS Phase 5)

> **TEST KEYS — NEVER USE ON A REAL NETWORK.** Every key here is `keccak256` of a public label
> (`chain/besu/generate.py`); anyone can re-derive them. Zero gas price, chainId **1338**.

A local 4-validator **Hyperledger Besu QBFT** network that *models* a consortium of cloud providers (one validator
each: provider-A…D). QBFT with 4 validators tolerates 1 faulty validator. It is not a production deployment.

| Item | Value |
|---|---|
| Image | `hyperledger/besu:26.10.2` (released 2026-10-26), digest `sha256:bc599f5ef95a3d5d03f966cd2c1f7dfd7353834c84bc5651ffb4af884860a2c7` |
| Consensus | QBFT, block period 2 s, request timeout 4 s, epoch 30,000 |
| Genesis | berlin/london/shanghai at 0, `zeroBaseFee`, gas limit 30 M, 10 funded TEST accounts (1 M ETH each) |
| Validators | `validator1..4` = provider-A..D, IPs 172.16.239.11–14, bootnode = validator1 |
| JSON-RPC | `127.0.0.1:8545` (validator1) … `127.0.0.1:8548` (validator4), loopback only; APIs ETH, NET, WEB3, QBFT, TXPOOL |
| Memory | `-Xmx768m` per node (≈ 3–4 GB for the network) |

## Files

- `generate.py` — writes `genesis.json`, `static.json` (enodes, addresses, accounts) and `nodes/validator<i>/key`
  deterministically; `python -m chain.besu.generate --check` verifies them (also run by the default pytest).
- `docker-compose.yml` — the 4 nodes. `status.py` — status / wait (stdlib JSON-RPC). `vote.py` — optional
  validator add/remove vote demo.

## Use

```powershell
powershell -ExecutionPolicy Bypass -File scripts\besu_up.ps1      # up + wait for blocks from 4 validators
.\.venv\Scripts\python.exe -m demo.run_demo --mode besu           # V1 case-study demo on Besu (or --config config/besu.yaml)
$env:QICAS_BESU='1'; .\.venv\Scripts\python.exe -m pytest -q -m besu        # opt-in tests (QICAS_BESU_VOTE=1 adds the vote test)
.\.venv\Scripts\python.exe -m experiments.besu_vs_memory          # E6 measurements -> results/besu/
powershell -ExecutionPolicy Bypass -File scripts\besu_down.ps1 [-Reset]     # stop (and wipe data)
```

Python: `Chain.start("besu")` signs locally with the TEST account keys (web3 `SignAndSendRawMiddlewareBuilder`) and
adds `ExtraDataToPOAMiddleware`; the existing `transact({"from": ...})` calls work unchanged.

## Troubleshooting

- `docker info` must print a server version (start Docker Desktop).
- No blocks: `docker compose -f chain/besu/docker-compose.yml logs validator1`; after changing the genesis, wipe the
  data with `scripts\besu_down.ps1 -Reset`.
- Port 8545 busy (e.g. a Hardhat node): stop it, or change the published ports in `docker-compose.yml`.
- Time-based tests (challenge windows, oracle freshness) stay in-memory: Besu runs in real time and the
  `PriceMarket` challenge window is 1 hour (plan decision A10).
