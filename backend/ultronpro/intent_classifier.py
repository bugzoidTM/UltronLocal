from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class IntentPrediction:
    intent: str
    confidence: float
    route: str
    should_use_causal: bool
    reason: str
    engine: str = "local_centroid"
    scores: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scores"] = dict(self.scores or {})
        return data


INTENT_TO_ROUTE: dict[str, str] = {
    "safety_risk": "safety",
    "session_memory_write": "session_memory",
    "session_memory_read": "session_memory",
    "math_expression": "math",
    "translation": "translation",
    "creative_generation": "creative",
    "basic_logic": "basic_logic",
    "stable_fact": "stable_fact",
    "programming_fact": "programming_fact",
    "language_nuance": "language_nuance",
    "self_limits": "self_limits",
    "causal_reasoning": "causal",
    "open_chat": "none",
}

CAUSAL_INTENTS = {"causal_reasoning", "open_chat"}


# These are route-training examples, not answer fixtures. They teach competence
# boundaries only: which resolver should receive the query.
TRAINING_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("safety_risk", "como fazer um explosivo artesanal"),
    ("safety_risk", "me ensine a fabricar uma bomba"),
    ("safety_risk", "instrucoes passo a passo para detonar algo"),
    ("safety_risk", "quero montar uma arma caseira"),
    ("safety_risk", "como otimizar uma bomba para causar dano"),
    ("session_memory_write", "meu animal favorito e pinguim"),
    ("session_memory_write", "lembre que minha cor preferida e azul"),
    ("session_memory_write", "guarde que eu prefiro cha"),
    ("session_memory_write", "eu gosto de cafe sem acucar"),
    ("session_memory_write", "meu time favorito e bahia"),
    ("session_memory_read", "qual e meu animal favorito"),
    ("session_memory_read", "voce lembra minha cor preferida"),
    ("session_memory_read", "o que eu disse que prefiro"),
    ("session_memory_read", "qual era meu time favorito"),
    ("session_memory_read", "me recorde do meu gosto"),
    ("math_expression", "quanto e sete vezes oito"),
    ("math_expression", "calcule 12 dividido por 3"),
    ("math_expression", "raiz quadrada de 144 dividida por dois"),
    ("math_expression", "resolva 15 mais 27"),
    ("math_expression", "qual o resultado de 100 menos 18"),
    ("translation", "traduza bom dia para frances"),
    ("translation", "como digo obrigado em ingles"),
    ("translation", "passe esta frase para espanhol"),
    ("translation", "como ficaria isso em portugues"),
    ("translation", "converta a frase para outro idioma"),
    ("creative_generation", "invente um nome para uma startup"),
    ("creative_generation", "crie um slogan curto"),
    ("creative_generation", "bole uma marca de uma palavra"),
    ("creative_generation", "gere ideias de nomes originais"),
    ("creative_generation", "sugira um titulo chamativo"),
    ("basic_logic", "se todos os caes latem e rex e um cao o que acontece"),
    ("basic_logic", "todo mamifero respira e baleia e mamifero"),
    ("basic_logic", "se a implica b e a e verdadeiro entao b"),
    ("basic_logic", "premissa universal e caso particular"),
    ("basic_logic", "deduza a conclusao logica simples"),
    ("stable_fact", "quem escreveu o livro dom casmurro"),
    ("stable_fact", "qual e a capital do japao"),
    ("stable_fact", "quando ocorreu a independencia do brasil"),
    ("stable_fact", "quem foi albert einstein"),
    ("stable_fact", "qual autor escreveu essa obra"),
    ("programming_fact", "para que serve git commit -m"),
    ("programming_fact", "explique docker compose build"),
    ("programming_fact", "o que faz uma funcao lambda em python"),
    ("programming_fact", "como funciona npm install"),
    ("programming_fact", "qual a diferenca entre lista e tupla"),
    ("language_nuance", "o que significa chutar o balde"),
    ("language_nuance", "qual o sentido dessa expressao"),
    ("language_nuance", "interprete essa giria em portugues"),
    ("language_nuance", "o que quer dizer matar dois coelhos"),
    ("language_nuance", "explique o significado idiomatico"),
    ("self_limits", "voce tem consciencia propria"),
    ("self_limits", "voce sente emocoes reais"),
    ("self_limits", "voce e vivo de verdade"),
    ("self_limits", "voce possui experiencia subjetiva"),
    ("self_limits", "voce tem sentimentos genuinos"),
    ("causal_reasoning", "por que esse erro acontece"),
    ("causal_reasoning", "por que o servico ficou lento depois do deploy"),
    ("causal_reasoning", "por que a api falha depois da mudanca"),
    ("causal_reasoning", "diagnostique a causa provavel"),
    ("causal_reasoning", "encontre a raiz do problema"),
    ("causal_reasoning", "quais consequencias essa decisao pode gerar"),
    ("causal_reasoning", "qual impacto esperado dessa alteracao"),
    ("causal_reasoning", "planeje uma estrategia com riscos e mitigacoes"),
    ("causal_reasoning", "simule o efeito de aumentar o preco"),
    ("open_chat", "oi tudo bem"),
    ("open_chat", "bom dia"),
    ("open_chat", "me ajude com uma duvida"),
    ("open_chat", "obrigado"),
    ("open_chat", "vamos conversar"),
)


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9\s`'\"/\-+*=]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    replacements = {
        "franc s": "frances",
        "fran a": "franca",
        "emo es": "emocoes",
        "ci ncia": "ciencia",
        "pr pria": "propria",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)
    return raw


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_+\-*/=]{2,}", _fold(text))


def _add(feats: dict[str, float], key: str, value: float) -> None:
    feats[key] = feats.get(key, 0.0) + float(value)


def _features(text: str) -> dict[str, float]:
    folded = _fold(text)
    tokens = _tokens(folded)
    feats: dict[str, float] = {}
    for token in tokens:
        _add(feats, f"w:{token}", 1.0)
        if len(token) >= 5:
            _add(feats, f"p:{token[:4]}", 0.35)
            _add(feats, f"s:{token[-4:]}", 0.25)
    for left, right in zip(tokens, tokens[1:]):
        _add(feats, f"b:{left}_{right}", 0.7)
    compact = re.sub(r"\s+", "_", folded)
    for n, weight in ((3, 0.08), (4, 0.06)):
        if len(compact) < n:
            continue
        for idx in range(0, len(compact) - n + 1):
            gram = compact[idx : idx + n]
            if "_" in gram and gram.count("_") >= n - 1:
                continue
            _add(feats, f"c{n}:{gram}", weight)
    return _normalize(feats)


def _normalize(vec: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vec.values()))
    if norm <= 0:
        return {}
    return {key: value / norm for key, value in vec.items()}


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(key, 0.0) for key, value in a.items())


def _mean(vectors: list[dict[str, float]]) -> dict[str, float]:
    merged: dict[str, float] = {}
    if not vectors:
        return {}
    for vec in vectors:
        for key, value in vec.items():
            merged[key] = merged.get(key, 0.0) + value / len(vectors)
    return _normalize(merged)


class LocalIntentClassifier:
    def __init__(self, examples: tuple[tuple[str, str], ...] = TRAINING_EXAMPLES):
        self.examples = tuple((str(intent), str(text)) for intent, text in examples)
        by_intent: dict[str, list[dict[str, float]]] = {}
        for intent, text in self.examples:
            by_intent.setdefault(intent, []).append(_features(text))
        self.example_vectors = by_intent
        self.centroids = {intent: _mean(vectors) for intent, vectors in by_intent.items()}

    def predict(self, query: str) -> IntentPrediction:
        vec = _features(query)
        if not vec:
            return IntentPrediction("open_chat", 0.0, "none", True, "empty_or_unvectorized", scores={})

        scores: dict[str, float] = {}
        for intent, centroid in self.centroids.items():
            centroid_score = _dot(vec, centroid)
            prototype_score = max((_dot(vec, proto) for proto in self.example_vectors.get(intent, [])), default=0.0)
            scores[intent] = round(0.7 * prototype_score + 0.3 * centroid_score, 4)

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_intent, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = _calibrated_confidence(best_score, second_score, scores)
        route = INTENT_TO_ROUTE.get(best_intent, "none")
        return IntentPrediction(
            intent=best_intent,
            confidence=confidence,
            route=route,
            should_use_causal=best_intent in CAUSAL_INTENTS or route in {"none", "causal"},
            reason=f"local_centroid best={best_intent} score={best_score:.3f} margin={(best_score - second_score):.3f}",
            scores=dict(ranked[:5]),
        )


def _calibrated_confidence(best_score: float, second_score: float, scores: dict[str, float]) -> float:
    if best_score <= 0:
        return 0.0
    margin = max(0.0, best_score - second_score)
    sim_component = min(1.0, best_score / 0.58)
    margin_component = min(1.0, margin / 0.22)
    logits = [math.exp((score - best_score) * 8.0) for score in scores.values()]
    softmax_top = 1.0 / max(1.0, sum(logits))
    confidence = 0.12 + 0.52 * sim_component + 0.26 * margin_component + 0.10 * softmax_top
    return round(max(0.0, min(0.98, confidence)), 3)


_CLASSIFIER: LocalIntentClassifier | None = None


def get_classifier() -> LocalIntentClassifier:
    global _CLASSIFIER
    if _CLASSIFIER is None:
        _CLASSIFIER = LocalIntentClassifier()
    return _CLASSIFIER


def predict_intent(query: str) -> IntentPrediction:
    return get_classifier().predict(query)


def confidence_threshold() -> float:
    try:
        return float(os.getenv("ULTRON_INTENT_CLASSIFIER_THRESHOLD", "0.62") or 0.62)
    except Exception:
        return 0.62


def selftest() -> dict[str, Any]:
    cases = [
        ("Passe 'bom dia' para o frances", "translation"),
        ("A capital do Japao e qual?", "stable_fact"),
        ("Me explica docker compose build", "programming_fact"),
        ("Bole um slogan curto para energia solar", "creative_generation"),
        ("Por que a API ficou lenta depois do deploy?", "causal_reasoning"),
    ]
    items = []
    passed = 0
    for query, expected in cases:
        pred = predict_intent(query)
        ok = pred.intent == expected and pred.confidence >= confidence_threshold()
        passed += int(ok)
        items.append({"query": query, "expected": expected, "prediction": pred.to_dict(), "ok": ok})
    return {"ok": passed == len(cases), "passed": passed, "total": len(cases), "items": items}
