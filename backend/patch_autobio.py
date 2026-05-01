"""
Patch script: integra autobiographical_router no episodic_compiler.py
Adiciona hooks da Camada 1 nas transições lifecycle: promoção, descarte, revisão.
"""
import re

path = r'f:\sistemas\UltronPro\backend\ultronpro\episodic_compiler.py'

with open(path, encoding='utf-8') as f:
    content = f.read()

# ── Patch 1: após skill_promoted workspace publish → adicionar autobio hook ──
SKILL_PROMOTED_ANCHOR = "                        salience=0.9,\n                        ttl_sec=7200\n                    )"
SKILL_PROMOTED_INSERT = """
                    # Camada 1: episodio autobiografico de conquista cognitiva
                    try:
                        from ultronpro import autobiographical_router as _abio
                        _abio.append_self_event(
                            kind='abstraction_promoted',
                            description=(
                                f"Abstracao '{target['name']}' promovida a compiled_skill apos {total} testes "
                                f"(taxa de confirmacao: {target['confirmation_rate']:.0%}, dominio: {target.get('domain')})."
                            ),
                            outcome='success',
                            module='episodic_compiler',
                            importance=0.85,
                            extra={'abs_id': abs_id, 'name': target['name'],
                                   'confirmation_rate': target['confirmation_rate'],
                                   'domain': target.get('domain')},
                        )
                    except Exception:
                        pass"""

# ── Patch 2: após hypothesis_discarded workspace publish → adicionar autobio hook ──
DISCARD_ANCHOR = "                        salience=0.7,\n                        ttl_sec=3600\n                    )\n                elif target['confirmation_rate'] < CONFIRMATION_THRESHOLD:"
DISCARD_INSERT = """
                    # Camada 1: episodio autobiografico de descarte (bug cognitivo corrigido)
                    try:
                        from ultronpro import autobiographical_router as _abio
                        _abio.append_self_event(
                            kind='abstraction_discarded',
                            description=(
                                f"Abstracao '{target['name']}' descartada por falha sistematica apos {total} testes "
                                f"(taxa de confirmacao: {target['confirmation_rate']:.0%}, dominio: {target.get('domain')}). "
                                "Hipotese estava errada — sistema aprendeu com o erro."
                            ),
                            outcome='correction',
                            module='episodic_compiler',
                            importance=0.80,
                            extra={'abs_id': abs_id, 'name': target['name'],
                                   'confirmation_rate': target['confirmation_rate'],
                                   'domain': target.get('domain'), 'tests': total},
                        )
                    except Exception:
                        pass"""

# ── Patch 3: após hypothesis_revised workspace publish → adicionar autobio hook ──
REVISED_ANCHOR = "                    }, ensure_ascii=False),\n                    salience=0.8,\n                    ttl_sec=3600\n                )\n        except Exception:\n            pass"
REVISED_INSERT = """
                # Camada 1: episodio autobiografico de auto-correcao
                try:
                    from ultronpro import autobiographical_router as _abio
                    _abio.append_self_event(
                        kind='abstraction_revised',
                        description=(
                            f"Abstracao '{target['name']}' revisada pelo LLM (revisao #{target.get('revision_count')}) "
                            f"apos falha na taxa de confirmacao. Hipotese refinada com variavel oculta corrigida."
                        ),
                        outcome='correction',
                        module='episodic_compiler',
                        importance=0.75,
                        extra={'id': target['id'], 'name': target['name'],
                               'revision_count': target.get('revision_count')},
                    )
                except Exception:
                    pass"""

applied = 0

if SKILL_PROMOTED_ANCHOR in content:
    content = content.replace(SKILL_PROMOTED_ANCHOR, SKILL_PROMOTED_ANCHOR + SKILL_PROMOTED_INSERT, 1)
    applied += 1
    print("Patch 1 (skill_promoted): OK")
else:
    print("Patch 1 (skill_promoted): ANCHOR NOT FOUND")

if DISCARD_ANCHOR in content:
    content = content.replace(DISCARD_ANCHOR,
        DISCARD_ANCHOR.split("\n                elif")[0] + DISCARD_INSERT + "\n                elif" + DISCARD_ANCHOR.split("elif")[1],
        1)
    applied += 1
    print("Patch 2 (hypothesis_discarded): OK")
else:
    print("Patch 2 (hypothesis_discarded): ANCHOR NOT FOUND")
    # Try simplified anchor
    simple = "                        salience=0.7,\n                        ttl_sec=3600\n                    )"
    if simple in content:
        content = content.replace(simple, simple + DISCARD_INSERT.replace("'", "'"), 1)
        applied += 1
        print("Patch 2 (hypothesis_discarded): OK via simplified anchor")

if REVISED_ANCHOR in content:
    content = content.replace(REVISED_ANCHOR, REVISED_ANCHOR + REVISED_INSERT, 1)
    applied += 1
    print("Patch 3 (hypothesis_revised): OK")
else:
    print("Patch 3 (hypothesis_revised): ANCHOR NOT FOUND")

if applied > 0:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"\nSUCCESS: {applied}/3 patches applied to episodic_compiler.py")
else:
    print("\nFAILED: No patches applied")
