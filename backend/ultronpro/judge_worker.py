import asyncio
import logging

from ultronpro.loop_worker import apply_worker_env, run_loop_worker

apply_worker_env(
    enabled_loop_env='ULTRON_JUDGE_ENABLED',
    tick_env='ULTRON_JUDGE_TICK_SEC',
    tick_sec=180,
)

from ultronpro.main import judge_loop  # noqa: E402


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_loop_worker('Judge', judge_loop))
