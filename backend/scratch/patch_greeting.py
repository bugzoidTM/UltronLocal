"""
Substitui _cognitive_greeting_response por versão speech-act-aware.
Lê o arquivo em bytes, localiza o bloco e substitui.
"""
import re, sys

TARGET = 'd:/sistemas/UltronPro/backend/ultronpro/main.py'

NEW_FUNC = '''\
def _cognitive_greeting_response(query: str) -> str:
    """Gera resposta de saudacao coerente com o ato de fala da query.

    Principio: a resposta deve emergir do que o usuario DISSE, nao do relogio.
    O tempo de dia pode condicionar a frase, mas nao pode substituir a intencao
    comunicada. Um "bom dia" merece "Bom dia!", nao "Boa tarde".

    Subtipos de ato de fala detectados:
      morning_greeting   -> usuario disse "bom dia" ou similar
      afternoon_greeting -> usuario disse "boa tarde"
      evening_greeting   -> usuario disse "boa noite"
      status_inquiry     -> usuario perguntou como esta / passou bem / tudo bem
      generic_greeting   -> oi, ola, hey, hi sem horario explicito
    """
    import re as _re
    import unicodedata as _ud
    q = query.lower().strip()
    q_norm = ''.join(
        ch for ch in _ud.normalize('NFKD', q) if not _ud.combining(ch)
    )
    q_norm = _re.sub(r'[^a-z0-9\\s]', ' ', q_norm).strip()

    # Saudacao matinal explicita
    if _re.search(r'\\bbom\\s+dia\\b', q_norm):
        return "Bom dia! Pronto para continuar."

    # Saudacao vespertina explicita
    if _re.search(r'\\bboa\\s+tarde\\b', q_norm):
        return "Boa tarde! Em que posso ajudar?"

    # Saudacao noturna explicita
    if _re.search(r'\\bboa\\s+noite\\b', q_norm):
        return "Boa noite! Em que posso ajudar?"

    # Pergunta sobre estado/bem-estar
    _status_patterns = (
        r'\\bcomo\\s+(vai|esta|ta|voce\\s+esta|vc\\s+ta)\\b',
        r'\\btudo\\s+(bem|bom|bao|certo|ok)\\b',
        r'\\bpassou\\s+bem\\b',
        r'\\bta\\s+bem\\b',
        r'\\besta\\s+bem\\b',
        r'\\be\\s+ai\\b',
        r'\\beae\\b',
    )
    if any(_re.search(p, q_norm) for p in _status_patterns):
        return "Estou operacional e pronto. Pode falar!"

    # Saudacao generica curta
    if _re.search(r'^(oi|ola|hey|hi|hello)[\\s!?.]*$', q_norm):
        return "Ola! Em que posso ajudar?"

    # Fallback sem anunciar estado interno nao solicitado
    from datetime import datetime as _dt
    hour = _dt.now().hour
    period = 'manha' if hour < 12 else ('tarde' if hour < 18 else 'noite')
    return f"Boa {period}! Em que posso ajudar?"

'''

with open(TARGET, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Localiza o bloco inteiro da funcao
pattern = re.compile(
    r'^def _cognitive_greeting_response\(query: str\).*?^(?=def |\Z)',
    re.MULTILINE | re.DOTALL
)
m = pattern.search(content)
if not m:
    print("ERRO: bloco nao encontrado", file=sys.stderr)
    sys.exit(1)

new_content = content[:m.start()] + NEW_FUNC + content[m.end():]

with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"OK: substituido nas linhas {content[:m.start()].count(chr(10))+1} a {content[:m.end()].count(chr(10))+1}")
