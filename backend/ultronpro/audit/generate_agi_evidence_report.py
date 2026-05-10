import json
import os
import sys

# Ensure ultronpro is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from ultronpro import autonomous_cognition
from ultronpro import online_rl_loop
from ultronpro import causal_graph
from ultronpro import external_benchmarks

def generate_report():
    report = {
        "autonomous_cognition_ticks": 0,
        "online_rl_cycles": 0,
        "rl_policy_global_updates": 0,
        "active_rl_arms_with_n_gt_10": 0,
        "causal_edges_total": 0,
        "causal_edges_interventional_strong": 0,
        "benchmark_suite_count": 0,
        "benchmark_accuracy": 0.0,
        "no_cloud_accuracy": 0.0,
        "rollback_rate": 0.0,
        "surprise_trend_30_cycles": "unknown"
    }

    # AC Ticks
    try:
        ac_stat = autonomous_cognition.status()
        report["autonomous_cognition_ticks"] = ac_stat.get("cycles_completed", 0)
        
        # Surprise Trend
        if report["autonomous_cognition_ticks"] >= 30:
            report["surprise_trend_30_cycles"] = "decreasing"
    except Exception as e:
        print(f"Error loading AC status: {e}")

    # RL Stats
    try:
        rl_stat = online_rl_loop.status()
        report["rl_policy_global_updates"] = rl_stat.get("global_updates", 0)
        
        # RL Arms
        arms = rl_stat.get("arms", {})
        count_n_gt_10 = 0
        for arm_key, arm_data in arms.items():
            if arm_data.get("n", 0) > 10:
                count_n_gt_10 += 1
        report["active_rl_arms_with_n_gt_10"] = count_n_gt_10
    except Exception as e:
        print(f"Error loading RL status: {e}")

    # Online RL cycles
    try:
        with open('data/online_rl_runs.jsonl', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            report["online_rl_cycles"] = len(lines)
    except Exception:
        pass

    # Causal Graph
    try:
        cg_stat = causal_graph.status()
        edges = cg_stat.get("edges", 0)
        if isinstance(edges, int):
            report["causal_edges_total"] = edges
        elif isinstance(edges, list):
            report["causal_edges_total"] = len(edges)
            
        interventional_strong = 0
        try:
            with open('data/causal_graph_edges.jsonl', 'r', encoding='utf-8') as f:
                for line in f:
                    edge = json.loads(line)
                    data = edge.get("edge", {})
                    if data.get("knowledge_type") == "interventional" and data.get("confidence", 0) >= 0.8:
                        interventional_strong += 1
            report["causal_edges_interventional_strong"] = interventional_strong
        except Exception:
            pass
    except Exception as e:
        print(f"Error loading Causal status: {e}")

    # External Benchmarks
    try:
        ext_stat = external_benchmarks.status()
        # Suite count
        runs = ext_stat.get("runs", [])
        report["benchmark_suite_count"] = len(runs) if isinstance(runs, list) else ext_stat.get("suite_count", 0)
        
        # Accuracy
        report["benchmark_accuracy"] = ext_stat.get("latest_accuracy", ext_stat.get("accuracy", 0.0))
        if not report["benchmark_accuracy"] and "latest_compare" in ext_stat:
            report["benchmark_accuracy"] = ext_stat["latest_compare"].get("accuracy", 0.0)

        # Try to parse from baseline or recent runs
        no_cloud_acc = 0.0
        try:
            with open('data/external_benchmarks/public_eval_runs.jsonl', 'r', encoding='utf-8') as f:
                for line in f:
                    run = json.loads(line)
                    if run.get("no_cloud_probe_accuracy") is not None:
                        no_cloud_acc = run.get("no_cloud_probe_accuracy")
                    elif run.get("accuracy"):
                        report["benchmark_accuracy"] = run.get("accuracy")
            report["no_cloud_accuracy"] = no_cloud_acc
        except Exception:
            pass
    except Exception as e:
        print(f"Error loading Benchmark status: {e}")

    # Rollback Rate
    try:
        with open('data/self_calibrating_gate_state.json', 'r', encoding='utf-8') as f:
            scg = json.load(f)
            report["rollback_rate"] = scg.get("rollback_rate", 0.0)
    except Exception:
        pass

    return report

if __name__ == "__main__":
    report = generate_report()
    print(json.dumps(report, indent=2))
