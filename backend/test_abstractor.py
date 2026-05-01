import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ultronpro import structural_abstractor, local_world_models

transitions = []
for i in range(15):
    transitions.append({'state_t': {'target': f'/tmp/cache_{i}', 'force': True, 'is_empty': False}, 'actual_outcome': 'success'})
    transitions.append({'state_t': {'target': f'/user/docs_{i}', 'force': False, 'is_empty': False}, 'actual_outcome': 'error'})

features = structural_abstractor.extract_structural_features(transitions)
print(f"Features at 30 items: {features}")

transitions_10 = transitions[:10]
features_10 = structural_abstractor.extract_structural_features(transitions_10)
print(f"Features at 10 items: {features_10}")

transitions_20 = transitions[:20]
features_20 = structural_abstractor.extract_structural_features(transitions_20)
print(f"Features at 20 items: {features_20}")
