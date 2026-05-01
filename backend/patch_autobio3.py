"""
Patch script 3: patches 1 e 2 do episodic_compiler.py (final)
"""
path = r'f:\sistemas\UltronPro\backend\ultronpro\episodic_compiler.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

HOOK1 = '''
                # Camada 1: episodio autobiografico de conquista cognitiva
                try:
                    from ultronpro import autobiographical_router as _abio
                    _abio.append_self_event(
                        kind='abstraction_promoted',
                        description=(
                            "Abstracao '" + target['name'] + "' promovida a compiled_skill apos " + str(total) + " testes "
                            + "(taxa de confirmacao: " + str(round(target['confirmation_rate']*100)) + "%, dominio: " + str(target.get('domain')) + ")."
                        ),
                        outcome='success',
                        module='episodic_compiler',
                        importance=0.85,
                        extra={'abs_id': abs_id, 'name': target['name'],
                               'confirmation_rate': target['confirmation_rate'],
                               'domain': target.get('domain')},
                    )
                except Exception:
                    pass'''

HOOK2 = '''
                # Camada 1: episodio autobiografico de descarte (hipotese refutada)
                try:
                    from ultronpro import autobiographical_router as _abio
                    _abio.append_self_event(
                        kind='abstraction_discarded',
                        description=(
                            "Abstracao '" + target['name'] + "' descartada por falha sistematica apos " + str(total) + " testes "
                            + "(taxa de confirmacao: " + str(round(target['confirmation_rate']*100)) + "%, dominio: " + str(target.get('domain')) + "). "
                            + "Hipotese estava errada. Sistema aprendeu com o erro."
                        ),
                        outcome='correction',
                        module='episodic_compiler',
                        importance=0.80,
                        extra={'abs_id': abs_id, 'name': target['name'],
                               'confirmation_rate': target['confirmation_rate'],
                               'domain': target.get('domain'), 'tests': total},
                    )
                except Exception:
                    pass'''

# Find the skill_promoted end
anchor1 = "salience=0.9,\n                    ttl_sec=7200\n                )"
if anchor1 in content and "abstraction_promoted" not in content:
    content = content.replace(
        anchor1,
        anchor1 + HOOK1,
        1
    )
    print("Patch 1 (skill_promoted): OK")
else:
    print("Patch 1: Either already applied or anchor not found.")

# Find the hypothesis_discarded end
anchor2 = "salience=0.7,\n                    ttl_sec=3600\n                )"
if anchor2 in content and "abstraction_discarded" not in content:
    content = content.replace(
        anchor2,
        anchor2 + HOOK2,
        1
    )
    print("Patch 2 (hypothesis_discarded): OK")
else:
    print("Patch 2: Either already applied or anchor not found.")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("File written.")
