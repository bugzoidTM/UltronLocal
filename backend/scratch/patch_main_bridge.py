import sys
with open('backend/ultronpro/main.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Inject skill bridge loop definition
bridge_loop = '''ACTIVE_DISCOVERY_INTERVAL_SEC = 3600  # 1 hora

SKILL_BRIDGE_INTERVAL_SEC = int(os.getenv('ULTRON_SKILL_BRIDGE_INTERVAL', '600'))  # 10 min
SKILL_BRIDGE_LOOP_ENABLED = int(os.getenv('ULTRON_SKILL_BRIDGE_LOOP_ENABLED', '1')) == 1

async def skill_bridge_loop():
    """Worker periódico para materializar skills aprendidas."""
    logger.info("🌉 Skill memory bridge loop started")
    await asyncio.sleep(_loop_start_delay('skill_bridge_loop', 200))
    while True:
        if await runtime_guard.checkpoint("skill_bridge_loop"):
            continue
        try:
            from ultronpro import skill_memory_bridge
            
            # Executa a bridge (compacta/materializa e faz o load se necessário)
            result = await asyncio.to_thread(skill_memory_bridge.run_bridge, dry_run=False, limit=20)
            
            if result.get("materialized", 0) > 0:
                logger.info(f"🌉 Skill Bridge: {result['materialized']} skills materializadas (falhas: {result['failed']})")
                store.db.add_event(
                    "skill_bridge",
                    f"materialized={result['materialized']} failed={result['failed']}"
                )
        except Exception as e:
            logger.warning(f"Skill bridge loop error: {e}")
        
        await asyncio.sleep(SKILL_BRIDGE_INTERVAL_SEC)
'''

if 'ACTIVE_DISCOVERY_INTERVAL_SEC = 3600  # 1 hora' in text:
    text = text.replace('ACTIVE_DISCOVERY_INTERVAL_SEC = 3600  # 1 hora', bridge_loop)

# 2. Add global task
if '_skill_bridge_task = None' not in text:
    text = text.replace('@app.on_event("startup")', '_skill_bridge_task = None\n\n@app.on_event("startup")')

# 3. Add to startup event globals
startup_globals = 'global _autofeeder_task, _autonomy_task, _judge_task, _prewarm_task, _roadmap_task, _agi_path_task, _reflexion_task, _self_governance_task, _meta_observer_task, _affect_task, _narrative_task, _integration_task, _sleep_cycle_task, _healer_verify_task, _background_guard_task, _inner_monologue_task, _self_improvement_task, _recursive_si_task, _active_discovery_task, _no_cloud_campaign_task'
if startup_globals in text:
    text = text.replace(startup_globals, startup_globals + ', _skill_bridge_task')

# 4. Start the task in startup_event
start_search = '''    if NO_CLOUD_CAMPAIGN_LOOP_ENABLED:
        _no_cloud_campaign_task = asyncio.create_task(no_cloud_campaign_loop())
    else:
        logger.info("No-cloud campaign loop disabled by env")'''
start_task = '''    if NO_CLOUD_CAMPAIGN_LOOP_ENABLED:
        _no_cloud_campaign_task = asyncio.create_task(no_cloud_campaign_loop())
    else:
        logger.info("No-cloud campaign loop disabled by env")

    if SKILL_BRIDGE_LOOP_ENABLED:
        _skill_bridge_task = asyncio.create_task(skill_bridge_loop())
    else:
        logger.info("Skill bridge loop disabled by env")'''
if start_search in text:
    text = text.replace(start_search, start_task)

# 5. Add to shutdown task tuple
shutdown_search = '''        _active_discovery_task,
        _no_cloud_campaign_task,
    ):'''
shutdown_task = '''        _active_discovery_task,
        _no_cloud_campaign_task,
        _skill_bridge_task,
    ):'''
if shutdown_search in text:
    text = text.replace(shutdown_search, shutdown_task)

with open('backend/ultronpro/main.py', 'w', encoding='utf-8') as f:
    f.write(text)

print('main.py patched successfully')
