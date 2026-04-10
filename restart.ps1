<#
.SYNOPSIS
    Recreate Azure resources deleted by stop.ps1 and start the local app.
.NOTES
    Takes ~3 minutes for the model deployment to become ready.
#>

$ErrorActionPreference = "Continue"
$RG = "vigil-demo-rg"
$AI_NAME = "vigil-ai-services"
$SEARCH_NAME = "vigil-search-std"
$LOCATION = "eastus2"

Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Vigil — Document Analyst — RESTART"     -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan

# ── Recreate model deployments ──
Write-Host "`n[1/4] Creating GPT-4.1 deployment..." -ForegroundColor Yellow
az cognitiveservices account deployment create `
    --name $AI_NAME `
    --resource-group $RG `
    --deployment-name gpt-4.1 `
    --model-name gpt-4.1 `
    --model-version "2025-04-14" `
    --model-format OpenAI `
    --sku-capacity 10 `
    --sku-name GlobalStandard 2>$null
Write-Host "  GPT-4.1 deployment created." -ForegroundColor Green

Write-Host "`n[2/4] Creating GPT-4.1-mini deployment..." -ForegroundColor Yellow
az cognitiveservices account deployment create `
    --name $AI_NAME `
    --resource-group $RG `
    --deployment-name gpt-4.1-mini `
    --model-name gpt-4.1-mini `
    --model-version "2025-04-14" `
    --model-format OpenAI `
    --sku-capacity 200 `
    --sku-name GlobalStandard 2>$null
Write-Host "  GPT-4.1-mini deployment created." -ForegroundColor Green

# ── Recreate search service ──
Write-Host "`n[3/4] Creating Azure AI Search service..." -ForegroundColor Yellow
az search service create `
    --name $SEARCH_NAME `
    --resource-group $RG `
    --location $LOCATION `
    --sku basic `
    --semantic-search free 2>$null
Write-Host "  Search service created." -ForegroundColor Green

# ── Start local app ──
Write-Host "`n[4/4] Starting Vigil..." -ForegroundColor Yellow
Write-Host "  Run: python app.py" -ForegroundColor Cyan

Write-Host ""
Write-Host "═══════════════════════════════════════" -ForegroundColor Green
Write-Host "  All resources restored." -ForegroundColor Green
Write-Host "  http://localhost:3000" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════" -ForegroundColor Green
