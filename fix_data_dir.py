from pathlib import Path

base = Path(__file__).resolve().parent / 'backend' / 'ultronpro'

files = [
    'continuous_learning.py',
    'epistemic_dialogue.py',
    'inner_monologue.py',
    'local_reasoning_engine.py',
    'local_world_models.py',
    'long_term_epistemic_agency.py',
    'recursive_self_improvement.py',
    'self_improvement_engine.py',
    'vision.py',
    'working_memory.py',
    'world_model.py',
    'phenomenal.py',
    'qualia.py',
    'task_manager.py',
    'tool_registry.py',
]

old = ".parent.parent.parent / 'data'"
new = ".parent.parent / 'data'"

count = 0
for fname in files:
    fpath = base / fname
    if fpath.exists():
        content = fpath.read_text(encoding='utf-8')
        if old in content:
            fpath.write_text(content.replace(old, new), encoding='utf-8')
            print(f'Fixed: {fname}')
            count += 1

# core/config.py separately
cfg = base / 'core' / 'config.py'
if cfg.exists():
    content = cfg.read_text(encoding='utf-8')
    if old in content:
        cfg.write_text(content.replace(old, new), encoding='utf-8')
        print('Fixed: core/config.py')
        count += 1

print(f'\nTotal fixed: {count}')
