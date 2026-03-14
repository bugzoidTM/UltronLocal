import asyncio
import logging
import os

from ultronpro.loop_worker import apply_worker_env, run_loop_worker

# Force worker profile before importing main
apply_worker_env(
    enabled_loop_env='ULTRON_AUTONOMY_ENABLED',
    tick_env='ULTRON_AUTONOMY_TICK_SEC',
    tick_sec=300,
    extra={
        'ULTRON_AUTONOMY_BUDGET_PER_MIN': '1',
    },
)

from ultronpro.main import autonomy_loop  # noqa: E402


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_loop_worker('Autonomy', autonomy_loop))
