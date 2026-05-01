"""
Patch script 2: patches 1 e 2 do episodic_compiler.py
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

# Find the skill_promoted block by unique nearby text
anchor1 = "ttl_sec=7200\n                    )\n                elif target['confirmation_rate'] < DISCARD_THRESHOLD:"
if anchor1 in content:
    content = content.replace(
        anchor1,
        "ttl_sec=7200\n                    )" + HOOK1 + "\n                elif target['confirmation_rate'] < DISCARD_THRESHOLD:",
        1
    )
    print("Patch 1 (skill_promoted): OK")
else:
    # Try to locate it differently
    idx = content.find("'causal.skill_promoted'")
    print(f"Patch 1 (skill_promoted): ANCHOR NOT FOUND. skill_promoted at idx={idx}")
    if idx > 0:
        chunk = content[idx:idx+400]
        print(repr(chunk))

# Find the hypothesis_discarded block
anchor2 = "ttl_sec=3600\n                    )\n                elif target['confirmation_rate'] < CONFIRMATION_THRESHOLD:"
if anchor2 in content:
    content = content.replace(
        anchor2,
        "ttl_sec=3600\n                    )" + HOOK2 + "\n                elif target['confirmation_rate'] < CONFIRMATION_THRESHOLD:",
        1
    )
    print("Patch 2 (hypothesis_discarded): OK")
else:
    idx = content.find("'causal.hypothesis_discarded'")
    print(f"Patch 2 (discarded): ANCHOR NOT FOUND. discarded at idx={idx}")
    if idx > 0:
        chunk = content[idx:idx+300]
        print(repr(chunk))

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("File written.")
