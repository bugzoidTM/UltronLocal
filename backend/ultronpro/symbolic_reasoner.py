from __future__ import annotations

import math
import re
from typing import Any

from ultronpro import llm

try:
    import sympy as sp
except Exception:  # pragma: no cover
    sp = None


_ROUTE_PATTERNS = [
    # Lógica
    r"\b(lógica|logica|deduza|infer[a-z]*|premissa|conclus[aã]o|implica|verdadeiro\s+ou\s+falso|todos\s+os)\b",
    r"\b(se\b.*\bent[aã]o\b|afirma[cç][aã]o\s+do\s+consequente|próximo\s+número|proximo\s+numero|sequ[eê]ncia)\b",
    # Matemática
    r"\b(matem[aá]tica|equa[cç][aã]o|derivad[a-z]*|integral|probabilidade|teorema|hipotenusa|cateto|raiz\s+quadrada|tri[aâ]ngulo|ret[aâ]ngulo|porcentagem|percentual|quantos\s+segundos|c[aá]lculo|calculo|quantos)\b",
    r"\b(resolva|resolver|calcule|simplifique|fatore|isole\s+[a-z])\b",
    # Planejamento
    r"\b(plano|planejamento|cronograma|prioridade|roadmap|milestone|etapas|checklist|migra[cç][aã]o|plano\s+de\s+estudos|framework|passos\s+para|zero\s+downtime)\b",
    # Programação
    r"\b(c[oó]digo|programa[cç][aã]o|algoritmo|python|docker|dockerfile|loop|fun[cç][aã]o\s+python|diferen[cç]a\s+entre|como\s+fa[cç]o\s+em\s+(python|docker)|deadlock|debug|refator[a-z]*|complexidade)\b",
    r"(?:\d+[a-z]?\s*[+\-*/^]\s*\d+[a-z]?\s*=\s*\d+)",
    r"x\s*[\^²]\s*2|equa[cç][aã]o\s+do\s+2[ºo]?\s+grau|=\s*0",
]

_PLACEHOLDERS = [
    "resposta clara, curta e objetiva",
    "pergunta objetiva",
    "pesquisa curta e objetiva",
    "resposta objetiva clara e curta",
    "resposta clara, curta e cordial",
]


def should_route(question: str) -> bool:
    q = str(question or '').strip().lower()
    if not q:
        return False
    for p in _ROUTE_PATTERNS:
        if re.search(p, q):
            return True
    return False


def _useful_len(s: str) -> int:
    return len(re.sub(r"\s+", " ", str(s or "").strip()))


def _is_placeholder(s: str) -> bool:
    sl = str(s or '').strip().lower()
    return any(p in sl for p in _PLACEHOLDERS)


def _valid_answer(s: str) -> bool:
    if not s:
        return False
    if _useful_len(s) < 30:
        return False
    if _is_placeholder(s):
        return False
    return True


def _fmt_steps(title: str, steps: list[str], final: str, limits: str = "Sem limitações relevantes para este cálculo.") -> str:
    body = "\n".join(f"- {x}" for x in steps)
    return (
        f"1) Diagnóstico do problema\n{title}\n\n"
        f"2) Passos de raciocínio\n{body}\n\n"
        f"3) Resposta final objetiva\n{final}\n\n"
        f"4) Limites/assunções\n{limits}"
    )


def _solve_sqrt(q: str) -> str | None:
    m = re.search(r"raiz\s+quadrada\s+de\s+(-?\d+(?:[\.,]\d+)?)", q, flags=re.I)
    if not m:
        return None
    n = float(m.group(1).replace(',', '.'))
    if n < 0:
        return _fmt_steps(
            "Cálculo de raiz quadrada em número negativo.",
            ["No conjunto dos reais, não existe raiz quadrada de número negativo."],
            "Sem solução real (apenas solução complexa).",
            "Assumindo domínio dos números reais.",
        )
    r = math.sqrt(n)
    rs = str(int(r)) if abs(r - int(r)) < 1e-12 else f"{r:.6g}"
    return _fmt_steps(
        "Cálculo direto da raiz quadrada.",
        [f"Identificar o número: {n:g}.", "Aplicar operação √n."],
        f"A raiz quadrada de {n:g} é {rs}.",
    )


def _solve_percent(q: str) -> str | None:
    m = re.search(r"(\d+(?:[\.,]\d+)?)\s*%\s+de\s+(\d+(?:[\.,]\d+)?)", q, flags=re.I)
    if not m:
        return None
    p = float(m.group(1).replace(',', '.'))
    v = float(m.group(2).replace(',', '.'))
    out = (p / 100.0) * v
    os = str(int(out)) if abs(out - int(out)) < 1e-12 else f"{out:.6g}"
    return _fmt_steps(
        "Cálculo de porcentagem.",
        [f"Converter {p:g}% para decimal: {p/100:g}.", f"Multiplicar por {v:g}."],
        f"{p:g}% de {v:g} = {os}.",
    )


def _solve_quadratic(q: str) -> str | None:
    if sp is None:
        return None
    qn = q.replace('−', '-').replace('–', '-').replace('x²', 'x^2')
    m = re.search(r"([+-]?\d*)\s*x\^2\s*([+-]\s*\d+)\s*x\s*([+-]\s*\d+)\s*=\s*0", qn, flags=re.I)
    if not m:
        return None
    a_raw = m.group(1).replace(' ', '')
    if a_raw in ('', '+'):
        a = 1
    elif a_raw == '-':
        a = -1
    else:
        a = int(a_raw)
    b = int(m.group(2).replace(' ', ''))
    c = int(m.group(3).replace(' ', ''))
    x = sp.symbols('x')
    sols = sp.solve(sp.Eq(a * x**2 + b * x + c, 0), x)
    sols_s = [str(sp.nsimplify(s)) for s in sols]
    return _fmt_steps(
        "Equação do 2º grau com solução determinística.",
        [f"Identificar coeficientes: a={a}, b={b}, c={c}.", "Resolver a*x² + b*x + c = 0 via SymPy."],
        f"As soluções são: x = {', '.join(sols_s)}.",
    )


def _solve_sequence(q: str) -> str | None:
    if 'próximo número' not in q.lower() and 'proximo número' not in q.lower() and 'próximo numero' not in q.lower():
        return None
    nums = [int(n) for n in re.findall(r"-?\d+", q)]
    if len(nums) < 4:
        return None
    d1 = [b - a for a, b in zip(nums, nums[1:])]
    d2 = [b - a for a, b in zip(d1, d1[1:])]
    if d2 and all(x == d2[0] for x in d2):
        next_d1 = d1[-1] + d2[0]
        nxt = nums[-1] + next_d1
        return _fmt_steps(
            "Detecção de padrão por diferenças sucessivas.",
            [f"Sequência: {nums}.", f"1ª diferença: {d1}.", f"2ª diferença constante: {d2[0]}."],
            f"Próximo número: {nxt}.",
        )
    return None


def _solve_deterministic(question: str) -> str | None:
    for fn in (_solve_sqrt, _solve_quadratic, _solve_percent, _solve_sequence):
        ans = fn(question)
        if ans:
            return ans
    return None


def solve(question: str, context: str = '') -> dict[str, Any]:
    q = str(question or '').strip()
    c = str(context or '').strip()
    if not q:
        return {'ok': False, 'error': 'empty_question'}

    det = _solve_deterministic(q)
    if det and _valid_answer(det):
        return {
            'ok': True,
            'answer': det,
            'module': 'symbolic_reasoner',
            'routed': True,
            'strategy_used': 'deterministic',
        }

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
            if _valid_answer(ans):
                return {
                    'ok': True,
                    'answer': ans,
                    'module': 'symbolic_reasoner',
                    'routed': True,
                    'strategy_used': st,
                }
            last_err = 'invalid_or_placeholder_answer'
        except Exception as e:
            last_err = str(e)[:220]
            continue

    return {'ok': False, 'error': last_err or 'empty_answer', 'module': 'symbolic_reasoner', 'routed': True}
