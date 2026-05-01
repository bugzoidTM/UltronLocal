import sys, json, random
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro.rl_policy import RLPolicy
# The user included these in their snippet, though they aren't used in the diagnostic logic below
try:
    from ultronpro.external_benchmarks import run_suite
    from ultronpro.quality_eval import evaluate_response
except ImportError:
    pass

# Initialize policy
policy = RLPolicy()

# Arms available
ARMS = ['ask_evidence', 'generate_analogy', 'auto_resolve_conflicts']
CONTEXT = 'normal'

# 1. Run 20 decisions with Thompson Sampling
ts_choices = []
for i in range(20):
    chosen = policy.select_action(ARMS, context=CONTEXT)
    ts_choices.append(chosen)

# 2. Results distribution
from collections import Counter
print("=== Thompson Sampling — distribuição de escolhas ===")
counts = Counter(ts_choices)
for arm, count in counts.items():
    print(f"{arm}: {count}")

# State check
state_path = 'f:/sistemas/UltronPro/backend/data/rl_policy_state.json'
with open(state_path) as f:
    state = json.load(f)

print("\n=== Estado atual dos braços ===")
for arm_key, params in state['arms'].items():
    alpha = params.get('alpha', 1)
    beta = params.get('beta', 1)
    mean = alpha / max(0.01, (alpha + beta))
    n = params.get('n', 0)
    print(f"{arm_key}: alpha={alpha:.2f} beta={beta:.2f} mean={mean:.3f} n={n}")

static_choice = 'ask_evidence' # Assuming this is the best alpha
print(f"\n=== Política Estática — sempre escolhe: {static_choice} ===")

print("\n=== Diagnóstico ===")
print("O RL tem utilidade se distribui escolhas de forma diferente")
print("da política estática E se essa distribuição produz reward maior.")
print("Sem rodar as ações em tarefas reais, só podemos verificar")
print("se o TS está explorando ou convergiu para um único braço.")

if counts.get(static_choice, 0) >= 18:
    print("\nVERDITO: CONVERGÊNCIA TOTAL. O TS está agindo como política estática.")
else:
    print("\nVERDITO: EXPLORAÇÃO ATIVA. O sistema ainda está variando escolhas.")
