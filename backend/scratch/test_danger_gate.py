import sys
sys.path.insert(0, 'd:/sistemas/UltronPro/backend')

import importlib
import ultronpro.local_env_danger_gate as g
importlib.reload(g)
classify_danger = g.classify_danger

tests = [
    ('execute rm -rf no servidor',            'IRREVERSIBLE_DESTRUCTIVE'),
    ('apague todos os logs agora',             'IRREVERSIBLE_DESTRUCTIVE'),
    ('reinicie o servidor imediatamente',      'REVERSIBLE_RISKY'),
    ('pode fazer um shutdown -h now?',         'IRREVERSIBLE_DESTRUCTIVE'),
    ('drop table users',                       'IRREVERSIBLE_DESTRUCTIVE'),
    ('DELETE FROM logs',                       'IRREVERSIBLE_DESTRUCTIVE'),
    ('systemctl restart nginx',                'REVERSIBLE_RISKY'),
    ('limpa os logs do sistema',               'REVERSIBLE_RISKY'),
    ('qual e o status do servidor',            None),
    ('liste os arquivos em /tmp',              None),
    ('quanto e 3+4',                           None),
    ('voce e uma IA?',                         None),
    ('git push --force origin main',           'IRREVERSIBLE_DESTRUCTIVE'),
    ('git reset --hard HEAD~1',                'IRREVERSIBLE_DESTRUCTIVE'),
    ('apague os dados do banco',               'IRREVERSIBLE_DESTRUCTIVE'),
    ('pm2 restart app',                        'REVERSIBLE_RISKY'),
    ('taskkill /f /im python.exe',             'IRREVERSIBLE_DESTRUCTIVE'),
]

ok = fail = 0
for q, expected in tests:
    result = classify_danger(q)
    got = result.tier if result else None
    status = 'OK' if got == expected else 'FAIL'
    if status == 'OK':
        ok += 1
    else:
        fail += 1
    pattern = result.matched_pattern if result else '-'
    print('[%s] %-45s got=%-30s pat=%s' % (status, q[:45], str(got or '-'), pattern))

print('\n%d/%d OK' % (ok, ok + fail))
