import sys
sys.path.insert(0, '.')

path = 'ultronpro/main.py'
content = open(path, 'r', encoding='utf-8').read()

old = "    return causal_discovery.simulate_intervention(intervention)"
new = "    return causal_discovery.simulate_causal_intervention(intervention)"

if old in content:
    new_content = content.replace(old, new, 1)
    open(path, 'w', encoding='utf-8').write(new_content)
    print('Fixed: simulate_intervention -> simulate_causal_intervention')
else:
    print('ANCHOR NOT FOUND')
