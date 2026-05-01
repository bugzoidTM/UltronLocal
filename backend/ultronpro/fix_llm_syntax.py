import re

files = [r'f:\sistemas\UltronPro\backend\ultronpro\llm.py', r'f:\sistemas\UltronPro\backend\ultronpro\llm_adapter.py']

for filepath in files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Repeat passing to clean up multiple adjacent comma errors: `cand in (, , provider):`
    for _ in range(5):
        content = re.sub(r',\s*,', ',', content)
        content = re.sub(r'\(\s*,', '(', content)
        content = re.sub(r',\s*\)', ')', content)
        content = re.sub(r'\[\s*,', '[', content)
        content = re.sub(r',\s*\]', ']', content)

    # Empty tuple checking like `in ()`
    content = content.replace("cand in () or cand == provider", "cand == provider")
    content = content.replace("cand in ()", "False")
    content = content.replace(" pv in ()", " False")
    content = content.replace(" p in ()", " False")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

print('Syntax fixed.')
