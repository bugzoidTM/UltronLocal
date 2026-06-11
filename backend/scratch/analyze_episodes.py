import json
with open('D:/sistemas/UltronPro/backend/scratch/operational_proof_episodes.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        ep = json.loads(line)
        if ep['phase'] in ('baseline', 'stress'):
            print(f"{ep['phase']:10s} | {ep['task']:30s} -> actual={ep['actual_route']:15s} expected={ep['expected_route']:15s} surp={ep['surprise']:.2f}")
