import sys, json
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro import planner
from ultronpro import store
from ultronpro import cognitive_patches

# Mock Store
class MockStore:
    def list_experiences(self, limit=20): return []
    def get_active_goal(self): return {"title": "Teste de Patches", "description": "Verificar se o planner lê regras ativas."}
    def list_conflicts(self, status='open', limit=10): return []
    def stats(self): return {"questions_open": 5}
    def list_laws(self, status='active', limit=10): return []
    def list_norms(self, limit=200): return []

# 1. Criar um patch promovido
patch_id = "test_patch_elo_1"
cognitive_patches.create_patch({
    "id": patch_id,
    "kind": "heuristic_patch",
    "problem_pattern": "overconfidence",
    "proposed_change": {"rule": "REGRAL-CRITICA-PLANNED: SEMPRE pedir evidência tripla para ciência."},
    "status": "promoted"
})

print(f"Patch {patch_id} criado e promovido.")

# 2. Executar o planner
print("\nExecutando propose_actions...")
from unittest.mock import MagicMock
# Mocking llm.complete to see if patches appear in prompt
from ultronpro import llm
original_complete = llm.complete
llm.complete = MagicMock(side_effect=lambda prompt, **kwargs: f"AÇÃO_AVALIADA: {prompt[:200]}...")

actions = planner.propose_actions(MockStore())

# 3. Verificar se o prompt continha o patch
prompts_seen = [call.args[0] for call in llm.complete.call_args_list]
found_patch = False
for p in prompts_seen:
    if "REGRAL-CRITICA-PLANNED" in p:
        found_patch = True
        print("\n✅ SUCESSO: O patch foi incluído no prompt do Planner!")
        break

if not found_patch:
    print("\n❌ FALHA: O patch não foi encontrado nos prompts do Planner.")

# Cleanup
llm.complete = original_complete
