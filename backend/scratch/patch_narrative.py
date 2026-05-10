import os

path = 'ultronpro/self_governance.py'
content = open(path, 'r', encoding='utf-8').read()

target = "    return {\n        'ok': True,\n        'summary': summary,"
if target not in content:
    target = "    return {\r\n        'ok': True,\r\n        'summary': summary,"

replacement = """    first_person_report = ""
    if latest_review:
        digest_text = str((latest_review.get("latest_biographic_digest") or {}).get("narrative") or "")
        first_person_report = digest_text if digest_text else str(latest_review.get("protocol_update") or "")

    return {
        'first_person_report': first_person_report,
        'ok': True,
        'summary': summary,"""

idx = content.find(target)
if idx != -1:
    new_content = content[:idx] + replacement + content[idx + len(target):]
    open(path, 'w', encoding='utf-8').write(new_content)
    print('Patched successfully')
else:
    print('Target not found')
