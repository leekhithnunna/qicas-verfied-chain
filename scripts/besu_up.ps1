# Phase 5: start the 4-validator Besu QBFT TEST network and wait until it produces blocks.
#   powershell -ExecutionPolicy Bypass -File scripts\besu_up.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose -f chain/besu/docker-compose.yml up -d
.\.venv\Scripts\python.exe -m chain.besu.status --wait 180
if ($LASTEXITCODE -ne 0) { Write-Error "Besu did not produce blocks within 180 s (docker compose -f chain/besu/docker-compose.yml logs validator1)" }
