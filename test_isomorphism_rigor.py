import sys
sys.path.insert(0, 'backend')
from ultronpro.local_world_models import get_manager
from ultronpro.autoisomorphic_mapper import _parse_struct_key, _parse_val

manager = get_manager()

for name in ['decision_planning', 'drone_navigation']:
    model = manager.models[name]
    print(f"\n=== {name} ===")
    for key, entry in model.empirical_matrix.items():
        if key.startswith('struct:'):
            parsed = _parse_struct_key(key)
            ev = entry.get('expected_value', '?')
            obs = entry.get('observations', '?')
            print(f"  key={key!r:60s} -> feat+val={parsed}  EV={ev}  obs={obs}")
