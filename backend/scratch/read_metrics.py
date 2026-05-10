import json

try:
    with open('data/agi_production_test_runs.jsonl', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    if not lines:
        print("Empty file")
        exit()
    last_run = json.loads(lines[-1])
    for front in last_run['fronts']:
        for check in front['checks']:
            if check['name'] in ['rl_policy_drives', 'autonomous_cognition_ticks', 'causal_graph_status']:
                print(f"{check['name']}: {check['detail']}")
except Exception as e:
    print(f"Error: {e}")
