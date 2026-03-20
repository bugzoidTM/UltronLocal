import asyncio
import logging

from ultronpro.loop_worker import apply_worker_env, run_loop_worker

apply_worker_env(
    enabled_loop_env='ULTRON_REFLEXION_ENABLED',
    tick_env='ULTRON_REFLEXION_TICK_SEC',
    tick_sec=180,
    extra={
        'ULTRON_OLLAMA_TIMEOUT_SEC': '18',
        'ULTRON_LOCAL_INFER_TIMEOUT_SEC': '14',
        'ULTRON_LOCAL_INFER_RETRY_TIMEOUT_SEC': '22',
    },
)

from ultronpro.main import reflexion_loop  # noqa: E402


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_loop_worker('Reflexion', reflexion_loop))
