import asyncio
import logging

from ultronpro.loop_worker import apply_worker_env, run_loop_worker

apply_worker_env(
    enabled_loop_env='ULTRON_AGI_PATH_ENABLED',
    tick_sec=360,
    extra={
        'ULTRON_OLLAMA_TIMEOUT_SEC': '20',
        'ULTRON_LOCAL_INFER_TIMEOUT_SEC': '15',
        'ULTRON_LOCAL_INFER_RETRY_TIMEOUT_SEC': '24',
    },
)

from ultronpro.main import agi_path_loop  # noqa: E402


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_loop_worker('AGI path', agi_path_loop))
