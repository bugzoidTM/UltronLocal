import sys
sys.path.insert(0, '.')

path = 'ultronpro/causal_discovery.py'
content = open(path, 'r', encoding='utf-8').read()

# Fix: parent.parent.parent -> parent.parent (3 levels up -> 2 levels up)
old = "DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'"
new = "DATA_DIR = Path(__file__).resolve().parent.parent / 'data'"

if old in content:
    new_content = content.replace(old, new, 1)
    open(path, 'w', encoding='utf-8').write(new_content)
    print('Fixed DATA_DIR path')
else:
    print('ANCHOR NOT FOUND — current DATA_DIR line:')
    for line in content.splitlines():
        if 'DATA_DIR' in line:
            print(' ', line)
