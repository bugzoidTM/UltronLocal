"""Limitador de paralelismo para o trabalho de fundo.

O processo do servidor (ultronpro.main:app) executa ~25 loops autônomos em
processo, e cada um despacha trabalho via ``asyncio.to_thread``. Sem
configuração, o asyncio usa um ThreadPoolExecutor default de ``min(32, cpu+4)``
threads: os loops disputam o pool e os núcleos, o GIL é martelado e o event
loop fica sem CPU (o background_guard chega a registrar dezenas de segundos de
lag). Os workers dedicados (autonomy_worker etc.) herdam o mesmo padrão.

Este módulo instala um executor **limitado** como default do loop — todos os
``asyncio.to_thread`` existentes passam a respeitá-lo sem mudança de call site —
e oferece ``run_blocking`` para seções CPU-bound de fundo, que além de tirar o
trabalho do event loop, passa por um **semáforo** que limita quantas seções
pesadas correm ao mesmo tempo (reservando núcleo para o event loop e para o
foreground de chat/voz). Nenhum loop é desligado; apenas o paralelismo é
contido. Determinístico, sem LLM.
"""

from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_HEAVY_SEM: asyncio.Semaphore | None = None
_HEAVY_SEM_LOOP: asyncio.AbstractEventLoop | None = None
_INSTALLED = False
_INFLIGHT = 0
_PEAK_INFLIGHT = 0


def _cpu() -> int:
    try:
        return max(1, int(os.cpu_count() or 1))
    except Exception:
        return 1


def _env_int(name: str, default: int) -> int:
    try:
        value = int(float(os.getenv(name, str(default)) or default))
    except Exception:
        return default
    return value


def thread_workers() -> int:
    """Tamanho do pool de fundo. Default conservador: cap em 16 (vs. 32 do
    asyncio), com folga para I/O (ex. chamadas LLM) sem explodir threads."""
    default = max(4, min(16, _cpu() + 4))
    return max(1, _env_int("ULTRON_BG_THREAD_WORKERS", default))


def heavy_concurrency() -> int:
    """Quantas seções CPU-bound de fundo podem correr simultaneamente.

    Default: metade dos núcleos (mínimo 1), sempre deixando ao menos uma thread
    do pool livre para o foreground. Esta é a alavanca principal de 'limitar
    paralelismo'.
    """
    default = max(1, _cpu() // 2)
    requested = max(1, _env_int("ULTRON_BG_HEAVY_CONCURRENCY", default))
    return max(1, min(requested, thread_workers() - 1)) if thread_workers() > 1 else 1


def _build_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(
        max_workers=thread_workers(),
        thread_name_prefix="ultron-bg",
    )


def install(loop: asyncio.AbstractEventLoop | None = None) -> dict[str, Any]:
    """Instala o executor limitado como default do loop. Idempotente por
    processo: instala uma vez e reusa (não troca o pool em uso)."""
    global _EXECUTOR, _HEAVY_SEM, _HEAVY_SEM_LOOP, _INSTALLED
    try:
        loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    with _LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = _build_executor()
        if loop is not None:
            try:
                loop.set_default_executor(_EXECUTOR)
                _INSTALLED = True
            except Exception:
                pass
            # Semáforo é ligado ao loop corrente; (re)cria se o loop mudou.
            if _HEAVY_SEM is None or _HEAVY_SEM_LOOP is not loop:
                _HEAVY_SEM = asyncio.Semaphore(heavy_concurrency())
                _HEAVY_SEM_LOOP = loop
    return status()


def _ensure_semaphore() -> asyncio.Semaphore:
    global _HEAVY_SEM, _HEAVY_SEM_LOOP
    loop = asyncio.get_running_loop()
    if _HEAVY_SEM is None or _HEAVY_SEM_LOOP is not loop:
        _HEAVY_SEM = asyncio.Semaphore(heavy_concurrency())
        _HEAVY_SEM_LOOP = loop
    return _HEAVY_SEM


async def run_blocking(fn: Callable[..., Any], *args: Any, label: str | None = None) -> Any:
    """Executa trabalho CPU-bound de fundo fora do event loop e sob o semáforo
    de carga, para que os loops autônomos não saturem todos os núcleos."""
    global _INFLIGHT, _PEAK_INFLIGHT
    sem = _ensure_semaphore()
    loop = asyncio.get_running_loop()
    async with sem:
        _INFLIGHT += 1
        _PEAK_INFLIGHT = max(_PEAK_INFLIGHT, _INFLIGHT)
        try:
            return await loop.run_in_executor(_EXECUTOR, lambda: fn(*args))
        finally:
            _INFLIGHT -= 1


def status() -> dict[str, Any]:
    return {
        "ok": True,
        "installed": _INSTALLED,
        "cpu_count": _cpu(),
        "thread_workers": thread_workers(),
        "heavy_concurrency": heavy_concurrency(),
        "heavy_inflight": _INFLIGHT,
        "heavy_peak_inflight": _PEAK_INFLIGHT,
        "executor_active": _EXECUTOR is not None,
    }


def _reset_for_tests() -> None:
    """Apenas para testes: descarta executor/semáforo instalados."""
    global _EXECUTOR, _HEAVY_SEM, _HEAVY_SEM_LOOP, _INSTALLED, _INFLIGHT, _PEAK_INFLIGHT
    with _LOCK:
        if _EXECUTOR is not None:
            try:
                _EXECUTOR.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        _EXECUTOR = None
        _HEAVY_SEM = None
        _HEAVY_SEM_LOOP = None
        _INSTALLED = False
        _INFLIGHT = 0
        _PEAK_INFLIGHT = 0


def run_selftest() -> dict[str, Any]:
    async def _probe() -> dict[str, Any]:
        install()
        peak_holder = {"max": 0, "cur": 0}
        lock = threading.Lock()

        def _busy() -> int:
            with lock:
                peak_holder["cur"] += 1
                peak_holder["max"] = max(peak_holder["max"], peak_holder["cur"])
            # trabalho curto para medir concorrência simultânea
            end = threading.Event()
            end.wait(0.05)
            with lock:
                peak_holder["cur"] -= 1
            return 1

        await asyncio.gather(*[run_blocking(_busy, label="selftest") for _ in range(8)])
        return {
            "ok": peak_holder["max"] <= heavy_concurrency(),
            "non_llm": True,
            "observed_peak": peak_holder["max"],
            "heavy_concurrency": heavy_concurrency(),
        }

    return asyncio.run(_probe())
