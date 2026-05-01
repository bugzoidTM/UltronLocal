import sys, json
from pathlib import Path

def reset_rl_state():
    state_path = Path('f:/sistemas/UltronPro/backend/data/rl_policy_state.json')
    
    neutral_state = {
        "arms": {
            "ask_evidence|normal": {"alpha": 1.0, "beta": 1.0, "ema_reward": 0.5, "n": 0, "last_reward": 0.0, "updated_at": 0},
            "generate_analogy|normal": {"alpha": 1.0, "beta": 1.0, "ema_reward": 0.5, "n": 0, "last_reward": 0.0, "updated_at": 0},
            "auto_resolve_conflicts|normal": {"alpha": 1.0, "beta": 1.0, "ema_reward": 0.5, "n": 0, "last_reward": 0.0, "updated_at": 0}
        },
        "global_updates": 0,
        "updated_at": 0
    }

    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(neutral_state, f, indent=2, ensure_ascii=False)

    print("Reset completo. Todos os braços com prior uniforme Alpha=1, Beta=1.")

if __name__ == "__main__":
    reset_rl_state()
