import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _fresh(monkeypatch, **env):
    from ultronpro import bg_runtime

    for key in ("ULTRON_BG_THREAD_WORKERS", "ULTRON_BG_HEAVY_CONCURRENCY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    bg_runtime._reset_for_tests()
    return bg_runtime


def test_thread_workers_respects_env_and_default_is_bounded(monkeypatch):
    bg = _fresh(monkeypatch)
    # Default fica entre 4 e 16 (vs. min(32, cpu+4) do asyncio).
    assert 4 <= bg.thread_workers() <= 16

    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=3)
    assert bg.thread_workers() == 3


def test_heavy_concurrency_is_clamped_below_pool(monkeypatch):
    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=4, ULTRON_BG_HEAVY_CONCURRENCY=10)
    # Nunca pode consumir o pool inteiro: deixa ao menos 1 thread livre.
    assert bg.heavy_concurrency() == 3

    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=8, ULTRON_BG_HEAVY_CONCURRENCY=2)
    assert bg.heavy_concurrency() == 2

    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=1, ULTRON_BG_HEAVY_CONCURRENCY=5)
    assert bg.heavy_concurrency() == 1


def test_install_sets_bounded_default_executor_and_is_idempotent(monkeypatch):
    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=5)

    async def _go():
        first = bg.install()
        exec1 = bg._EXECUTOR
        second = bg.install()
        exec2 = bg._EXECUTOR
        assert exec1 is exec2  # não troca o pool em uso
        assert first["thread_workers"] == 5
        assert second["installed"] is True
        assert exec1._max_workers == 5
        return True

    assert asyncio.run(_go()) is True
    bg._reset_for_tests()


def test_run_blocking_executes_off_the_event_loop_thread(monkeypatch):
    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=4)

    async def _go():
        bg.install()
        caller = threading.get_ident()
        worker = await bg.run_blocking(threading.get_ident, label="probe")
        assert worker != caller
        assert (await bg.run_blocking(lambda x: x * 2, 21)) == 42
        return True

    assert asyncio.run(_go()) is True
    bg._reset_for_tests()


def test_semaphore_limits_concurrent_heavy_sections(monkeypatch):
    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=8, ULTRON_BG_HEAVY_CONCURRENCY=2)

    state = {"cur": 0, "peak": 0}
    lock = threading.Lock()

    def _busy():
        with lock:
            state["cur"] += 1
            state["peak"] = max(state["peak"], state["cur"])
        time.sleep(0.05)
        with lock:
            state["cur"] -= 1
        return 1

    async def _go():
        bg.install()
        await asyncio.gather(*[bg.run_blocking(_busy, label="heavy") for _ in range(12)])
        return True

    assert asyncio.run(_go()) is True
    # Apesar de 12 tarefas e 8 threads no pool, no máximo 2 seções pesadas juntas.
    assert state["peak"] <= 2
    assert state["peak"] >= 1
    bg._reset_for_tests()


def test_status_reports_inflight_and_peak(monkeypatch):
    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=6, ULTRON_BG_HEAVY_CONCURRENCY=2)

    async def _go():
        bg.install()
        await asyncio.gather(*[bg.run_blocking(lambda: time.sleep(0.02) or 1) for _ in range(5)])
        return bg.status()

    st = asyncio.run(_go())
    assert st["thread_workers"] == 6
    assert st["heavy_concurrency"] == 2
    assert st["heavy_inflight"] == 0  # tudo terminou
    assert st["heavy_peak_inflight"] >= 1
    assert st["installed"] is True
    bg._reset_for_tests()


def test_selftest_passes(monkeypatch):
    bg = _fresh(monkeypatch, ULTRON_BG_THREAD_WORKERS=6, ULTRON_BG_HEAVY_CONCURRENCY=2)
    result = bg.run_selftest()
    assert result["ok"] is True
    assert result["observed_peak"] <= result["heavy_concurrency"]
    bg._reset_for_tests()
