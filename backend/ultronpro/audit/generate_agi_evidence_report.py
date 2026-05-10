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
        # The module returns metrics['ticks']
        metrics = ac_stat.get("metrics", {})
        report["autonomous_cognition_ticks"] = metrics.get("ticks", 0)
    except Exception as e:
        print(f"Error loading AC status: {e}")

    # RL Stats
    try:
        rl_stat = online_rl_loop.status()
        policy = rl_stat.get("policy", {})
        report["rl_policy_global_updates"] = policy.get("global_updates", 0)
        
        # RL Arms
        arms = policy.get("arms", [])
        count_n_gt_10 = 0
        if isinstance(arms, list):
            for arm_data in arms:
                if arm_data.get("n", 0) >= 10:
                    count_n_gt_10 += 1
        elif isinstance(arms, dict):
             for arm_key, arm_data in arms.items():
                if arm_data.get("n", 0) >= 10:
                    count_n_gt_10 += 1
        report["active_rl_arms_with_n_gt_10"] = count_n_gt_10
    except Exception as e:
        print(f"Error loading RL status: {e}")

    # Online RL cycles (Source of Truth: online_rl_loop.state)
    try:
        rl_stat = online_rl_loop.status()
        report["online_rl_cycles"] = rl_stat.get("state", {}).get("cycle_count", 0)
        
        # Surprise Trend (Source of Truth: online_rl_loop.status)
        report["surprise_trend_30_cycles"] = rl_stat.get("state", {}).get("surprise_trend", "unknown")
    except Exception:
        # Fallback to file
        try:
            with open('backend/data/online_rl_runs.jsonl', 'r', encoding='utf-8') as f:
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
            with open('backend/data/causal_graph_edges.jsonl', 'r', encoding='utf-8') as f:
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
        # Suite count - ext_stat.get("suite") has the count from list_suite()
        report["benchmark_suite_count"] = ext_stat.get("suite", {}).get("count", 0)
        
        # Accuracy - latest_compare has overall_accuracy
        latest_compare = ext_stat.get("latest_compare")
        if isinstance(latest_compare, dict):
            report["benchmark_accuracy"] = latest_compare.get("overall_accuracy", {}).get("current", 0.0)
        
        if not report["benchmark_accuracy"]:
            # Fallback to accuracy or latest_accuracy if present
            report["benchmark_accuracy"] = ext_stat.get("latest_accuracy", ext_stat.get("accuracy", 0.0))

        # Try to parse from baseline or recent runs
        no_cloud_acc = 0.0
        try:
            # Check both public eval and hard cognitive eval logs for no-cloud probe
            log_files = [
                'backend/data/external_benchmarks/public_eval_runs.jsonl',
                'backend/data/hard_cognitive_eval_runs.jsonl'
            ]
            for log_file in log_files:
                if not os.path.exists(log_file):
                    continue
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        run = json.loads(line)
                        # Skip oracle/selftest runs (these are for harness validation, not cognitive measurement)
                        if run.get("predictor") == "oracle" or run.get("tag") == "selftest" or "oracle" in str(run).lower():
                            continue

                        # Check for no_cloud_probe_accuracy (flat or nested in sections.external_benchmark)
                        probe_acc = run.get("no_cloud_probe_accuracy")
                        if probe_acc is None and "sections" in run:
                            ext_bench = run["sections"].get("external_benchmark", {})
                            if isinstance(ext_bench, dict):
                                probe_acc = ext_bench.get("no_cloud_probe_accuracy")
                        
                        if probe_acc is not None:
                            no_cloud_acc = probe_acc
                        
                        # Update benchmark accuracy if not set yet (favoring recent logs)
                        if not report["benchmark_accuracy"]:
                            acc = run.get("overall_accuracy", run.get("accuracy", 0.0))
                            if not acc and "sections" in run:
                                # In hard eval, the overall score might be 'score_0_10'
                                score = run.get("score_0_10")
                                if score is not None:
                                    acc = score / 10.0
                            report["benchmark_accuracy"] = acc
                            
            report["no_cloud_accuracy"] = no_cloud_acc
        except Exception:
            pass
    except Exception as e:
        print(f"Error loading Benchmark status: {e}")

    # Rollback Rate
    try:
        with open('backend/data/self_calibrating_gate_state.json', 'r', encoding='utf-8') as f:
            scg = json.load(f)
            report["rollback_rate"] = scg.get("rollback_rate", 0.0)
    except Exception:
        pass

    return report

if __name__ == "__main__":
    report = generate_report()
    print(json.dumps(report, indent=2))
