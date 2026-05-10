# ============================================================
# UltronPRO — Script de Build do Executável (.exe)
# ============================================================
# Pré-requisito: Python instalado e no PATH.
# Execute este script UMA VEZ na máquina de desenvolvimento.
# O .exe gerado em build\dist\UltronPRO.exe pode ser copiado
# para qualquer máquina Windows — ele instalará as deps sozinho.
# ============================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Caminhos ──────────────────────────────────────────────
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir     = Split-Path -Parent $ScriptDir
$BackendDir  = Join-Path $RootDir "backend"
$LauncherDir = Join-Path $ScriptDir "launcher"
$LauncherPy  = Join-Path $LauncherDir "ultronpro_launcher.py"
$DistDir     = Join-Path $ScriptDir "dist"
$BuildDir    = Join-Path $ScriptDir "_pyibuild"
$IconFile    = Join-Path $ScriptDir "icon.ico"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  UltronPRO — Build do Executável" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Verificar Python ───────────────────────────────────
Write-Host "[1/5] Verificando Python..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "      $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "ERRO: Python não encontrado no PATH." -ForegroundColor Red
    Write-Host "      Baixe em https://python.org/downloads" -ForegroundColor Red
    exit 1
}

# ── 2. Instalar PyInstaller ───────────────────────────────
Write-Host "[2/5] Instalando PyInstaller..." -ForegroundColor Yellow
python -m pip install --quiet pyinstaller pyinstaller-hooks-contrib
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: Falha ao instalar PyInstaller." -ForegroundColor Red
    exit 1
}
Write-Host "      PyInstaller OK." -ForegroundColor Green

# ── 3. Instalar PyQt5 (necessário para o .exe incluir os binários) ─
Write-Host "[3/5] Instalando PyQt5 para bundling..." -ForegroundColor Yellow
python -m pip install --quiet PyQt5
if ($LASTEXITCODE -ne 0) {
    Write-Host "AVISO: PyQt5 não instalado. O .exe pode não ter a UI." -ForegroundColor Yellow
}
Write-Host "      PyQt5 OK." -ForegroundColor Green

# ── 4. Gerar ícone padrão se não existir ─────────────────
if (-not (Test-Path $IconFile)) {
    Write-Host "[4/5] Gerando ícone padrão..." -ForegroundColor Yellow
    python -c @"
try:
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (256, 256), (3, 10, 18, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([28, 28, 228, 228], outline=(0, 200, 255, 255), width=8)
    draw.ellipse([80, 80, 176, 176], fill=(0, 170, 200, 255))
    img.save(r'$IconFile')
    print('Icone gerado.')
except Exception as e:
    print(f'Icone nao gerado (Pillow ausente): {e}')
"@
    Write-Host "      Ícone gerado (ou ignorado se Pillow ausente)." -ForegroundColor Green
} else {
    Write-Host "[4/5] Ícone encontrado: $IconFile" -ForegroundColor Green
}

# ── 5. Rodar PyInstaller ──────────────────────────────────
Write-Host "[5/5] Compilando com PyInstaller..." -ForegroundColor Yellow
Write-Host "      (pode levar 2-5 minutos)" -ForegroundColor Gray

# Monta argumentos
$PyiArgs = @(
    $LauncherPy,
    "--name", "UltronPRO",
    "--onefile",
    "--noconsole",
    "--distpath", $DistDir,
    "--workpath", $BuildDir,
    "--specpath", $BuildDir,
    # Inclui a pasta ultronpro como pacote Python
    "--add-data", "$BackendDir\ultronpro;ultronpro",
    # Inclui a pasta ui (HTML da interface web interna, se usada)
    "--add-data", "$BackendDir\ui;ui",
    # Inclui scripts de tasks
    "--add-data", "$RootDir\tasks;tasks",
    # Hidden imports que o PyInstaller costuma perder
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols",
    "--hidden-import", "uvicorn.protocols.http",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.websockets",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan",
    "--hidden-import", "uvicorn.lifespan.on",
    "--hidden-import", "fastapi",
    "--hidden-import", "PyQt5",
    "--hidden-import", "PyQt5.QtCore",
    "--hidden-import", "PyQt5.QtGui",
    "--hidden-import", "PyQt5.QtWidgets",
    "--hidden-import", "sqlalchemy.dialects.sqlite",
    "--hidden-import", "pydantic",
    "--hidden-import", "loguru",
    "--hidden-import", "tiktoken",
    "--hidden-import", "httpx",
    "--hidden-import", "anyio",
    "--hidden-import", "anyio._backends._asyncio",
    "--hidden-import", "tkinter",
    "--hidden-import", "tkinter.messagebox",
    "--collect-all", "PyQt5",
    "--collect-all", "uvicorn",
    "--collect-all", "fastapi",
    "--collect-all", "tiktoken",
    "--noconfirm",
    "--clean"
)

# Adiciona ícone se existir
if (Test-Path $IconFile) {
    $PyiArgs += "--icon"
    $PyiArgs += $IconFile
}

& python -m PyInstaller @PyiArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERRO: PyInstaller falhou. Veja os logs acima." -ForegroundColor Red
    exit 1
}

# ── Resultado ─────────────────────────────────────────────
$ExePath = Join-Path $DistDir "UltronPRO.exe"
Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  BUILD CONCLUÍDO COM SUCESSO!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Executável: $ExePath" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Como distribuir:" -ForegroundColor White
Write-Host "  1. Copie UltronPRO.exe para a máquina destino" -ForegroundColor Gray
Write-Host "  2. Copie também a pasta 'data\' do backend" -ForegroundColor Gray
Write-Host "     (contém modelos de voz e banco de dados)" -ForegroundColor Gray
Write-Host "  3. Estrutura esperada na máquina destino:" -ForegroundColor Gray
Write-Host "       C:\UltronPRO\" -ForegroundColor Gray
Write-Host "         UltronPRO.exe" -ForegroundColor Gray
Write-Host "         backend\data\  <-- copie esta pasta" -ForegroundColor Gray
Write-Host ""
Write-Host "  Na primeira execução, o .exe instala as deps automaticamente." -ForegroundColor Yellow
Write-Host ""
