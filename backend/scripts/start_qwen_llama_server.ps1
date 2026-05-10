[CmdletBinding()]
param(
    [ValidateSet('auto', 'cpu_8k', 'light_4k', 'gpu_test_16k')]
    [string]$Profile = 'auto',
    [string]$ModelPath = '',
    [string]$ServerPath = '',
    [string]$HostAddress = '127.0.0.1',
    [int]$Port = 8025,
    [int]$Threads = 0,
    [switch]$NoMlock,
    [switch]$NoWatch,
    [switch]$ForceRestart,
    [int]$PressureSeconds = 60
)

$ErrorActionPreference = 'Stop'

$BackendDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$RootDir = (Resolve-Path (Join-Path $BackendDir '..')).Path
if (-not $ModelPath) { $ModelPath = Join-Path $BackendDir 'data\models\qwen2.5-1.5b-instruct-q4_k_m.gguf' }
if (-not $ServerPath) { $ServerPath = Join-Path $BackendDir 'bin\llama_cpp\llama-server.exe' }

$DataDir = Join-Path $BackendDir 'data'
$LogDir = Join-Path $DataDir 'logs'
$StatePath = Join-Path $DataDir 'qwen_llama_runtime.json'
$StdoutLog = Join-Path $LogDir 'qwen_llama_server.out.log'
$StderrLog = Join-Path $LogDir 'qwen_llama_server.err.log'
$Endpoint = "http://$HostAddress`:$Port"

$Profiles = @{
    cpu_8k = [ordered]@{
        name = 'cpu_8k'
        label = 'CPU 8K / KV Q8'
        ctx = 8192
        cache_k = 'q8_0'
        cache_v = 'q8_0'
        gpu_layers = 0
        ngl = '0'
        max_tokens = 512
        temperature = 0.3
        mlock_min_available_gb = 3.5
    }
    light_4k = [ordered]@{
        name = 'light_4k'
        label = 'Leve 4K / KV Q4'
        ctx = 4096
        cache_k = 'q4_0'
        cache_v = 'q4_0'
        gpu_layers = 0
        ngl = '0'
        max_tokens = 384
        temperature = 0.3
        mlock_min_available_gb = 2.5
    }
    gpu_test_16k = [ordered]@{
        name = 'gpu_test_16k'
        label = 'GPU teste 16K / KV Q8'
        ctx = 16384
        cache_k = 'q8_0'
        cache_v = 'q8_0'
        gpu_layers = 'all'
        ngl = '999'
        max_tokens = 768
        temperature = 0.3
        mlock_min_available_gb = 8.0
    }
}

function Ensure-Dirs {
    New-Item -ItemType Directory -Force -Path $DataDir, $LogDir | Out-Null
}

function Test-GpuBackend {
    $serverDir = Split-Path -Parent $ServerPath
    foreach ($name in @('ggml-cuda.dll', 'ggml-hip.dll', 'ggml-vulkan.dll', 'ggml-kompute.dll')) {
        if (Test-Path (Join-Path $serverDir $name)) { return $true }
    }
    return $false
}

function Get-HardwareSnapshot {
    $totalGb = 0.0
    $availableGb = 0.0
    $memoryLoad = 0.0
    $logical = [Math]::Max(1, [Environment]::ProcessorCount)
    $cpuLoad = 0.0
    $gpus = @()

    try {
        $osInfo = Get-CimInstance Win32_OperatingSystem
        $csInfo = Get-CimInstance Win32_ComputerSystem
        $totalGb = [Math]::Round([double]$csInfo.TotalPhysicalMemory / 1GB, 2)
        $availableGb = [Math]::Round(([double]$osInfo.FreePhysicalMemory * 1KB) / 1GB, 2)
        if ($totalGb -gt 0) {
            $memoryLoad = [Math]::Round((1.0 - ($availableGb / $totalGb)) * 100.0, 1)
        }
    } catch {}

    try {
        $cpuRows = @(Get-CimInstance Win32_Processor)
        $logicalSum = ($cpuRows | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        if ($logicalSum) { $logical = [int]$logicalSum }
        $cpuAvg = ($cpuRows | Measure-Object -Property LoadPercentage -Average).Average
        if ($null -ne $cpuAvg) { $cpuLoad = [Math]::Round([double]$cpuAvg, 1) }
    } catch {}

    try {
        $gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {
            $ramGb = 0.0
            try { $ramGb = [Math]::Round([double]$_.AdapterRAM / 1GB, 2) } catch {}
            [ordered]@{ name = [string]$_.Name; adapter_ram_gb = $ramGb }
        })
    } catch {}

    [ordered]@{
        total_ram_gb = $totalGb
        available_ram_gb = $availableGb
        memory_load_pct = $memoryLoad
        logical_cpus = $logical
        cpu_load_pct = $cpuLoad
        gpus = $gpus
        gpu_backend_available = (Test-GpuBackend)
        checked_at = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    }
}

function Resolve-QwenProfile([string]$Requested) {
    if ($Requested -ne 'auto' -and $Profiles.ContainsKey($Requested)) {
        return $Profiles[$Requested]
    }

    $hw = Get-HardwareSnapshot
    $bestVram = 0.0
    foreach ($gpu in @($hw.gpus)) {
        if ([double]$gpu.adapter_ram_gb -gt $bestVram) { $bestVram = [double]$gpu.adapter_ram_gb }
    }

    if ($hw.gpu_backend_available -and $bestVram -ge 6.0 -and $env:ULTRON_QWEN_DISABLE_AUTO_GPU -ne '1') {
        return $Profiles.gpu_test_16k
    }
    if (($hw.available_ram_gb -gt 0 -and $hw.available_ram_gb -lt 1.75) -or ($hw.total_ram_gb -gt 0 -and $hw.total_ram_gb -lt 6.0)) {
        return $Profiles.light_4k
    }
    return $Profiles.cpu_8k
}

function Get-EffectiveThreads($Hardware) {
    if ($Threads -gt 0) { return $Threads }
    if ($env:ULTRON_QWEN_THREADS) {
        try { return [Math]::Max(1, [int]$env:ULTRON_QWEN_THREADS) } catch {}
    }
    $logical = [Math]::Max(1, [int]$Hardware.logical_cpus)
    return [Math]::Max(1, [Math]::Min(4, [Math]::Floor($logical / 2)))
}

function Should-UseMlock($ProfileObject, $Hardware) {
    if ($NoMlock -or $env:ULTRON_QWEN_DISABLE_MLOCK -eq '1') { return $false }
    if ($Hardware.available_ram_gb -le 0) { return $true }
    return ([double]$Hardware.available_ram_gb -ge [double]$ProfileObject.mlock_min_available_gb)
}

function Quote-Arg([string]$Value) {
    if ($Value -match '\s') { return '"' + ($Value -replace '"', '\"') + '"' }
    return $Value
}

function Build-Args($ProfileObject, [bool]$UseMlock, $Hardware) {
    $threadCount = Get-EffectiveThreads $Hardware
    $args = @(
        '-m', $ModelPath,
        '--host', $HostAddress,
        '--port', [string]$Port,
        '--ctx-size', [string]$ProfileObject.ctx,
        '-ngl', [string]$ProfileObject.ngl,
        '--no-mmap',
        '-ctk', [string]$ProfileObject.cache_k,
        '-ctv', [string]$ProfileObject.cache_v,
        '-n', [string]$ProfileObject.max_tokens,
        '--temp', [string]$ProfileObject.temperature,
        '--threads', [string]$threadCount
    )
    if ($UseMlock) { $args += '--mlock' }
    return $args
}

function Write-State($ProfileObject, $Hardware, $Process, [bool]$UseMlock, [array]$Args, [string]$Reason) {
    $state = [ordered]@{
        ok = $true
        engine = 'llama-server'
        profile = [string]$ProfileObject.name
        label = [string]$ProfileObject.label
        endpoint = $Endpoint
        pid = if ($Process) { [int]$Process.Id } else { 0 }
        model_path = $ModelPath
        server_path = $ServerPath
        ctx = [int]$ProfileObject.ctx
        cache_k = [string]$ProfileObject.cache_k
        cache_v = [string]$ProfileObject.cache_v
        gpu_layers = $ProfileObject.gpu_layers
        ngl = [string]$ProfileObject.ngl
        no_mmap = $true
        mlock = $UseMlock
        max_tokens = [int]$ProfileObject.max_tokens
        temperature = [double]$ProfileObject.temperature
        command = @($ServerPath) + $Args
        hardware = $Hardware
        reason = $Reason
        updated_at = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    }
    $state | ConvertTo-Json -Depth 8 | Set-Content -Path $StatePath -Encoding UTF8
}

function Stop-OwnedLlamaServerOnPort {
    if (-not $ForceRestart) { return }
    try {
        $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        foreach ($conn in $conns) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -like 'llama-server*') {
                Stop-Process -Id $proc.Id -Force
            }
        }
    } catch {}
}

function Start-QwenServer($ProfileObject, [string]$Reason) {
    Ensure-Dirs
    if (-not (Test-Path $ServerPath)) { throw "llama-server not found: $ServerPath" }
    if (-not (Test-Path $ModelPath)) { throw "model not found: $ModelPath" }

    $hw = Get-HardwareSnapshot
    $useMlock = Should-UseMlock $ProfileObject $hw
    $args = Build-Args $ProfileObject $useMlock $hw
    $argString = ($args | ForEach-Object { Quote-Arg ([string]$_) }) -join ' '

    Stop-OwnedLlamaServerOnPort
    Write-Host "Starting Qwen llama-server: profile=$($ProfileObject.name) endpoint=$Endpoint mlock=$useMlock"
    Write-Host "Logs: $StdoutLog / $StderrLog"
    $proc = Start-Process -FilePath $ServerPath -ArgumentList $argString -WorkingDirectory (Split-Path -Parent $ServerPath) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
    Write-State $ProfileObject $hw $proc $useMlock $args $Reason

    Start-Sleep -Seconds 4
    $proc.Refresh()
    if ($proc.HasExited -and $useMlock) {
        Write-Warning "llama-server exited after --mlock; retrying without --mlock"
        $useMlock = $false
        $args = Build-Args $ProfileObject $useMlock $hw
        $argString = ($args | ForEach-Object { Quote-Arg ([string]$_) }) -join ' '
        $proc = Start-Process -FilePath $ServerPath -ArgumentList $argString -WorkingDirectory (Split-Path -Parent $ServerPath) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
        Write-State $ProfileObject $hw $proc $useMlock $args 'retry_without_mlock'
    }
    return $proc
}

function Wait-QwenHealth($Process, [int]$TimeoutSec = 150) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $Process.Refresh()
            if ($Process.HasExited) { return $false }
        } catch { return $false }
        try {
            $r = Invoke-RestMethod -Uri "$Endpoint/health" -TimeoutSec 3
            if ($null -ne $r) { return $true }
        } catch {}
        Start-Sleep -Seconds 2
    }
    return $false
}

function Restart-QwenServer($OldProcess, $ProfileObject, [string]$Reason) {
    try {
        if ($OldProcess -and -not $OldProcess.HasExited) {
            Stop-Process -Id $OldProcess.Id -Force
            Start-Sleep -Seconds 2
        }
    } catch {}
    $newProc = Start-QwenServer $ProfileObject $Reason
    [void](Wait-QwenHealth $newProc 150)
    return $newProc
}

function Test-HighPressure($Hardware) {
    if ($Hardware.available_ram_gb -gt 0 -and $Hardware.available_ram_gb -lt 1.25) { return $true }
    if ($Hardware.cpu_load_pct -ge 92.0) { return $true }
    return $false
}

$currentProfile = Resolve-QwenProfile $Profile
$process = Start-QwenServer $currentProfile "startup_$Profile"
$healthy = Wait-QwenHealth $process 150
if ($healthy) {
    Write-Host "Qwen llama-server is healthy at $Endpoint"
} else {
    Write-Warning "Qwen llama-server did not become healthy within the startup window. Check $StderrLog"
}

if ($NoWatch) {
    return
}

Write-Host "Watching hardware pressure. Use Ctrl+C to stop this watcher; the server process is pid=$($process.Id)."
$pressureSince = $null
while ($true) {
    Start-Sleep -Seconds 15
    try { $process.Refresh() } catch {}
    if ($process.HasExited) {
        Write-Warning "llama-server exited. Restarting same profile $($currentProfile.name)."
        $process = Start-QwenServer $currentProfile 'process_exit_restart'
        [void](Wait-QwenHealth $process 150)
        $pressureSince = $null
        continue
    }

    $hw = Get-HardwareSnapshot
    if (Test-HighPressure $hw) {
        if ($null -eq $pressureSince) { $pressureSince = Get-Date }
        $elapsed = ((Get-Date) - $pressureSince).TotalSeconds
        if ($elapsed -ge $PressureSeconds -and $currentProfile.name -ne 'light_4k') {
            Write-Warning "Sustained pressure detected. Downgrading Qwen profile to light_4k."
            $currentProfile = $Profiles.light_4k
            $process = Restart-QwenServer $process $currentProfile 'sustained_hardware_pressure'
            $pressureSince = $null
        }
    } else {
        $pressureSince = $null
    }
}
