# Phase 5: stop the Besu QBFT TEST network. Add -Reset to also wipe the chain data volumes.
#   powershell -ExecutionPolicy Bypass -File scripts\besu_down.ps1 [-Reset]
param([switch]$Reset)
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($Reset) { docker compose -f chain/besu/docker-compose.yml down -v } else { docker compose -f chain/besu/docker-compose.yml down }
