from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
DEFAULT_MODEL_PATH = BACKEND_DIR / "data" / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEFAULT_SERVER_PATH = BACKEND_DIR / "bin" / "llama_cpp" / ("llama-server.exe" if os.name == "nt" else "llama-server")
DEFAULT_STATE_PATH = BACKEND_DIR / "data" / "qwen_llama_runtime.json"
MODEL_ALIAS = "qwen2.5-1.5b-instruct-q4_k_m"
_HW_CACHE: dict[str, Any] = {"ts": 0.0, "value": None}
_RUNTIME_LOCK = threading.Lock()
_MONITOR_STOP = threading.Event()
_MONITOR_THREAD: threading.Thread | None = None
_STARTED_PROCESS: subprocess.Popen | None = None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return int(default)


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class QwenProfile:
    name: str
    label: str
    ctx: int
    cache_k: str
    cache_v: str
    gpu_layers: int | str
    max_tokens: int
    temperature: float
    mlock_min_available_gb: float
    purpose: str

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["no_mmap"] = True
        data["engine"] = "llama-server"
        return data


PROFILES: dict[str, QwenProfile] = {
    "cpu_8k": QwenProfile(
        name="cpu_8k",
        label="CPU 8K / KV Q8",
        ctx=8192,
        cache_k="q8_0",
        cache_v="q8_0",
        gpu_layers=0,
        max_tokens=512,
        temperature=0.3,
        mlock_min_available_gb=3.5,
        purpose="default_cpu_stable",
    ),
    "light_4k": QwenProfile(
        name="light_4k",
        label="Leve 4K / KV Q4",
        ctx=4096,
        cache_k="q4_0",
        cache_v="q4_0",
        gpu_layers=0,
        max_tokens=384,
        temperature=0.3,
        mlock_min_available_gb=2.5,
        purpose="low_ram_pressure",
    ),
    "gpu_test_16k": QwenProfile(
        name="gpu_test_16k",
        label="GPU teste 16K / KV Q8",
        ctx=16384,
        cache_k="q8_0",
        cache_v="q8_0",
        gpu_layers="all",
        max_tokens=768,
        temperature=0.3,
        mlock_min_available_gb=8.0,
        purpose="gpu_validation_only",
    ),
}


def model_path() -> Path:
    return Path(os.getenv("ULTRON_QWEN_MODEL_PATH", str(DEFAULT_MODEL_PATH))).expanduser()


def server_path() -> Path:
    return Path(os.getenv("ULTRON_LLAMA_SERVER_PATH", str(DEFAULT_SERVER_PATH))).expanduser()


def state_path() -> Path:
    return Path(os.getenv("ULTRON_QWEN_RUNTIME_STATE", str(DEFAULT_STATE_PATH))).expanduser()


def endpoint_url() -> str:
    return str(os.getenv("ULTRON_LOCAL_INFER_URL", "http://127.0.0.1:8025") or "http://127.0.0.1:8025").rstrip("/")


def endpoint_host_port(url: str | None = None) -> tuple[str, int]:
    parsed = urlparse(str(url or endpoint_url()))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, int(port)


def log_paths() -> dict[str, str]:
    log_dir = BACKEND_DIR / "data" / "logs"
    return {
        "stdout": str(log_dir / "qwen_llama_server.out.log"),
        "stderr": str(log_dir / "qwen_llama_server.err.log"),
    }


def _memory_windows() -> dict[str, float] | None:
    if os.name != "nt":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
        return None
    gb = float(1024 ** 3)
    return {
        "total_ram_gb": round(float(stat.ullTotalPhys) / gb, 2),
        "available_ram_gb": round(float(stat.ullAvailPhys) / gb, 2),
        "memory_load_pct": float(stat.dwMemoryLoad),
    }


def _memory_posix() -> dict[str, float] | None:
    try:
        page = float(os.sysconf("SC_PAGE_SIZE"))
        pages = float(os.sysconf("SC_PHYS_PAGES"))
        avail_pages = float(os.sysconf("SC_AVPHYS_PAGES"))
    except Exception:
        return None
    gb = float(1024 ** 3)
    total = (page * pages) / gb
    avail = (page * avail_pages) / gb
    load = 100.0 - ((avail / total) * 100.0) if total > 0 else 0.0
    return {
        "total_ram_gb": round(total, 2),
        "available_ram_gb": round(avail, 2),
        "memory_load_pct": round(load, 1),
    }


def _detect_nvidia_gpus() -> list[dict[str, Any]]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        proc = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    out: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        mem_mb = 0
        if len(parts) > 1:
            try:
                mem_mb = int(float(parts[1]))
            except Exception:
                mem_mb = 0
        out.append({"name": parts[0], "vram_mb": mem_mb})
    return out


def gpu_backend_available(path: Path | None = None) -> bool:
    base = (path or server_path()).parent
    candidates = (
        "ggml-cuda.dll",
        "ggml-hip.dll",
        "ggml-vulkan.dll",
        "ggml-kompute.dll",
        "libggml-cuda.so",
        "libggml-hip.so",
        "libggml-vulkan.so",
        "libggml-metal.dylib",
    )
    return any((base / name).exists() for name in candidates)


def hardware_snapshot() -> dict[str, Any]:
    now = time.time()
    ttl = _env_float("ULTRON_QWEN_HARDWARE_CACHE_SEC", 15.0)
    cached = _HW_CACHE.get("value")
    if isinstance(cached, dict) and now - float(_HW_CACHE.get("ts") or 0.0) < ttl:
        return dict(cached)

    mem = _memory_windows() or _memory_posix() or {}
    cpus = os.cpu_count() or 1
    gpus = _detect_nvidia_gpus()
    total = float(mem.get("total_ram_gb") or 0.0)
    avail = float(mem.get("available_ram_gb") or 0.0)
    pressure = "unknown"
    if total > 0 or avail > 0:
        if avail and avail < _env_float("ULTRON_QWEN_HIGH_PRESSURE_RAM_GB", 1.25):
            pressure = "high"
        elif avail and avail < _env_float("ULTRON_QWEN_LIGHT_AVAILABLE_RAM_GB", 1.75):
            pressure = "medium"
        else:
            pressure = "normal"
    snapshot = {
        **mem,
        "logical_cpus": int(cpus),
        "gpus": gpus,
        "gpu_backend_available": gpu_backend_available(),
        "pressure": pressure,
        "checked_at": int(time.time()),
    }
    _HW_CACHE["ts"] = now
    _HW_CACHE["value"] = dict(snapshot)
    return snapshot


def choose_profile(requested: str | None = None, hardware: dict[str, Any] | None = None) -> QwenProfile:
    req = str(requested or os.getenv("ULTRON_QWEN_PROFILE", "auto") or "auto").strip().lower()
    if req in PROFILES:
        return PROFILES[req]

    hw = hardware or hardware_snapshot()
    available = float(hw.get("available_ram_gb") or 0.0)
    total = float(hw.get("total_ram_gb") or 0.0)
    gpus = list(hw.get("gpus") or [])
    best_vram = max([int(g.get("vram_mb") or 0) for g in gpus] or [0])
    gpu_ok = bool(hw.get("gpu_backend_available")) and best_vram >= _env_int("ULTRON_QWEN_GPU_MIN_VRAM_MB", 6144)

    if gpu_ok and not _env_flag("ULTRON_QWEN_DISABLE_AUTO_GPU", "0"):
        return PROFILES["gpu_test_16k"]

    if (available and available < _env_float("ULTRON_QWEN_LIGHT_AVAILABLE_RAM_GB", 1.75)) or (
        total and total < _env_float("ULTRON_QWEN_LIGHT_TOTAL_RAM_GB", 6.0)
    ):
        return PROFILES["light_4k"]

    return PROFILES["cpu_8k"]


def should_enable_mlock(profile: QwenProfile, hardware: dict[str, Any] | None = None) -> bool:
    if _env_flag("ULTRON_QWEN_DISABLE_MLOCK", "0"):
        return False
    hw = hardware or hardware_snapshot()
    available = float(hw.get("available_ram_gb") or 0.0)
    if available <= 0:
        return True
    return available >= float(profile.mlock_min_available_gb)


def _arg_value(args: list[str], flag: str) -> str | None:
    try:
        idx = args.index(flag)
        return str(args[idx + 1])
    except Exception:
        return None


def default_threads(hardware: dict[str, Any] | None = None) -> int:
    env_value = os.getenv("ULTRON_QWEN_THREADS")
    if env_value:
        try:
            return max(1, int(env_value))
        except Exception:
            pass
    hw = hardware or hardware_snapshot()
    logical = max(1, int(hw.get("logical_cpus") or os.cpu_count() or 1))
    return max(1, min(4, logical // 2 if logical > 1 else 1))


def default_parallel(profile: QwenProfile | None = None) -> int:
    env_value = os.getenv("ULTRON_QWEN_PARALLEL")
    if env_value:
        try:
            return max(1, int(env_value))
        except Exception:
            pass
    prof = profile or choose_profile()
    return 2 if prof.name == "gpu_test_16k" else 1


def default_prompt_cache_ram_mb(profile: QwenProfile | None = None) -> int:
    env_value = os.getenv("ULTRON_QWEN_CACHE_RAM_MB")
    if env_value is not None:
        try:
            return max(0, int(env_value))
        except Exception:
            pass
    prof = profile or choose_profile()
    return 512 if prof.name != "light_4k" else 256


def _pid_running(pid: int | None) -> bool:
    try:
        value = int(pid or 0)
    except Exception:
        return False
    if value <= 0:
        return False
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, value)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return int(code.value) == 259
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(value, 0)
        return True
    except PermissionError:
        return True
    except Exception:
        return False


def _terminate_pid(pid: int | None, *, timeout_sec: float = 8.0) -> bool:
    try:
        value = int(pid or 0)
    except Exception:
        return False
    if value <= 0 or not _pid_running(value):
        return False
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(value), "/T", "/F"], capture_output=True, text=True, timeout=timeout_sec)
            return True
        os.kill(value, 15)
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if not _pid_running(value):
                return True
            time.sleep(0.2)
        os.kill(value, 9)
        return True
    except Exception:
        return False


def _write_state(
    profile: QwenProfile,
    *,
    pid: int = 0,
    mlock: bool = False,
    args: list[str] | None = None,
    reason: str = "",
    status: str = "starting",
    started_by: str = "ultronpro",
    hardware: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hw = hardware or hardware_snapshot()
    command = list(args or [])
    active_parallel = _arg_value(command, "--parallel")
    active_cache_ram = _arg_value(command, "--cache-ram")
    state = {
        "ok": True,
        "engine": "llama-server",
        "status": status,
        "profile": profile.name,
        "label": profile.label,
        "endpoint": endpoint_url(),
        "pid": int(pid or 0),
        "model_path": str(model_path()),
        "server_path": str(server_path()),
        "ctx": int(profile.ctx),
        "cache_k": profile.cache_k,
        "cache_v": profile.cache_v,
        "gpu_layers": profile.gpu_layers,
        "ngl": "999" if profile.gpu_layers == "all" else str(int(profile.gpu_layers)),
        "no_mmap": True,
        "mlock": bool(mlock),
        "parallel": int(active_parallel) if active_parallel and active_parallel.lstrip("-").isdigit() else ("auto" if command else default_parallel(profile)),
        "cache_ram_mb": int(active_cache_ram) if active_cache_ram and active_cache_ram.lstrip("-").isdigit() else (8192 if command else default_prompt_cache_ram_mb(profile)),
        "max_tokens": int(profile.max_tokens),
        "temperature": float(profile.temperature),
        "command": command,
        "hardware": hw,
        "logs": log_paths(),
        "reason": str(reason or ""),
        "started_by": started_by,
        "updated_at": int(time.time()),
    }
    if extra:
        state.update(extra)
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return state


def read_state() -> dict[str, Any]:
    path = state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def active_profile_name() -> str:
    st = read_state()
    name = str(st.get("profile") or "").strip().lower()
    if name in PROFILES and str(st.get("status") or "").strip().lower() in {"starting", "running"}:
        return name
    req = str(os.getenv("ULTRON_QWEN_PROFILE", "") or "").strip().lower()
    if req in PROFILES:
        return req
    return choose_profile().name


def active_profile() -> QwenProfile:
    name = active_profile_name()
    if name in PROFILES:
        return PROFILES[name]
    return choose_profile()


def generation_defaults(max_tokens: int | None = None, temperature: float | None = None) -> dict[str, Any]:
    prof = active_profile()
    req_max = int(max_tokens) if isinstance(max_tokens, int) and max_tokens > 0 else int(prof.max_tokens)
    return {
        "max_tokens": max(32, min(4096, req_max)),
        "temperature": float(prof.temperature if temperature is None else temperature),
        "profile": prof.public(),
    }


def llama_server_args(
    profile: QwenProfile | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8025,
    threads: int | None = None,
    include_mlock: bool | None = None,
) -> list[str]:
    prof = profile or choose_profile()
    ngl = "999" if prof.gpu_layers == "all" else str(int(prof.gpu_layers))
    args = [
        str(server_path()),
        "-m",
        str(model_path()),
        "--host",
        str(host),
        "--port",
        str(int(port)),
        "--ctx-size",
        str(int(prof.ctx)),
        "-ngl",
        ngl,
        "--no-mmap",
        "-ctk",
        prof.cache_k,
        "-ctv",
        prof.cache_v,
        "-n",
        str(int(prof.max_tokens)),
        "--temp",
        str(float(prof.temperature)),
        "--parallel",
        str(default_parallel(prof)),
        "--cache-ram",
        str(default_prompt_cache_ram_mb(prof)),
    ]
    if threads is not None and int(threads) > 0:
        args.extend(["--threads", str(int(threads))])
    if include_mlock is None:
        include_mlock = should_enable_mlock(prof)
    if include_mlock:
        args.append("--mlock")
    return args


def autostart_enabled() -> bool:
    if _env_flag("ULTRON_QWEN_AUTOSTART", "1") is False:
        return False
    if _env_flag("ULTRON_DISABLE_ULTRON_INFER", "0"):
        return False
    return True


def _start_process(profile: QwenProfile, *, reason: str, include_mlock: bool | None = None) -> tuple[subprocess.Popen, list[str], bool]:
    global _STARTED_PROCESS

    hw = hardware_snapshot()
    host, port = endpoint_host_port()
    use_mlock = should_enable_mlock(profile, hw) if include_mlock is None else bool(include_mlock)
    args = llama_server_args(
        profile,
        host=host,
        port=port,
        threads=default_threads(hw),
        include_mlock=use_mlock,
    )
    paths = log_paths()
    Path(paths["stdout"]).parent.mkdir(parents=True, exist_ok=True)
    stdout = open(paths["stdout"], "ab")
    stderr = open(paths["stderr"], "ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        args,
        cwd=str(server_path().parent),
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    _STARTED_PROCESS = proc
    _write_state(
        profile,
        pid=int(proc.pid),
        mlock=use_mlock,
        args=args,
        reason=reason,
        status="starting",
        hardware=hw,
    )
    return proc, args, use_mlock


def _wait_health(seconds: float) -> dict[str, Any]:
    deadline = time.time() + max(0.0, float(seconds or 0.0))
    last = _server_health(endpoint_url())
    while time.time() < deadline:
        if last.get("ok"):
            return last
        time.sleep(0.5)
        last = _server_health(endpoint_url())
    return last


def ensure_server_started(*, reason: str = "startup", wait_health_sec: float = 0.0) -> dict[str, Any]:
    if not autostart_enabled():
        return {"ok": True, "started": False, "reason": "autostart_disabled", "runtime": runtime_status(check_server=False)}

    profile = choose_profile()
    health = _server_health(endpoint_url())
    if health.get("ok"):
        state = read_state()
        if str(state.get("profile") or "") not in PROFILES:
            _write_state(profile, pid=int(state.get("pid") or 0), reason="adopt_existing_server", status="running", started_by="external_or_existing")
        return {
            "ok": True,
            "started": False,
            "reason": "already_running",
            "profile": active_profile().public(),
            "server": health,
        }

    with _RUNTIME_LOCK:
        health = _server_health(endpoint_url())
        if health.get("ok"):
            return {
                "ok": True,
                "started": False,
                "reason": "already_running",
                "profile": active_profile().public(),
                "server": health,
            }

        state = read_state()
        pid = int(state.get("pid") or 0)
        age = time.time() - float(state.get("updated_at") or 0)
        startup_grace = _env_float("ULTRON_QWEN_STARTUP_GRACE_SEC", 180.0)
        if pid and _pid_running(pid) and age < startup_grace:
            return {
                "ok": True,
                "started": False,
                "reason": "already_starting",
                "pid": pid,
                "profile": PROFILES.get(str(state.get("profile") or ""), profile).public(),
                "server": health,
            }

        if not server_path().exists():
            return {"ok": False, "started": False, "reason": "llama_server_missing", "path": str(server_path())}
        if not model_path().exists():
            return {"ok": False, "started": False, "reason": "qwen_model_missing", "path": str(model_path())}

        proc, args, use_mlock = _start_process(profile, reason=reason)
        time.sleep(_env_float("ULTRON_QWEN_STARTUP_EXIT_CHECK_SEC", 2.0))
        if proc.poll() is not None and use_mlock:
            proc, args, use_mlock = _start_process(profile, reason="retry_without_mlock", include_mlock=False)

        health = _wait_health(wait_health_sec) if wait_health_sec > 0 else _server_health(endpoint_url())
        if health.get("ok"):
            _write_state(profile, pid=int(proc.pid), mlock=use_mlock, args=args, reason=reason, status="running")
        return {
            "ok": True,
            "started": True,
            "reason": reason,
            "pid": int(proc.pid),
            "profile": profile.public(),
            "mlock": bool(use_mlock),
            "server": health,
            "logs": log_paths(),
        }


def restart_server_with_profile(profile_name: str, *, reason: str = "profile_switch") -> dict[str, Any]:
    profile = PROFILES.get(str(profile_name or "").strip().lower())
    if not profile:
        return {"ok": False, "reason": "unknown_profile", "profile": profile_name}
    with _RUNTIME_LOCK:
        state = read_state()
        pid = int(state.get("pid") or 0)
        if pid and str(state.get("started_by") or "") == "ultronpro":
            _terminate_pid(pid)
            time.sleep(1.0)
        proc, args, use_mlock = _start_process(profile, reason=reason)
        health = _wait_health(_env_float("ULTRON_QWEN_RESTART_HEALTH_WAIT_SEC", 8.0))
        if health.get("ok"):
            _write_state(profile, pid=int(proc.pid), mlock=use_mlock, args=args, reason=reason, status="running")
        return {
            "ok": True,
            "started": True,
            "reason": reason,
            "pid": int(proc.pid),
            "profile": profile.public(),
            "server": health,
        }


def stop_server(*, only_started_by_ultron: bool = True) -> dict[str, Any]:
    state = read_state()
    pid = int(state.get("pid") or 0)
    if only_started_by_ultron and str(state.get("started_by") or "") != "ultronpro":
        return {"ok": True, "stopped": False, "reason": "not_owned_by_ultronpro"}
    stopped = _terminate_pid(pid)
    if stopped:
        active = PROFILES.get(str(state.get("profile") or ""), choose_profile())
        _write_state(active, pid=0, reason="shutdown_stop", status="stopped")
    return {"ok": True, "stopped": stopped, "pid": pid}


def _hardware_under_pressure(hw: dict[str, Any]) -> bool:
    available = float(hw.get("available_ram_gb") or 0.0)
    load = float(hw.get("memory_load_pct") or 0.0)
    if available and available < _env_float("ULTRON_QWEN_HIGH_PRESSURE_RAM_GB", 1.25):
        return True
    if load >= _env_float("ULTRON_QWEN_HIGH_PRESSURE_LOAD_PCT", 92.0):
        return True
    return False


def _monitor_loop() -> None:
    pressure_since: float | None = None
    interval = _env_float("ULTRON_QWEN_MONITOR_INTERVAL_SEC", 15.0)
    pressure_seconds = _env_float("ULTRON_QWEN_PRESSURE_SWITCH_SEC", 60.0)
    while not _MONITOR_STOP.wait(max(2.0, interval)):
        try:
            state = read_state()
            health = _server_health(endpoint_url())
            if not health.get("ok"):
                pid = int(state.get("pid") or 0)
                age = time.time() - float(state.get("updated_at") or 0)
                if (not pid or not _pid_running(pid)) and age > _env_float("ULTRON_QWEN_STARTUP_GRACE_SEC", 180.0):
                    ensure_server_started(reason="monitor_restart", wait_health_sec=0)
                continue

            hw = hardware_snapshot()
            if str(state.get("status") or "").strip().lower() != "running":
                name = str(state.get("profile") or "").strip().lower()
                profile = PROFILES.get(name) or choose_profile(hw)
                cmd = state.get("command") if isinstance(state.get("command"), list) else []
                _write_state(
                    profile,
                    pid=int(state.get("pid") or 0),
                    mlock=bool(state.get("mlock")),
                    args=[str(x) for x in cmd],
                    reason=str(state.get("reason") or "monitor_health_ok"),
                    status="running",
                    started_by=str(state.get("started_by") or "external_or_existing"),
                    hardware=hw,
                )
            if _hardware_under_pressure(hw):
                if pressure_since is None:
                    pressure_since = time.time()
                if time.time() - pressure_since >= pressure_seconds:
                    current = str((read_state() or {}).get("profile") or active_profile_name())
                    if current != "light_4k" and str((read_state() or {}).get("started_by") or "") == "ultronpro":
                        restart_server_with_profile("light_4k", reason="sustained_hardware_pressure")
                    pressure_since = None
            else:
                pressure_since = None
        except Exception:
            pressure_since = None


def start_runtime_monitor() -> dict[str, Any]:
    global _MONITOR_THREAD
    if not _env_flag("ULTRON_QWEN_MONITOR_ENABLED", "1"):
        return {"ok": True, "started": False, "reason": "monitor_disabled"}
    if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
        return {"ok": True, "started": False, "reason": "already_running"}
    _MONITOR_STOP.clear()
    _MONITOR_THREAD = threading.Thread(target=_monitor_loop, name="qwen-runtime-monitor", daemon=True)
    _MONITOR_THREAD.start()
    return {"ok": True, "started": True}


def stop_runtime_monitor() -> dict[str, Any]:
    _MONITOR_STOP.set()
    thread = _MONITOR_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    return {"ok": True, "stopped": True}


def _server_health(url: str) -> dict[str, Any]:
    try:
        import httpx

        with httpx.Client(timeout=0.75) as hc:
            resp = hc.get(url.rstrip("/") + "/health")
        data: Any = {}
        try:
            data = resp.json() if resp.text else {}
        except Exception:
            data = {"raw": resp.text[:120]}
        return {
            "reachable": True,
            "status_code": int(resp.status_code),
            "ok": 200 <= int(resp.status_code) < 300,
            "body": data,
        }
    except Exception as exc:
        return {"reachable": False, "ok": False, "error": str(exc)[:180]}


def runtime_status(*, check_server: bool = False) -> dict[str, Any]:
    hw = hardware_snapshot()
    recommended = choose_profile(hardware=hw)
    active = active_profile()
    st = read_state()
    url = endpoint_url()
    out = {
        "ok": True,
        "engine": "llama-server",
        "model_alias": MODEL_ALIAS,
        "endpoint": url,
        "active_profile": active.public(),
        "recommended_profile": recommended.public(),
        "profile_mismatch": active.name != recommended.name,
        "selection": {
            "requested": str(os.getenv("ULTRON_QWEN_PROFILE", "auto") or "auto"),
            "source": "state_file" if st.get("profile") in PROFILES else "auto",
            "state_path": str(state_path()),
        },
        "paths": {
            "model": str(model_path()),
            "model_exists": model_path().exists(),
            "server": str(server_path()),
            "server_exists": server_path().exists(),
        },
        "autostart": {
            "enabled": autostart_enabled(),
            "monitor_enabled": _env_flag("ULTRON_QWEN_MONITOR_ENABLED", "1"),
            "monitor_running": bool(_MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive()),
            "stop_on_shutdown": _env_flag("ULTRON_QWEN_STOP_ON_SHUTDOWN", "0"),
        },
        "logs": log_paths(),
        "hardware": hw,
        "state": st,
        "profiles": {name: prof.public() for name, prof in PROFILES.items()},
        "generation_defaults": generation_defaults(),
    }
    if check_server:
        out["server"] = _server_health(url)
    return out
