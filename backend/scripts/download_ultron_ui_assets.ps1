param(
    [string]$BackendDir = "",
    [switch]$FullVosk,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not $BackendDir) {
    $BackendDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$VoskRoot = Join-Path $BackendDir "data\models\vosk"
if ($FullVosk) {
    $VoskModelName = "vosk-model-pt-fb-v0.1.1-20220516_2113"
    $VoskModelUrl = "https://alphacephei.com/vosk/models/vosk-model-pt-fb-v0.1.1-20220516_2113.zip"
} else {
    $VoskModelName = "vosk-model-small-pt-0.3"
    $VoskModelUrl = "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
}
$VoskModel = Join-Path $VoskRoot $VoskModelName
$PiperDir = Join-Path $BackendDir "bin\piper"
$VoiceDir = Join-Path $BackendDir "data\piper\voices"
$TmpDir = Join-Path $BackendDir "tmp\ultron_ui_downloads"

New-Item -ItemType Directory -Force -Path $VoskRoot, $PiperDir, $VoiceDir, $TmpDir | Out-Null

function Download-File {
    param([string]$Url, [string]$OutFile)
    if ((Test-Path $OutFile) -and (-not $Force)) {
        Write-Host "OK: $OutFile"
        return
    }
    Write-Host "Baixando: $Url"
    Invoke-WebRequest -Uri $Url -OutFile $OutFile
}

$VoskZip = Join-Path $TmpDir ($VoskModelName + ".zip")
if ((-not (Test-Path $VoskModel)) -or $Force) {
    Download-File $VoskModelUrl $VoskZip
    if (Test-Path $VoskModel) { Remove-Item -Recurse -Force $VoskModel }
    Expand-Archive -Path $VoskZip -DestinationPath $VoskRoot -Force
}

$PiperZip = Join-Path $TmpDir "piper_windows_amd64.zip"
$PiperExe = Join-Path $PiperDir "piper.exe"
if ((-not (Test-Path $PiperExe)) -or $Force) {
    $ExtractDir = Join-Path $TmpDir "piper_extract"
    if (Test-Path $ExtractDir) { Remove-Item -Recurse -Force $ExtractDir }
    New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
    Download-File "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip" $PiperZip
    Expand-Archive -Path $PiperZip -DestinationPath $ExtractDir -Force
    $FoundExe = Get-ChildItem -Path $ExtractDir -Recurse -Filter "piper.exe" | Select-Object -First 1
    if (-not $FoundExe) { throw "piper.exe não encontrado no zip" }
    Copy-Item -Path (Join-Path $FoundExe.DirectoryName "*") -Destination $PiperDir -Recurse -Force
}

$VoiceOnnx = Join-Path $VoiceDir "pt_BR-faber-medium.onnx"
$VoiceJson = Join-Path $VoiceDir "pt_BR-faber-medium.onnx.json"
Download-File "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx?download=true" $VoiceOnnx
Download-File "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json?download=true" $VoiceJson

Write-Host ""
Write-Host "Assets Ultron UI prontos:"
Write-Host "Vosk:  $VoskModel"
if ($FullVosk) {
    Write-Host "Dica: defina ULTRON_UI_PREFER_FULL_VOSK=1 para a UI usar este modelo maior."
}
Write-Host "Piper: $PiperExe"
Write-Host "Voz:   $VoiceOnnx"
