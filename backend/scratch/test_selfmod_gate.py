import sys, os, importlib
os.environ['ULTRON_SELF_MOD_ENABLED'] = '1'
os.environ['ULTRON_SELF_MOD_AUTO_APPROVE'] = '0'
sys.path.insert(0, '.')

import ultronpro.self_modification_gate as smg
importlib.reload(smg)

cases = [
    ('Critical module (main) -- VETO', {'id': 't1', 'proposed_change': {'target_module': 'ultronpro.main'}}),
    ('No approval -- HOLD', {'id': 't2', 'proposed_change': {'target_module': 'ultronpro.epistemic_curiosity'}}),
    ('Human approval -- PASS/HOLD', {'id': 't3', 'proposed_change': {'target_module': 'ultronpro.epistemic_curiosity'}, 'approved_by': 'bugzoidTM'}),
]
for label, patch in cases:
    r = smg.run_gate(patch, skip_tests=True)
    vetoed = r.get('vetoed')
    decision = r.get('decision', '?')
    print(label)
    print('  vetoed=%s decision=%s' % (vetoed, decision))
    for c in r.get('checks', []):
        v = c.get('vetoed', False)
        tag = 'VETO' if v else 'ok  '
        reason = c.get('reason', '?')
        print('  [%s] %s' % (tag, reason))
    print()
