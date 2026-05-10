# ============================================================
# UltronPRO -- Empacotamento de Distribuicao
# ============================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir     = Split-Path -Parent $ScriptDir
$BackendDir  = Join-Path $RootDir "backend"
$DistDir     = Join-Path $ScriptDir "dist"
$ExePath     = Join-Path $DistDir "UltronPRO.exe"
$PackageDir  = Join-Path $DistDir "UltronPRO_Package"
$ZipPath     = Join-Path $DistDir "UltronPRO_Distribuivel.zip"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  UltronPRO -- Empacotamento para Distribuicao" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

if (-not (Test-Path $ExePath)) {
    Write-Host "ERRO: UltronPRO.exe nao encontrado em: $ExePath" -ForegroundColor Red
    exit 1
}

if (Test-Path $PackageDir) { Remove-Item -Recurse -Force $PackageDir }
New-Item -ItemType Directory -Path $PackageDir | Out-Null

Write-Host "Copiando executavel..." -ForegroundColor Yellow
Copy-Item $ExePath "$PackageDir\UltronPRO.exe"

Write-Host "Copiando dados do backend..." -ForegroundColor Yellow
$DataSrc = Join-Path $BackendDir "data"
$DataDst = Join-Path $PackageDir "backend\data"
if (Test-Path $DataSrc) {
    robocopy $DataSrc $DataDst /E /XF "*.log" "*.wal" "*.shm" "*.binlog" /XD "logs" ".cache" /NJH /NJS /NFL | Out-Null
}

$BinSrc = Join-Path $BackendDir "bin"
$BinDst = Join-Path $PackageDir "backend\bin"
if (Test-Path $BinSrc) {
    Write-Host "Copiando binarios..." -ForegroundColor Yellow
    robocopy $BinSrc $BinDst /E /NJH /NJS /NFL | Out-Null
}

$TasksSrc = Join-Path $RootDir "tasks"
$TasksDst = Join-Path $PackageDir "tasks"
if (Test-Path $TasksSrc) {
    Write-Host "Copiando tasks..." -ForegroundColor Yellow
    robocopy $TasksSrc $TasksDst /E /XD "__pycache__" ".pytest_cache" /NJH /NJS /NFL | Out-Null
}

$ReadmeSrc = Join-Path $ScriptDir "LEIAME.txt"
if (Test-Path $ReadmeSrc) {
    Write-Host "Copiando LEIAME.txt..." -ForegroundColor Yellow
    Copy-Item $ReadmeSrc "$PackageDir\LEIAME.txt"
}

Write-Host "Compactando para .zip..." -ForegroundColor Yellow
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path "$PackageDir\*" -DestinationPath $ZipPath -CompressionLevel Optimal

$SizeMB = [Math]::Round((Get-Item $ZipPath).Length / 1MB, 1)

Write-Host "==================================================" -ForegroundColor Green
Write-Host "  PACOTE GERADO COM SUCESSO!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  Arquivo: $ZipPath" -ForegroundColor Cyan
Write-Host "  Tamanho: $SizeMB MB" -ForegroundColor Cyan
Write-Host "  Envie esse .zip para o usuario final." -ForegroundColor White
Write-Host "  Instrua-o a extrair e executar UltronPRO.exe." -ForegroundColor White

