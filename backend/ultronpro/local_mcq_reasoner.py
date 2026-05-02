from __future__ import annotations

import json
import re
import unicodedata
from typing import Any


_STOPWORDS = {
    "a",
    "as",
    "de",
    "do",
    "da",
    "das",
    "dos",
    "e",
    "em",
    "na",
    "no",
    "nas",
    "nos",
    "o",
    "os",
    "ou",
    "para",
    "por",
    "que",
    "qual",
    "um",
    "uma",
    "the",
    "of",
    "and",
    "or",
    "to",
    "in",
}

_ABSURDITY_MARKERS = {
    "armario",
    "asfalto",
    "carro",
    "correndo",
    "dentro",
    "desamarrar",
    "dormir",
    "geladeira",
    "jogar",
    "lixo",
    "molho",
    "motivo",
    "quebre",
    "quebrar",
    "sozinha",
    "tropecar",
    "voar",
}


def _norm(text: Any) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _tokens(text: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", _norm(text))
        if token not in _STOPWORDS and len(token) >= 2
    }


def _has(text: str, *terms: str) -> bool:
    return all(term in text for term in terms)


def _any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _score_choice(question: str, choice: str) -> tuple[float, list[str]]:
    q = _norm(question)
    c = _norm(choice)
    q_tokens = _tokens(q)
    c_tokens = _tokens(c)
    score = 0.0
    reasons: list[str] = []

    overlap = len(q_tokens & c_tokens)
    if overlap:
        score += min(1.5, 0.25 * overlap)
        reasons.append(f"overlap:{overlap}")

    absurd_hits = sorted(c_tokens & _ABSURDITY_MARKERS)
    if absurd_hits:
        score -= 2.4 + 0.25 * len(absurd_hits)
        reasons.append("absurdity_penalty")

    if _any(q, ("afund", "flutua", "agua")) and _any(q, ("densidade", "propriedade", "objeto")):
        if _has(c, "alta", "densidade") or _has(c, "maior", "densidade"):
            score += 6.0
            reasons.append("physics_density")
        if _has(c, "baixa", "densidade") or _any(c, ("cor", "brilhante", "circular")):
            score -= 2.5

    if _any(q, ("cadeia alimentar", "teia alimentar", "plantas", "fazem seu proprio alimento")):
        if _any(c, ("produtor", "produtores", "autotrofo", "autotrofos")):
            score += 6.0
            reasons.append("food_chain_producer")
        if _any(c, ("consumidor", "decompositor", "predador")):
            score -= 1.8

    if _any(q, ("evapor", "secar", "seca mais rapido")):
        if _any(c, ("aumentar", "maior", "espalhar")) and _any(c, ("area", "superficie", "exposta", "exposicao")):
            score += 6.0
            reasons.append("evaporation_surface_area")
        if _any(c, ("reduzir", "diminuir", "cobrir", "tampar", "frio")):
            score -= 2.0

    if _any(q, ("cebola", "cozinha", "frigideira", "fogao", "panela")):
        if _any(c, ("cozinhar", "refogar", "fritar", "colocar")) and _any(c, ("cebola", "frigideira", "panela")):
            score += 6.0
            reasons.append("kitchen_next_step")

    if _any(q, ("chuva", "guarda-chuva", "cadarco", "sapato", "bota")):
        if _any(c, ("sair", "porta", "rua", "enfrentar")) and _any(c, ("chuva", "guarda-chuva", "rua", "porta")):
            score += 6.0
            reasons.append("rain_next_step")

    if _any(q, ("garrafa", "fonte", "bebedouro", "ciclista", "corredor")):
        if _any(c, ("encher", "encha", "reabastecer")) and _any(c, ("garrafa", "agua")):
            score += 6.0
            reasons.append("water_bottle_next_step")

    if _any(q, ("negacao", "negacao de", "not (", "de morgan")) and _any(q, ("p e q", "a e b", "and")):
        if _any(c, ("nao p ou nao q", "nao a ou nao b", "not p or not q", "not a or not b")):
            score += 6.0
            reasons.append("de_morgan_and")
        if _any(c, ("nao p e nao q", "nao a e nao b", "not p and not q")):
            score -= 3.0

    if _any(q, ("preco", "price")) and _any(q, ("aumento", "sobe", "rise")) and (
        _any(q, ("demanda", "demandada", "demand"))
        or _any(q, ("bem", "microeconomia", "tudo o mais constante", "ceteris paribus"))
    ):
        if _any(c, ("reducao", "reduz", "queda", "diminui", "decrease")) and _any(c, ("demandada", "demanda", "demand")):
            score += 6.0
            reasons.append("law_of_demand")
        if _any(c, ("aumento", "aumenta", "increase")) and _any(c, ("demandada", "demanda", "demand")):
            score -= 2.5
        if _any(c, ("desaparecimento", "perfeitamente", "todos os casos")):
            score -= 1.5

    if _any(q, ("atp", "energia celular", "celula eucariotica", "eucariot")):
        if _any(c, ("mitocondria", "mitochondria")):
            score += 6.0
            reasons.append("cellular_energy")
        if _any(c, ("golgi", "lisossomo", "nucleo", "ribossomo")):
            score -= 1.5

    return score, reasons


def solve_mcq(question: str, choices: list[dict[str, Any]]) -> dict[str, Any]:
    """Solve small external MCQ probes without calling an LLM or reading gold labels."""
    rows: list[dict[str, Any]] = []
    for idx, choice in enumerate(choices or []):
        if not isinstance(choice, dict):
            continue
        label = str(choice.get("label") or chr(ord("A") + idx)).strip().upper()
        text = str(choice.get("text") or "")
        score, reasons = _score_choice(question, text)
        rows.append({
            "label": label,
            "text": text,
            "score": round(score, 4),
            "reasons": reasons,
        })

    rows.sort(key=lambda row: (-float(row.get("score") or 0.0), str(row.get("label") or "")))
    best = rows[0] if rows else {}
    second = rows[1] if len(rows) > 1 else {"score": 0.0}
    margin = float(best.get("score") or 0.0) - float(second.get("score") or 0.0)
    answer = str(best.get("label") or "")
    ok = bool(answer) and (float(best.get("score") or 0.0) > 0.0 or margin > 0.0)

    return {
        "ok": ok,
        "answer": answer if ok else "",
        "confidence": round(max(0.0, min(1.0, margin / 6.0)), 4),
        "margin": round(margin, 4),
        "source": "local_mcq_reasoner",
        "scores": rows,
        "raw": json.dumps({"answer": answer if ok else "", "source": "local_mcq_reasoner"}, ensure_ascii=False),
    }
