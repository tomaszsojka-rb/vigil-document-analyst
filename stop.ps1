<#
.SYNOPSIS
    Stop all Azure resources and the local app to save costs.
    The AI Services account is kept (free when idle) — only the
    model deployment and search service are deleted.
.NOTES
    Run restart.ps1 to get back up in ~3 minutes.
#>

$ErrorActionPreference = "Continue"
$RG = "vigil-demo-rg"
$AI_NAME = "vigil-ai-services"
$SEARCH_NAME = "vigil-search-std"

Write-Host "═══════════════════════════════════════" -ForegroundColor Yellow
Write-Host "  Vigil — Document Analyst — STOP"       -ForegroundColor Yellow
Write-Host "═══════════════════════════════════════" -ForegroundColor Yellow

# ── Stop local app ──
Write-Host "`n[1/4] Stopping local app..." -ForegroundColor Yellow
$vigilProc = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue } |
    Where-Object { $_.ProcessName -eq "python" }
if ($vigilProc) {
    $vigilProc | Stop-Process -Force
    Write-Host "  Local app stopped (PID: $($vigilProc.Id -join ', '))." -ForegroundColor Green
} else {
    Write-Host "  No Vigil app process found on port 3000." -ForegroundColor Gray
}

# ── Delete model deployments (no cost when deleted) ──
Write-Host "`n[2/4] Deleting GPT-4.1 deployment..." -ForegroundColor Yellow
az cognitiveservices account deployment delete `
    --name $AI_NAME `
    --resource-group $RG `
    --deployment-name gpt-4.1 2>$null
Write-Host "  GPT-4.1 deployment deleted." -ForegroundColor Green

Write-Host "`n[3/4] Deleting GPT-4.1-mini deployment..." -ForegroundColor Yellow
az cognitiveservices account deployment delete `
    --name $AI_NAME `
    --resource-group $RG `
    --deployment-name gpt-4.1-mini 2>$null
Write-Host "  GPT-4.1-mini deployment deleted." -ForegroundColor Green

# ── Delete search service (Basic = ~$75/month even idle) ──
Write-Host "`n[4/4] Deleting Azure AI Search service..." -ForegroundColor Yellow
az search service delete `
    --name $SEARCH_NAME `
    --resource-group $RG `
    --yes 2>$null
Write-Host "  Search service deleted." -ForegroundColor Green

Write-Host ""
Write-Host "═══════════════════════════════════════" -ForegroundColor Green
Write-Host "  All resources stopped." -ForegroundColor Green
Write-Host "  Remaining (free when idle):" -ForegroundColor Green
Write-Host "    - Resource group: $RG" -ForegroundColor Gray
Write-Host "    - AI Services account: $AI_NAME (no deployment)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Run .\restart.ps1 to get back up in ~3 min." -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════" -ForegroundColor Green
