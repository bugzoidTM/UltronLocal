import asyncio
import logging
import os
import signal
from typing import Awaitable, Callable

logger = logging.getLogger("uvicorn")


async def run_loop_worker(name: str, loop_factory: Callable[[], Awaitable[None]]) -> None:
    logger.info("%s worker starting", name)
    task = asyncio.create_task(loop_factory())
    stop = asyncio.Event()

    def _handle_stop(*_args):
        logger.info("%s worker stopping", name)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _handle_stop())

    await stop.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("%s worker stopped", name)


BASE_DISABLED_LOOPS = {
    'ULTRON_AUTOFEEDER_ENABLED': '0',
    'ULTRON_AUTONOMY_ENABLED': '0',
    'ULTRON_JUDGE_ENABLED': '0',
    'ULTRON_ROADMAP_ENABLED': '0',
    'ULTRON_REFLEXION_ENABLED': '0',
    'ULTRON_AGI_PATH_ENABLED': '0',
    'ULTRON_PREWARM_ENABLED': '0',
    'ULTRON_VOICE_PREWARM_ENABLED': '0',
}


DEFAULT_GOVERNANCE = {
    'ULTRON_LLM_BLOCKING_CONCURRENCY': '1',
    'ULTRON_LIGHTRAG_CONCURRENCY': '1',
    'ULTRON_LLM_COMPAT_TIMEOUT_SEC': '12',
    'ULTRON_LLM_ROUTER_TIMEOUT_SEC': '15',
    'ULTRON_LLM_ANTHROPIC_TIMEOUT_SEC': '12',
    'ULTRON_OLLAMA_TIMEOUT_SEC': '25',
    'ULTRON_LOCAL_INFER_TIMEOUT_SEC': '18',
    'ULTRON_LOCAL_INFER_RETRY_TIMEOUT_SEC': '28',
    'ULTRON_PROVIDER_FAILURE_COOLDOWN_SEC': '300',
}


def apply_worker_env(*, enabled_loop_env: str, tick_env: str | None = None, tick_sec: int | None = None, extra: dict[str, str] | None = None) -> None:
    for key, value in BASE_DISABLED_LOOPS.items():
        os.environ.setdefault(key, value)
    os.environ.setdefault(enabled_loop_env, '1')
    if tick_env and tick_sec is not None:
        os.environ.setdefault(tick_env, str(int(tick_sec)))
    for key, value in DEFAULT_GOVERNANCE.items():
        os.environ.setdefault(key, value)
    for key, value in (extra or {}).items():
        os.environ.setdefault(key, value)
