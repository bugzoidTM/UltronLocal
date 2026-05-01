"""Semantic and structural intent routing helpers.

This module intentionally avoids cataloguing full user utterances. It classifies
autobiographical questions with two signals:

1. Semantic similarity between the query and intent profiles, using the existing
   embeddings stack when available.
2. Structural features: second-person/system-directed reference plus semantic
   role classes such as origin, capability, state, history, and mission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import os
import re
import unicodedata
from typing import Any


AUTOBIOGRAPHICAL_LABEL = "autobiographical"
EXTERNAL_FACTUAL_LABEL = "external_factual"


@dataclass(frozen=True)
class IntentDecision:
    label: str
    category: str
    confidence: float
    method: str
    semantic_score: float = 0.0
    structural_score: float = 0.0
    margin: float = 0.0
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CATEGORY_PROFILES: dict[str, str] = {
    "identity": (
        "Autobiographical self-reference: the user asks the assistant what it is, "
        "its name, nature, self-model, identity, age, or personal metadata. "
        "Pergunta autobiografica sobre identidade, nome, natureza ou metadados do proprio sistema."
    ),
    "creation": (
        "Autobiographical origin and provenance: the user asks the assistant where it came from, "
        "how it was authored, built, developed, trained, designed, or brought into existence. "
        "Pergunta autobiografica sobre origem, autoria, construcao, desenvolvimento ou proveniencia."
    ),
    "capability": (
        "Autobiographical capability and limitation: the user asks what the assistant can do, "
        "what it knows, its tools, limits, skills, competencies, runtime models, LLM providers, "
        "or operational abilities. Pergunta sobre capacidades, limites, ferramentas, modelos, "
        "LLMs, provedores e competencias do proprio sistema."
    ),
    "state": (
        "Autobiographical internal state: the user asks how the assistant is doing, feeling, "
        "running, its health, mood, homeostasis, current activity, or operational status. "
        "Pergunta sobre estado interno, saude, execucao, humor ou atividade atual."
    ),
    "history": (
        "Autobiographical memory and trajectory: the user asks what the assistant remembers, "
        "learned, did, became, changed, fixed, experienced, or recorded in its own episodes. "
        "Pergunta sobre memoria, trajetoria, aprendizado, episodios, mudancas ou historico proprio."
    ),
    "mission": (
        "Autobiographical mission and purpose: the user asks why the assistant exists, "
        "its purpose, goals, objective, mission, values, direction, or reason for being. "
        "Pergunta sobre missao, objetivo, proposito, metas ou razao de ser do proprio sistema."
    ),
}


_NEGATIVE_PROFILES: tuple[str, ...] = (
    "External factual question about another person, company, product, place, law, event, or public fact.",
    "Task request asking the assistant to write, edit, create, debug, search, calculate, or operate on user content.",
    "General conversation that is not about the assistant's own identity, memory, origin, state, or capabilities.",
)


_SELF_REFERENCE_TOKENS = frozenset(
    {
        "voce",
        "voces",
        "vc",
        "vcs",
        "tu",
        "te",
        "ti",
        "contigo",
        "seu",
        "sua",
        "seus",
        "suas",
        "teu",
        "tua",
        "teus",
        "tuas",
        "your",
        "yours",
        "yourself",
        "you",
        "assistant",
        "assistente",
        "ultronpro",
    }
)

_QUESTION_TOKENS = frozenset(
    {
        "quem",
        "qual",
        "quais",
        "quando",
        "onde",
        "como",
        "por",
        "porque",
        "what",
        "who",
        "when",
        "where",
        "how",
        "why",
        "which",
    }
)

_CURRENT_FACT_TOKENS = frozenset(
    {
        "atual",
        "atuais",
        "hoje",
        "agora",
        "recent",
        "latest",
        "current",
        "today",
        "now",
    }
)

_EXTERNAL_FACT_STEMS: tuple[str, ...] = (
    "president",
    "govern",
    "prefeit",
    "minist",
    "senador",
    "deputad",
    "chanceler",
    "premier",
    "prime",
    "ceo",
    "cfo",
    "cto",
    "diretor",
    "fundador",
    "lider",
    "capital",
    "popul",
    "cotac",
    "preco",
    "valor",
    "temperatura",
    "clima",
    "tempo",
    "placar",
    "resultado",
    "ranking",
    "notic",
    "lei",
    "regul",
    "evento",
    "eleic",
    "mandat",
    "nasc",
    "morre",
    "data",
    "versao",
    "lanc",
)

_EXTERNAL_LOOKUP_VERBS = frozenset(
    {
        "pesquise",
        "pesquisar",
        "procure",
        "procurar",
        "busque",
        "buscar",
        "consulte",
        "consultar",
        "verifique",
        "verificar",
        "search",
        "lookup",
        "find",
        "check",
    }
)

_INTERNAL_ENTITY_TOKENS = frozenset(
    {
        "sistema",
        "ultronpro",
        "assistente",
        "assistant",
        "nucleo",
        "grafo",
        "memoria",
        "skill",
        "pipeline",
        "workspace",
    "runtime",
    "modelo",
    "model",
    "llm",
    "provider",
    "provedor",
    "roteador",
    "router",
    }
)

_INTERNAL_CAUSAL_OR_SYSTEM_STEMS: tuple[str, ...] = (
    "causal",
    "grafo",
    "nucleo",
    "threshold",
    "risco",
    "execut",
    "comando",
    "bug",
    "debug",
    "falha",
    "erro",
    "consequ",
    "simul",
    "aconteceria",
    "decis",
)

_OPINION_STEMS: tuple[str, ...] = (
    "opinia",
    "acha",
    "pensa",
    "perspect",
    "avali",
    "opinion",
)

_EXTERNAL_RELATION_PATTERN = re.compile(
    r"\b(?:"
    r"president[a-z0-9_]*|governador[a-z0-9_]*|prefeit[a-z0-9_]*|"
    r"minist[a-z0-9_]*|senador[a-z0-9_]*|deputad[a-z0-9_]*|"
    r"chanceler[a-z0-9_]*|premier|primeiro|ministra?|ceo|cfo|cto|"
    r"diretor[a-z0-9_]*|fundador[a-z0-9_]*|lider[a-z0-9_]*|"
    r"capital|populacao|cotacao|preco|valor|temperatura|clima|"
    r"placar|resultado|ranking|noticia[a-z0-9_]*|lei|regulacao|"
    r"evento[a-z0-9_]*|eleicao[a-z0-9_]*|mandato|data|versao|lancamento"
    r")\s+(?:de|do|da|dos|das|em|no|na|nos|nas)\s+[a-z0-9_]{3,}"
)

_CATEGORY_STEMS: dict[str, tuple[str, ...]] = {
    "identity": (
        "ident",
        "nome",
        "nature",
        "name",
        "idade",
        "anos",
        "age",
        "born",
        "metadata",
        "self",
        "agi",
        "ia",
        "intelig",
        "intelligence",
        "artificial",
    ),
    "creation": (
        "orig",
        "proven",
        "autoria",
        "autor",
        "cria",
        "criad",
        "criador",
        "feito",
        "fez",
        "faz",
        "desenvolv",
        "constru",
        "program",
        "projet",
        "trein",
        "mont",
        "surg",
        "veio",
        "ven",
        "made",
        "creat",
        "built",
        "build",
        "develop",
        "design",
        "train",
        "origin",
        "nasc",
        "came",
        "from",
        "maker",
        "author",
        "creator",
    ),
    "capability": (
        "capab",
        "capac",
        "habil",
        "compet",
        "skill",
        "ferrament",
        "tool",
        "limita",
        "limit",
        "can",
        "sabe",
        "know",
        "pode",
        "consegue",
        "able",
        "usa",
        "uso",
        "utiliza",
        "modelo",
        "model",
        "llm",
        "provider",
        "provedor",
        "nuvem",
        "cloud",
        "local",
        "arquitet",
        "config",
        "runtime",
    ),
    "state": (
        "estado",
        "status",
        "saude",
        "health",
        "sente",
        "sent",
        "feel",
        "feeling",
        "humor",
        "mood",
        "homeostas",
        "running",
        "execut",
        "fazendo",
        "doing",
    ),
    "history": (
        "memori",
        "remember",
        "lembra",
        "aprend",
        "learn",
        "hist",
        "trajet",
        "episod",
        "torn",
        "became",
        "change",
        "mud",
        "corrig",
        "fix",
        "bench",
        "digest",
        "passado",
        "past",
        "ontem",
        "yesterday",
        "hoje",
        "today",
    ),
    "mission": (
        "miss",
        "objet",
        "goal",
        "meta",
        "purpose",
        "proposit",
        "serve",
        "existe",
        "exist",
        "direcao",
        "direction",
        "valor",
        "value",
    ),
}


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9_]+", normalize_text(text)))


def _near_token(token: str, references: frozenset[str]) -> bool:
    if token in references:
        return True
    if len(token) < 3:
        return False
    for ref in references:
        if len(ref) < 3:
            continue
        if abs(len(token) - len(ref)) > 1:
            continue
        if _edit_distance_at_most_one(token, ref):
            return True
    return False


@lru_cache(maxsize=8192)
def _edit_distance_at_most_one(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(1 for a, b in zip(left, right) if a != b) <= 1
    if len(left) > len(right):
        left, right = right, left
    i = j = edits = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        j += 1
    return True


def _stem_hits(tokens: tuple[str, ...], stems: tuple[str, ...]) -> tuple[str, ...]:
    hits: list[str] = []
    for token in tokens:
        for stem in stems:
            if token.startswith(stem):
                hits.append(stem)
                break
            if len(token) >= 4 and len(stem) >= 4 and _edit_distance_at_most_one(token[: len(stem)], stem):
                hits.append(stem)
                break
    return tuple(sorted(set(hits)))


def _proper_entity_hits(query: str) -> tuple[str, ...]:
    """Lightweight signal for named real-world entities without storing facts."""
    raw_words = re.findall(r"\b[^\W\d_][\w.-]*\b", str(query or ""), flags=re.UNICODE)
    hits: list[str] = []
    ignored = _QUESTION_TOKENS | _SELF_REFERENCE_TOKENS | {"eu", "me", "meu", "minha"}
    for idx, word in enumerate(raw_words):
        norm = normalize_text(word).strip("._-")
        if not norm or norm in ignored:
            continue
        if idx == 0 and norm in _QUESTION_TOKENS:
            continue
        if word[:1].isupper() or (len(word) > 1 and word.isupper()):
            hits.append(norm)
    return tuple(sorted(set(hits))[:6])


def classify_external_factual_intent(query: str, *, threshold: float | None = None) -> IntentDecision:
    """Classify lookups about external world facts that should use web/RAG.

    This intentionally detects the *shape* of the question, not the answer:
    public roles, current-state markers, named entities, and factual relations.
    """
    if threshold is None:
        threshold = float(os.getenv("ULTRON_EXTERNAL_FACTUAL_THRESHOLD", "0.55") or 0.55)

    text = str(query or "").strip()
    tokens = _tokens(text)
    token_set = set(tokens)
    if not tokens:
        return IntentDecision(
            label="general",
            category="none",
            confidence=0.0,
            method="empty_query",
        )

    question_hits = tuple(t for t in tokens if t in _QUESTION_TOKENS)
    lookup_hits = tuple(t for t in tokens if t in _EXTERNAL_LOOKUP_VERBS)
    current_hits = tuple(t for t in tokens if t in _CURRENT_FACT_TOKENS)
    fact_hits = _stem_hits(tokens, _EXTERNAL_FACT_STEMS)
    internal_hits = _stem_hits(tokens, _INTERNAL_CAUSAL_OR_SYSTEM_STEMS)
    opinion_hits = _stem_hits(tokens, _OPINION_STEMS)
    proper_hits = _proper_entity_hits(text)
    relation_hit = bool(_EXTERNAL_RELATION_PATTERN.search(normalize_text(text)))
    question_shape = bool("?" in text or question_hits)
    self_hits = tuple(t for t in tokens if _near_token(t, _SELF_REFERENCE_TOKENS))

    self_metadata_hits = _stem_hits(
        tokens,
        (
            "nasc",
            "born",
            "birth",
            "orig",
            "criad",
            "criador",
            "creator",
            "autor",
            "ident",
            "nome",
            "llm",
            "model",
            "modelo",
            "provider",
            "provedor",
        ),
    )
    if self_hits and self_metadata_hits and not proper_hits and not lookup_hits:
        return IntentDecision(
            label="general",
            category="none",
            confidence=0.0,
            method="self_metadata_query",
            signals=tuple(
                sorted(
                    {
                        *(f"self:{hit}" for hit in self_hits[:3]),
                        *(f"self_metadata:{hit}" for hit in self_metadata_hits[:4]),
                    }
                )
            ),
        )

    if opinion_hits and not lookup_hits:
        return IntentDecision(
            label="general",
            category="none",
            confidence=0.0,
            method="opinion_request_not_factual_lookup",
            signals=tuple(f"opinion:{hit}" for hit in opinion_hits[:4]),
        )

    internal_entity_hits = token_set & _INTERNAL_ENTITY_TOKENS
    if internal_entity_hits and not lookup_hits:
        return IntentDecision(
            label="general",
            category="none",
            confidence=0.0,
            method="internal_entity_query",
            signals=tuple(f"internal_entity:{hit}" for hit in sorted(internal_entity_hits)[:4]),
        )

    # Internal causal/operational questions belong to the structured core unless
    # they also contain a clear external factual relation.
    if internal_hits and not relation_hit and not proper_hits and not lookup_hits:
        return IntentDecision(
            label="general",
            category="none",
            confidence=0.0,
            method="internal_causal_or_system_query",
            signals=tuple(f"internal:{hit}" for hit in internal_hits[:4]),
        )

    entity_signal = relation_hit or bool(proper_hits) or bool(current_hits)
    fact_signal = bool(fact_hits) or bool(current_hits) or bool(lookup_hits)
    if not (question_shape or lookup_hits) or not (entity_signal and fact_signal):
        signals = tuple(
            sorted(
                {
                    *(f"question:{hit}" for hit in question_hits[:2]),
                    *(f"lookup:{hit}" for hit in lookup_hits[:2]),
                    *(f"fact:{hit}" for hit in fact_hits[:3]),
                    *(f"entity:{hit}" for hit in proper_hits[:3]),
                    *(f"current:{hit}" for hit in current_hits[:2]),
                }
            )
        )
        return IntentDecision(
            label="general",
            category="none",
            confidence=0.0,
            method="no_external_factual_shape",
            signals=signals,
        )

    score = 0.0
    if question_shape:
        score += 0.22
    if lookup_hits:
        score += 0.24
    if fact_hits:
        score += min(0.30, 0.16 + 0.05 * len(fact_hits))
    if relation_hit:
        score += 0.30
    elif proper_hits:
        score += 0.20
    if current_hits:
        score += 0.12
    score = round(min(1.0, score), 3)

    signals = tuple(
        sorted(
            {
                *(f"question:{hit}" for hit in question_hits[:2]),
                *(f"lookup:{hit}" for hit in lookup_hits[:2]),
                *(f"fact:{hit}" for hit in fact_hits[:4]),
                *(f"entity:{hit}" for hit in proper_hits[:4]),
                *(["relation:external_entity"] if relation_hit else []),
                *(f"current:{hit}" for hit in current_hits[:2]),
            }
        )
    )
    if score >= threshold:
        category = "current_world_fact" if current_hits else "external_entity_lookup"
        return IntentDecision(
            label=EXTERNAL_FACTUAL_LABEL,
            category=category,
            confidence=score,
            method="structural_external_factual",
            structural_score=score,
            signals=signals,
        )

    return IntentDecision(
        label="general",
        category="none",
        confidence=score,
        method="external_factual_below_threshold",
        structural_score=score,
        signals=signals,
    )


def _structural_decision(query: str) -> tuple[str, float, tuple[str, ...]]:
    tokens = _tokens(query)
    if not tokens:
        return "none", 0.0, ()

    self_hits = tuple(t for t in tokens if _near_token(t, _SELF_REFERENCE_TOKENS))
    question_hits = tuple(t for t in tokens if t in _QUESTION_TOKENS)

    category_scores: dict[str, tuple[float, tuple[str, ...]]] = {}
    for category, stems in _CATEGORY_STEMS.items():
        hits = _stem_hits(tokens, stems)
        category_scores[category] = (min(1.0, len(hits) / 2.0), hits)

    best_category, (best_category_score, best_hits) = max(
        category_scores.items(),
        key=lambda item: item[1][0],
    )

    birth_hits = _stem_hits(tokens, ("nasc", "born", "birth"))
    if self_hits and birth_hits and ("?" in str(query or "") or question_hits):
        best_category = "creation"
        best_category_score = max(best_category_score, 0.88)
        best_hits = tuple(sorted(set(best_hits + birth_hits)))

    creator_hits = _stem_hits(tokens, ("criad", "criador", "creator", "maker", "autor", "author", "desenvolv"))
    if self_hits and creator_hits and ("?" in str(query or "") or question_hits or any(t in {"quem", "who", "nome"} for t in tokens)):
        best_category = "creation"
        best_category_score = max(best_category_score, 0.88)
        best_hits = tuple(sorted(set(best_hits + creator_hits)))

    model_runtime_hits = _stem_hits(tokens, ("llm", "model", "modelo", "provider", "provedor", "usa", "utiliza", "runtime"))
    if self_hits and model_runtime_hits and ("?" in str(query or "") or question_hits):
        best_category = "capability"
        best_category_score = max(best_category_score, 0.88)
        best_hits = tuple(sorted(set(best_hits + model_runtime_hits)))

    agi_identity_hits = _stem_hits(tokens, ("agi", "ia", "intelig", "intelligence", "artificial"))
    if self_hits and agi_identity_hits and ("?" in str(query or "") or question_hits or any(t in {"e", "eh", "ser", "are", "is"} for t in tokens)):
        best_category = "identity"
        best_category_score = max(best_category_score, 0.90)
        best_hits = tuple(sorted(set(best_hits + agi_identity_hits)))

    # Copular identity questions have structure even when the only semantic role
    # is the question form itself, e.g. "who are you?".
    if (
        best_category_score == 0.0
        and self_hits
        and (
            any(t in {"quem", "who"} for t in question_hits)
            or (
                any(t in {"what"} for t in question_hits)
                and any(t in {"are", "is", "e", "eh", "ser"} for t in tokens)
            )
        )
    ):
        best_category = "identity"
        best_category_score = 0.62
        best_hits = ("copular_identity_question",)

    self_score = 1.0 if self_hits else 0.0
    question_score = 1.0 if ("?" in str(query or "") or question_hits) else 0.0
    imperative_self_score = 0.25 if self_hits and best_category_score >= 0.5 else 0.0

    score = (
        self_score * 0.48
        + best_category_score * 0.36
        + question_score * 0.12
        + imperative_self_score * 0.04
    )

    signals = tuple(
        sorted(
            {
                *(f"self:{hit}" for hit in self_hits[:3]),
                *(f"question:{hit}" for hit in question_hits[:2]),
                *(f"{best_category}:{hit}" for hit in best_hits[:3]),
            }
        )
    )
    return best_category if score > 0 else "none", round(min(1.0, score), 3), signals


def _semantic_enabled() -> bool:
    value = str(os.getenv("ULTRON_INTENT_EMBEDDINGS_ENABLED", "1") or "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _semantic_profiles() -> tuple[tuple[tuple[str, list[float]], ...], tuple[list[float], ...]]:
    from ultronpro import embeddings

    categories = tuple(_CATEGORY_PROFILES.items())
    positive_vectors = embeddings.embed_texts([text for _, text in categories])
    negative_vectors = embeddings.embed_texts(list(_NEGATIVE_PROFILES))
    return (
        tuple((category, vec) for (category, _), vec in zip(categories, positive_vectors)),
        tuple(negative_vectors),
    )


def _semantic_decision(query: str) -> tuple[str, float, float]:
    if not _semantic_enabled():
        return "none", 0.0, 0.0
    try:
        from ultronpro import embeddings

        positives, negatives = _semantic_profiles()
        query_vec = embeddings.embed_text(query)
        scored = [
            (category, embeddings.cosine_similarity(query_vec, vec))
            for category, vec in positives
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        negative_score = max(
            (embeddings.cosine_similarity(query_vec, vec) for vec in negatives),
            default=0.0,
        )
        category, positive_score = scored[0] if scored else ("none", 0.0)
        margin = float(positive_score) - float(negative_score)
        return category, round(float(positive_score), 3), round(margin, 3)
    except Exception:
        return "none", 0.0, 0.0


def classify_autobiographical_intent(query: str, *, threshold: float | None = None) -> IntentDecision:
    if threshold is None:
        threshold = float(os.getenv("ULTRON_AUTOBIO_INTENT_THRESHOLD", "0.62") or 0.62)

    structural_category, structural_score, structural_signals = _structural_decision(query)
    has_self_signal = any(str(signal).startswith("self:") for signal in structural_signals)
    fast_structural = str(os.getenv("ULTRON_AUTOBIO_FAST_STRUCTURAL", "1") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if fast_structural and structural_score >= threshold:
        return IntentDecision(
            label=AUTOBIOGRAPHICAL_LABEL,
            category=structural_category,
            confidence=structural_score,
            method="structural_features",
            semantic_score=0.0,
            structural_score=structural_score,
            margin=0.0,
            signals=structural_signals,
        )

    learned_threshold = float(os.getenv("ULTRON_LEARNED_INTENT_CONFIDENCE", "0.68") or 0.68)
    learned_min_evidence = int(os.getenv("ULTRON_LEARNED_INTENT_MIN_EVIDENCE", "2") or 2)
    learned_probe_floor = float(os.getenv("ULTRON_AUTOBIO_LEARNED_PROBE_FLOOR", "0.25") or 0.25)
    if has_self_signal and structural_score >= learned_probe_floor:
        try:
            from ultronpro.core import learned_intent

            learned = learned_intent.predict_route(query)
            if learned.evidence_count >= learned_min_evidence and learned.confidence >= learned_threshold:
                signals = tuple(
                    f"learned:{item.get('module')}:{item.get('similarity')}"
                    for item in learned.evidence[:4]
                )
                if learned.module == AUTOBIOGRAPHICAL_LABEL:
                    return IntentDecision(
                        label=AUTOBIOGRAPHICAL_LABEL,
                        category=structural_category if structural_category != "none" else "identity",
                        confidence=learned.confidence,
                        method=learned.method,
                        semantic_score=learned.top_similarity,
                        structural_score=structural_score,
                        margin=learned.margin,
                        signals=signals + structural_signals,
                    )
                return IntentDecision(
                    label="general",
                    category="none",
                    confidence=learned.confidence,
                    method=f"learned_route:{learned.module}",
                    semantic_score=learned.top_similarity,
                    structural_score=0.0,
                    margin=learned.margin,
                    signals=signals,
                )
        except Exception:
            pass

    semantic_category, semantic_score, semantic_margin = "none", 0.0, 0.0
    semantic_probe_floor = float(os.getenv("ULTRON_AUTOBIO_SEMANTIC_PROBE_FLOOR", "0.25") or 0.25)
    always_embed = str(os.getenv("ULTRON_INTENT_ALWAYS_EMBED", "0") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if always_embed or (has_self_signal and structural_score >= semantic_probe_floor):
        semantic_category, semantic_score, semantic_margin = _semantic_decision(query)
    semantic_threshold = float(os.getenv("ULTRON_AUTOBIO_SEMANTIC_THRESHOLD", "0.48") or 0.48)
    semantic_margin_min = float(os.getenv("ULTRON_AUTOBIO_SEMANTIC_MARGIN", "0.02") or 0.02)

    semantic_hit = semantic_score >= semantic_threshold and semantic_margin >= semantic_margin_min
    structural_hit = structural_score >= threshold

    if semantic_hit and semantic_score >= structural_score:
        return IntentDecision(
            label=AUTOBIOGRAPHICAL_LABEL,
            category=semantic_category,
            confidence=semantic_score,
            method="semantic_embeddings",
            semantic_score=semantic_score,
            structural_score=structural_score,
            margin=semantic_margin,
            signals=structural_signals,
        )

    if structural_hit:
        return IntentDecision(
            label=AUTOBIOGRAPHICAL_LABEL,
            category=structural_category,
            confidence=structural_score,
            method="structural_features",
            semantic_score=semantic_score,
            structural_score=structural_score,
            margin=semantic_margin,
            signals=structural_signals,
        )

    combined = max(structural_score, semantic_score if semantic_margin >= semantic_margin_min else 0.0)
    return IntentDecision(
        label="general",
        category="none",
        confidence=round(combined, 3),
        method="no_autobiographical_coverage",
        semantic_score=semantic_score,
        structural_score=structural_score,
        margin=semantic_margin,
        signals=structural_signals,
    )


def is_autobiographical_intent(query: str, *, threshold: float | None = None) -> bool:
    return classify_autobiographical_intent(query, threshold=threshold).label == AUTOBIOGRAPHICAL_LABEL


def is_external_factual_intent(query: str, *, threshold: float | None = None) -> bool:
    return classify_external_factual_intent(query, threshold=threshold).label == EXTERNAL_FACTUAL_LABEL


def is_creation_intent(query: str, *, threshold: float | None = None) -> bool:
    decision = classify_autobiographical_intent(query, threshold=threshold)
    return decision.label == AUTOBIOGRAPHICAL_LABEL and decision.category == "creation"
