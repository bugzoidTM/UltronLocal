from __future__ import annotations

import re
from typing import Any

from ultronpro import llm


_ROUTE_PATTERNS = [
    r"\b(lógica|logica|deduza|infer[a-z]*|premissa|conclus[aã]o)\b",
    r"\b(matem[aá]tica|equa[cç][aã]o|derivad[a-z]*|integral|probabilidade|teorema|hipotenusa|cateto|raiz quadrada)\b",
    r"\b(resolva|resolver|calcule|simplifique|fatore|isole\s+[a-z])\b",
    r"\b(plano|planejamento|cronograma|prioridade|roadmap|milestone|etapas)\b",
    r"\b(c[oó]digo|programa[cç][aã]o|algoritmo|python|bug|debug|refator[a-z]*|complexidade)\b",
    r"(?:\d+[a-z]?\s*[+\-*/^]\s*\d+[a-z]?\s*=\s*\d+)",
]


def should_route(question: str) -> bool:
    q = str(question or '').strip().lower()
    if not q:
        return False
    for p in _ROUTE_PATTERNS:
        if re.search(p, q):
            return True
    return False


def solve(question: str, context: str = '') -> dict[str, Any]:
    q = str(question or '').strip()
    c = str(context or '').strip()
    if not q:
        return {'ok': False, 'error': 'empty_question'}

    prompt = (
        "Tarefa: resolver com raciocínio estruturado (lógica/matemática/planejamento/programação) sem inventar fatos.\n"
        f"Pergunta: {q}\n"
        f"Contexto opcional: {c or '(nenhum)'}\n\n"
        "Produza resposta em português no formato:\n"
        "1) Diagnóstico do problema\n"
        "2) Passos de raciocínio (curtos e verificáveis)\n"
        "3) Resposta final objetiva\n"
        "4) Limites/assunções (se houver incerteza)\n"
        "Se faltarem dados, diga explicitamente e proponha o próximo dado necessário."
    )

    strategies = ('reasoning', 'default', 'cheap')
    last_err = ''
    for st in strategies:
        try:
            ans = llm.complete(
                prompt,
                strategy=st,
                system='Você é um resolvedor simbólico rigoroso. Clareza, verificabilidade e sem alucinação.',
                json_mode=False,
                inject_persona=False,
                max_tokens=260,
                cloud_fallback=True,
            )
            ans = str(ans or '').strip()
            if ans:
                return {
                    'ok': True,
                    'answer': ans,
                    'module': 'symbolic_reasoner',
                    'routed': True,
                    'strategy_used': st,
                }
        except Exception as e:
            last_err = str(e)[:220]
            continue

    return {'ok': False, 'error': last_err or 'empty_answer', 'module': 'symbolic_reasoner', 'routed': True}
