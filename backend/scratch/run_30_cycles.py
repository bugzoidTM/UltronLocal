import sys
import json
import time

sys.path.insert(0, '.')
from ultronpro import autonomous_cognition, homeostasis, intrinsic_utility

def run_30_cycles():
    print("Iniciando 30 ciclos de autonomous_cognition...")
    cycles = []
    actions_executed = 0
    consequences_learned = 0
    new_goals = 0
    errors = 0
    repeated_failures = 0
    
    last_action = None
    consecutive_same_action_failures = 0

    for i in range(30):
        util_before = intrinsic_utility.status().get("utility", 0.0)
        
        try:
            tick_res = autonomous_cognition.tick(stage="full", train_world_model=True)
            error = None
        except Exception as e:
            tick_res = {}
            error = str(e)
            errors += 1
            
        util_after = intrinsic_utility.status().get("utility", 0.0)
        
        action = tick_res.get("action")
        surprise = 0.0
        
        if action:
            actions_executed += 1
            if action.get("error") or not action.get("ok", True):
                if last_action == action.get("action_key"):
                    consecutive_same_action_failures += 1
                last_action = action.get("action_key")
            else:
                last_action = None
                
            conseq = action.get("consequence", {})
            if conseq:
                consequences_learned += 1
                surprise = conseq.get("surprise", 0.0)
                
        if tick_res.get("new_goal_created") or tick_res.get("goal"):
            new_goals += 1
            
        # fallback for surprise if no action or conseq
        if surprise == 0.0:
            vitals = homeostasis.status().get("vitals", {})
            surprise = vitals.get("uncertainty_load", 0.0)
            
        utility_delta = util_after - util_before
        vitals_after = homeostasis.status().get("vitals", {})
        rollback = 1 if (vitals_after.get("coherence_score", 1.0) < 0.3) else 0
        
        cycle_data = {
            "cycle": i + 1,
            "surprise": surprise,
            "utility_delta": utility_delta,
            "error": error,
            "rollback": rollback,
            "action": action.get("action_key") if action else None
        }
        cycles.append(cycle_data)
        print(f"Cycle {i+1}: surprise={surprise:.4f}, util_delta={utility_delta:.4f}, error={'yes' if error else 'no'}, action={cycle_data['action']}")
        
    surprise_first_10 = [c["surprise"] for c in cycles[:10]]
    surprise_last_10 = [c["surprise"] for c in cycles[-10:]]
    
    mean_first_10 = sum(surprise_first_10) / len(surprise_first_10) if surprise_first_10 else 0.0
    mean_last_10 = sum(surprise_last_10) / len(surprise_last_10) if surprise_last_10 else 0.0
    
    rep_failure_rate = consecutive_same_action_failures / max(1, actions_executed)
    
    report = {
        "surprise_mean_first_10": mean_first_10,
        "surprise_mean_last_10": mean_last_10,
        "actions_executed": actions_executed,
        "consequences_learned": consequences_learned,
        "new_goals_created": new_goals,
        "repeated_failure_rate": rep_failure_rate,
        "cycles": cycles
    }
    
    with open("data/30_cycles_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        
    print("\n=== Relatório Longitudinal ===")
    print(f"Surpresa (Primeiros 10): {mean_first_10:.4f}")
    print(f"Surpresa (Últimos 10):   {mean_last_10:.4f}")
    print(f"Ações Executadas:        {actions_executed}")
    print(f"Consequências Aprendidas:{consequences_learned}")
    print(f"Novos Goals Criados:     {new_goals}")
    print(f"Taxa de Falha Repetida:  {rep_failure_rate:.2%}")
    
    if mean_last_10 < mean_first_10:
        print("-> CONCLUSÃO: A surpresa está caindo! O modelo de mundo está aprendendo de forma confiável.")
    else:
        print("-> CONCLUSÃO: A surpresa NÃO caiu. O sistema não está acumulando previsibilidade.")

if __name__ == "__main__":
    run_30_cycles()
