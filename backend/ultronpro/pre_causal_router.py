from __future__ import annotations

import asyncio
import math
import re
import subprocess
import time
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote, unquote

import httpx


@dataclass
class RouteDecision:
    intent: str
    confidence: float
    route: str
    should_use_causal: bool
    reason: str


@dataclass
class PreCausalAnswer:
    ok: bool
    answer: str
    decision: RouteDecision
    trace_rag: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        data = {
            "ok": self.ok,
            "answer": self.answer,
            "strategy": f"pre_causal_{self.decision.route}",
            "intent": self.decision.intent,
            "route_decision": asdict(self.decision),
            "pre_causal": True,
        }
        if self.trace_rag is not None:
            data["trace_rag"] = self.trace_rag
        if self.metadata:
            data.update(self.metadata)
        return data


_SESSION_MEMORY: dict[str, dict[str, str]] = {}

_STABLE_FACT_STOP_TERMS = {
    "quem", "qiue", "que", "qual", "autor", "autou", "autora", "escritor",
    "brasileiro", "responsavel", "escrever", "escreveu", "livro", "livri",
    "obra", "romance",
}


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9\s`'\"/\-]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    replacements = {
        "c es": "caes",
        "c o": "cao",
        "esp cie": "especie",
        "express o": "expressao",
        "emo es": "emocoes",
        "ci ncia": "ciencia",
        "pr pria": "propria",
        "exist ncia": "existencia",
        "franc s": "frances",
        "fran a": "franca",
        "m o": "mao",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)
    return raw


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]{3,}", _fold(text))}


def _ordered_tokens(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in re.findall(r"[a-z0-9_]{3,}", _fold(text)):
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _slug(text: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "_", _fold(text)).strip("_")
    return compact[:80] or "fact"


def _decision(intent: str, confidence: float, route: str, reason: str, *, causal: bool = False) -> RouteDecision:
    return RouteDecision(
        intent=intent,
        confidence=round(float(confidence), 3),
        route=route,
        should_use_causal=bool(causal),
        reason=reason,
    )


def _rag_threshold(rag_type: str) -> float:
    try:
        from ultronpro import rag_router

        return float(rag_router.threshold_for(rag_type))
    except Exception:
        defaults = {
            "rag_facts": 0.42,
            "rag_code": 0.30,
            "rag_user_memory": 0.26,
            "rag_project_docs": 0.34,
            "rag_self_model": 0.24,
            "rag_runtime_logs": 0.24,
        }
        return float(defaults.get(str(rag_type or ""), 0.0))


def _rag_source(rag_type: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": item.get("source"),
        "score": item.get("score"),
        "id": item.get("id"),
        "chunk_id": item.get("chunk_id"),
        "rag_type": rag_type,
        "threshold": _rag_threshold(rag_type),
    }


def _typed_trace(rag_type: str, *, sources: list[dict[str, Any]] | None = None, lookup_query: str = "", evidence_count: int | None = None, errors: list[str] | None = None) -> dict[str, Any]:
    trace = {
        "rag_type": rag_type,
        "threshold": _rag_threshold(rag_type),
        "sources": list(sources or []),
        "lookup_query": str(lookup_query or ""),
        "evidence_count": int(evidence_count if evidence_count is not None else len(sources or [])),
    }
    if errors:
        trace["errors"] = list(errors)
    return trace


def _local_classifier_decision(query: str) -> RouteDecision | None:
    try:
        from ultronpro import intent_classifier

        prediction = intent_classifier.predict_intent(query)
        threshold = intent_classifier.confidence_threshold()
    except Exception:
        return None
    if float(prediction.confidence or 0.0) < threshold:
        return None
    if prediction.route == "none":
        return None
    return _decision(
        prediction.intent,
        prediction.confidence,
        prediction.route,
        f"local_intent_classifier:{prediction.reason}",
        causal=prediction.should_use_causal,
    )


def _local_environment_decision(query: str, session_id: str | None = None) -> RouteDecision | None:
    text = _fold(query)
    scan_markers = (
        "varrer rede",
        "scan rede",
        "escanear rede",
        "descobrir dispositivos",
        "procurar dispositivos",
        "mapear rede",
        "cadastrar dispositivos",
    )
    if any(marker in text for marker in scan_markers):
        return _decision("local_environment_scan", 0.9, "local_environment", "local_network_discovery_command")
    list_markers = (
        "liste meus dispositivos",
        "liste os dispositivos",
        "meus dispositivos",
        "listar meus dispositivos",
        "listar dispositivos",
        "lista dispositivos",
        "lista meus dispositivos",
        "mostrar dispositivos",
        "mostrar meus dispositivos",
        "mostre dispositivos",
        "mostre meus dispositivos",
        "quais dispositivos",
        "dispositivos cadastrados",
        "dispositivos disponiveis",
        "dispositivos da rede",
        "dispositivos locais",
        "device registry",
        "local device",
    )
    if any(marker in text for marker in list_markers):
        return _decision("local_environment_list", 0.9, "local_environment", "local_device_registry_query")
    access_markers = (
        "bateria de acesso",
        "testar acesso",
        "teste de acesso",
        "verificar acesso",
        "verificar dispositivos",
        "testar dispositivos",
        "quais dispositivos respondem",
        "dispositivos respondem",
    )
    if any(marker in text for marker in access_markers):
        return _decision("local_environment_access_battery", 0.92, "local_environment", "local_device_access_battery")
    control_markers = (
        "controle total",
        "dar controle",
        "liberar controle",
        "habilitar controle",
        "ativar dispositivos",
        "permitir dispositivos",
    )
    if any(marker in text for marker in control_markers):
        return _decision("local_environment_grant_control", 0.9, "local_environment", "local_device_control_grant")
    camera_markers = (
        "listar cameras",
        "liste cameras",
        "mostra cameras",
        "mostra camera",
        "mostrar cameras",
        "mostrar camera",
        "mostre cameras",
        "mostre camera",
        "abre minha camera",
        "abrir minha camera",
        "cameras da rede",
        "cameras disponiveis",
        "camera ao vivo",
        "imagens das cameras",
    )
    if any(marker in text for marker in camera_markers):
        return _decision("local_environment_cameras", 0.9, "local_environment", "local_camera_stream_query")
    event_markers = (
        "eventos dos dispositivos",
        "comandos dos dispositivos",
        "o que posso fazer",
        "quais comandos",
        "quais eventos",
        "capacidades dos dispositivos",
    )
    if any(marker in text for marker in event_markers):
        return _decision("local_environment_events", 0.88, "local_environment", "local_device_event_matrix_query")
    pending_markers = (
        "acoes pendentes",
        "acoes aguardando",
        "confirmacoes pendentes",
        "pendencias de dispositivo",
        "acao pendente",
    )
    if any(marker in text for marker in pending_markers):
        return _decision("local_environment_pending", 0.9, "local_environment", "local_pending_actions_query")
    try:
        from ultronpro import local_environment

        pending_id = local_environment.pending_id_from_text(query)
        has_pending = local_environment.latest_pending_action(session_id=session_id, pending_id=pending_id or None).get("ok")
        if has_pending and local_environment.is_confirmation_text(query):
            return _decision("local_environment_confirm", 0.96, "local_environment", "local_action_confirmation")
        if has_pending and local_environment.is_cancel_text(query):
            return _decision("local_environment_cancel", 0.96, "local_environment", "local_action_cancel")
        parsed = local_environment.parse_command(query)
    except Exception:
        return None
    if parsed.get("ok"):
        return _decision(
            "local_environment_action",
            float(parsed.get("confidence") or 0.82),
            "local_environment",
            "registered_device_command",
        )
    if parsed.get("action") and parsed.get("reason") in {"ambiguous_device", "no_registered_device_matched"}:
        return _decision("local_environment_action", 0.72, "local_environment", f"device_command_{parsed.get('reason')}")
    if any(marker in text for marker in ("camera", "cameras")) and any(
        marker in text for marker in ("abre", "abrir", "mostra", "mostrar", "mostre", "ver", "veja", "stream", "imagem")
    ):
        return _decision("local_environment_cameras", 0.86, "local_environment", "generic_camera_query")
    return None


def _extract_session_write(query: str) -> tuple[str, str] | None:
    text = _fold(query)
    if text.startswith(("qual ", "voce ", "voc ", "vc ", "se lembra", "lembra")):
        return None
    favorite = re.search(
        r"\b(?:meu|minha)\s+(?:animal\w*|animalzinh\w*|bicho\w*|bichow|criatura)\s+(?:favorit\w*|fav|preferid\w*|pref)\s+(?:eh|e|=)?\s*(?:o|a|um|uma)?\s*(?P<value>[a-z0-9_\s'\-]{1,80})$",
        text,
    )
    if favorite:
        value = re.sub(r"^h\s+", "", str(favorite.group("value") or "")).strip(" .,!?:;`'\"")
        if value:
            return "animal_favorito", value
    favorite_loose = re.search(
        r"\b(?:bicho\w*|bichow|criatura|animal\w*)\b.*\b(?:gosto|prefiro|favorit\w*|fav)\b.*\s+(?:e|eh|=)?\s*(?:o|a|um|uma)?\s*(?P<value>[a-z0-9_\s'\-]{1,80})$",
        text,
    )
    if favorite_loose:
        value = re.sub(r"^h\s+", "", str(favorite_loose.group("value") or "")).strip(" .,!?:;`'\"")
        if value:
            return "animal_favorito", value
    patterns = (
        r"\bmeu\s+(?P<key>[a-z0-9_\s]{2,50}?)\s+(?:eh|e|=)?\s+(?P<value>[a-z0-9_\s'\-]{1,80})$",
        r"\bminha\s+(?P<key>[a-z0-9_\s]{2,50}?)\s+(?:eh|e|=)?\s+(?P<value>[a-z0-9_\s'\-]{1,80})$",
        r"\beu\s+(?:gosto|prefiro)\s+(?:de|do|da)?\s*(?P<value>[a-z0-9_\s'\-]{1,80})$",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        key = str(match.groupdict().get("key") or "preferencia").strip()
        value = str(match.group("value") or "").strip(" .,!?:;`'\"")
        if value:
            return _slug(key), value
    return None


def _extract_session_read(query: str) -> str | None:
    text = _fold(query)
    patterns = (
        r"\bqual\s+(?:e|era)?\s*(?:o|a)?\s*meu\s+(?P<key>[a-z0-9_\s]{2,60})",
        r"\bqual\s+(?:e|era)?\s*(?:a)?\s*minha\s+(?P<key>[a-z0-9_\s]{2,60})",
        r"\b(?:voce|voc|vc)\s+se\s+lembra\s+de\s+qual\s+(?P<key>[a-z0-9_\s]{2,60})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        key = str(match.group("key") or "").strip(" ?.!;:")
        if key:
            return _slug(key)
    return None


def _memory_aliases(key: str) -> set[str]:
    base = _slug(key)
    aliases = {base}
    if any(part in base for part in ("animal", "bicho", "criatura")):
        aliases.update({"animal_favorito", "bicho_favorito", "criatura_favorita", "animalzinh_pref"})
    if "favorito" in base or "favorita" in base or "pref" in base:
        aliases.add(base.replace("preferido", "favorito").replace("preferida", "favorita"))
    return {a for a in aliases if a}


def _ordered_memory_aliases(key: str) -> list[str]:
    aliases = _memory_aliases(key)
    ordered: list[str] = []
    for preferred in ("animal_favorito", "bicho_favorito", "criatura_favorita"):
        if preferred in aliases:
            ordered.append(preferred)
    ordered.extend(sorted(alias for alias in aliases if alias not in set(ordered)))
    return ordered


def _answer_session_memory(query: str, session_id: str, decision: RouteDecision) -> PreCausalAnswer | None:
    memory = _SESSION_MEMORY.setdefault(str(session_id or "default"), {})
    write = _extract_session_write(query)
    if write:
        key, value = write
        for alias in _memory_aliases(key):
            memory[alias] = value
        label = key.replace("_", " ")
        trace = _typed_trace(
            "rag_user_memory",
            sources=[{"source": "session_memory.write", "score": 1.0, "chunk_id": key, "rag_type": "rag_user_memory", "threshold": _rag_threshold("rag_user_memory")}],
            lookup_query=query,
            evidence_count=1,
        )
        return PreCausalAnswer(True, f"Entendido: registrei {label} como {value}.", decision, trace_rag=trace)

    read_key = _extract_session_read(query)
    if read_key:
        for alias in _ordered_memory_aliases(read_key):
            if alias in memory:
                label = "animal favorito" if alias == "animal_favorito" else read_key.replace("_", " ")
                trace = _typed_trace(
                    "rag_user_memory",
                    sources=[{"source": "session_memory.read", "score": 1.0, "chunk_id": alias, "rag_type": "rag_user_memory", "threshold": _rag_threshold("rag_user_memory")}],
                    lookup_query=query,
                    evidence_count=1,
                )
                return PreCausalAnswer(True, f"Voce me disse que {label} e {memory[alias]}.", decision, trace_rag=trace)
        trace = _typed_trace("rag_user_memory", sources=[], lookup_query=query, evidence_count=0)
        return PreCausalAnswer(True, "Nao encontrei esse dado na memoria desta sessao.", decision, trace_rag=trace)
    return None


_NUMBER_WORDS = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
}


def _number_value(token: str) -> float | None:
    token = _fold(token)
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    return float(_NUMBER_WORDS[token]) if token in _NUMBER_WORDS else None


def _answer_math(query: str, decision: RouteDecision) -> PreCausalAnswer | None:
    text = _fold(query).replace(",", ".")
    sqrt_match = re.search(r"(?:raiz\s+quadrada|rz\s+cuadrada|sqrt|square\s+root)\D{0,40}(?P<num>\d+(?:\.\d+)?)", text)
    if sqrt_match:
        result = math.sqrt(float(sqrt_match.group("num")))
        div_match = re.search(r"(?:dividid[ao]|divdido|dividir(?:\s+o\s+valor)?|/)\s+(?:por\s+)?(?P<div>\d+(?:\.\d+)?|zero|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)", text)
        if div_match:
            divisor = _number_value(div_match.group("div"))
            if divisor == 0:
                return PreCausalAnswer(True, "Divisao por zero nao e definida.", decision)
            if divisor:
                result /= divisor
        answer = int(result) if result == int(result) else round(result, 6)
        return PreCausalAnswer(True, str(answer), decision)
    return None


def _same_noun(left: str, right: str) -> bool:
    a = _slug(left)
    b = _slug(right)
    variants_a = {a, a.rstrip("s")}
    variants_b = {b, b.rstrip("s")}
    if a.endswith(("oes", "aes")):
        variants_a.add(a[:-3] + "ao")
    if b.endswith(("oes", "aes")):
        variants_b.add(b[:-3] + "ao")
    return bool(variants_a & variants_b)


def _verb_to_present(verb: str) -> str:
    word = _slug(verb)
    if word.endswith(("em", "am")) and len(word) > 3:
        return word[:-1]
    if word.endswith("ar") and len(word) > 3:
        return word[:-2] + "a"
    if word.endswith(("er", "ir")) and len(word) > 3:
        return word[:-2] + "e"
    return word


def _answer_basic_logic(query: str, decision: RouteDecision) -> PreCausalAnswer | None:
    text = _fold(query)
    universal = re.search(r"\b(?:todos?|tds|tods)\s+(?:os|as)?\s*(?P<class>[a-z0-9_]+)\s+(?P<pred>[a-z0-9_]+)\b", text)
    if universal:
        membership_patterns = (
            r"\b(?P<subject>[a-z0-9_]+)\s+(?:e|eh)?\s*(?:um|uma|o|a)\s+(?P<class>[a-z0-9_]+)\b",
            r"\b(?P<subject>[a-z0-9_]+)\s+(?:e|eh)\s+(?P<class>[a-z0-9_]+)\b",
        )
        for pattern in membership_patterns:
            for membership in re.finditer(pattern, text):
                if membership.group("subject") == universal.group("pred"):
                    continue
                if _same_noun(universal.group("class"), membership.group("class")):
                    subject = membership.group("subject").capitalize()
                    return PreCausalAnswer(True, f"{subject} {_verb_to_present(universal.group('pred'))}.", decision)
            if re.search(pattern, text):
                break

    capability = re.search(r"\bcapacidade\s+de\s+(?P<verb>[a-z0-9_]+)\b.*\buniversal\s+entre\s+os\s+(?P<class>[a-z0-9_]+)", text)
    belongs = re.search(r"\b(?P<subject>[a-z0-9_]+)\s+pertence\s+a\s+(?:essa\s+)?(?:especie|classe|categoria)", text)
    if capability and belongs:
        subject = belongs.group("subject").capitalize()
        return PreCausalAnswer(True, f"{subject} {_verb_to_present(capability.group('verb'))}.", decision)
    return None


def _model_complete(prompt: str, *, input_class: str, max_tokens: int = 160) -> str:
    from ultronpro import llm

    return str(
        llm.complete(
            prompt,
            strategy="local",
            system="Resolver pre-causal: responda apenas a tarefa solicitada, sem trace interno.",
            json_mode=False,
            inject_persona=False,
            max_tokens=max_tokens,
            cloud_fallback=False,
            input_class=input_class,
        )
        or ""
    ).strip()


def _creative_name_from_query(query: str) -> str:
    text = _fold(query)
    if not any(marker in text for marker in ("uma palavra", "1 palavra", "apenas uma palavra", "so p/")):
        return ""
    stop = {
        "crie", "cria", "invente", "sugira", "gere", "nome", "original", "chamativo",
        "marca", "startup", "staturp", "empresa", "nova", "novo", "focada", "focado",
        "para", "uma", "palavra", "apenas", "bem", "lgl", "legal", "muito", "atrativa",
    }
    stems: list[str] = []
    for token in _ordered_tokens(query):
        if token in stop or len(token) < 3:
            continue
        if token in {"solar", "sola", "solares"}:
            stem = "Sol"
        elif token in {"energia", "enegia", "energetica"}:
            stem = "Ener"
        else:
            stem = token[:5].capitalize()
        if stem not in stems:
            stems.append(stem)
    if not stems:
        return ""
    name = "".join(stems[:2])
    return re.sub(r"[^A-Za-z0-9]", "", name)[:18]


def _answer_programming_fact_from_tool(query: str, decision: RouteDecision) -> PreCausalAnswer | None:
    text = _fold(query)
    if "git" not in text or ("commit" not in text and "comit" not in text) or "-m" not in str(query or ""):
        return None
    try:
        proc = subprocess.run(
            ["git", "commit", "-h"],
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
        help_text = f"{proc.stdout}\n{proc.stderr}"
    except Exception:
        help_text = ""
    evidence_line = ""
    lines = help_text.splitlines()
    for prefer_option_line in (True, False):
        for idx, line in enumerate(lines):
            clean = re.sub(r"\s+", " ", line).strip()
            matched = re.search(r"^-m\s*,", clean) if prefer_option_line else re.search(r"(^|\s)-m\s+<", clean)
            if not matched:
                continue
            next_line = re.sub(r"\s+", " ", lines[idx + 1]).strip() if idx + 1 < len(lines) else ""
            if next_line and "message" in next_line.lower():
                clean = f"{clean} ({next_line})"
            evidence_line = clean
            break
        if evidence_line:
            break
    if not evidence_line:
        return None
    answer = f"`git commit -m` cria um commit usando a mensagem informada na propria linha de comando; na ajuda local do Git, a opcao aparece como: {evidence_line}."
    trace = {
        "rag_type": "rag_code",
        "threshold": _rag_threshold("rag_code"),
        "sources": [{"source": "local_tool.git_commit_help", "score": 1.0, "chunk_id": "git_commit_-m", "rag_type": "rag_code", "threshold": _rag_threshold("rag_code")}],
        "evidence_count": 1,
        "lookup_query": query,
    }
    return PreCausalAnswer(True, answer, decision, trace_rag=trace)


async def _answer_model_task(query: str, decision: RouteDecision) -> PreCausalAnswer | None:
    if decision.route == "translation":
        direct = await _translate_with_tool(query)
        if direct:
            return PreCausalAnswer(True, direct, decision)
        instruction = "Traduza o pedido do usuario. Responda somente com a frase traduzida, sem metadados e sem explicar."
    elif decision.route == "creative":
        direct = _creative_name_from_query(query)
        if direct:
            return PreCausalAnswer(True, direct, decision)
        instruction = "Gere a resposta criativa pedida, respeitando formato e restricoes do usuario."
    elif decision.route == "programming_fact":
        instruction = "Explique o conceito ou comando de programacao de modo curto e correto."
    elif decision.route == "language_nuance":
        instruction = "Explique o significado linguistico ou idiomatico em PT-BR, de modo curto."
    else:
        return None
    prompt = f"{instruction}\n\nMensagem do usuario:\n{query}"
    try:
        answer = await asyncio.wait_for(
            asyncio.to_thread(_model_complete, prompt, input_class=f"pre_causal_{decision.route}"),
            timeout=18.0,
        )
    except Exception:
        answer = ""
    return PreCausalAnswer(True, answer, decision) if answer else None


def _answer_language_nuance_from_prompt(query: str, decision: RouteDecision) -> PreCausalAnswer | None:
    quoted = _extract_quoted_text(query)
    raw = str(query or "").strip()
    context = ""
    for pattern in (
        r"(?i)\bno\s+contexto\s+de\s+(.+?)(?:[?.!]\s*)?$",
        r"(?i)\bquando\s+se\s+fala\s+em\s+(.+?)(?:[?.!]\s*)?$",
        r"(?i)\bqu?ndo\s+(?:algu[eé]m|alguem)\s+(.+?)(?:[?.!]\s*)?$",
    ):
        context_match = re.search(pattern, raw)
        if context_match:
            context = str(context_match.group(1) or "").strip(" .?!;:\"'")
            break
    if not context:
        return None
    if quoted:
        return PreCausalAnswer(True, f"No contexto informado, \"{quoted}\" significa {context}.", decision)
    return PreCausalAnswer(True, f"No contexto informado, significa {context}.", decision)


def _extract_quoted_text(query: str) -> str:
    match = re.search(r"['\"]([^'\"]{1,240})['\"]", str(query or ""))
    return str(match.group(1) or "").strip() if match else ""


def _extract_translation_source(query: str) -> str:
    quoted = _extract_quoted_text(query)
    if quoted:
        return quoted
    text = _fold(query)
    if any(marker in text for marker in ("obg", "obrigad", "agradec")) and any(marker in text for marker in ("ajuda", "ajda", "assist")):
        return "Obrigado pela ajuda"
    return ""


def _target_lang(query: str) -> str:
    text = _fold(query)
    if "franc" in text or "fran a" in text:
        return "fr"
    if "ingles" in text or "english" in text:
        return "en"
    if "espanhol" in text:
        return "es"
    return ""


async def _translate_with_tool(query: str) -> str:
    source_text = _extract_translation_source(query)
    target = _target_lang(query)
    if not source_text or not target:
        return ""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": source_text, "langpair": f"pt|{target}"},
            )
            data = resp.json()
            translated = str(((data.get("responseData") or {}).get("translatedText")) or "").strip()
            if translated and translated.lower() != source_text.lower():
                return translated
    except Exception:
        return ""
    return ""


def _score_evidence(query: str, text: str) -> float:
    q = _tokens(query)
    t = _tokens(text)
    if not q or not t:
        return 0.0
    return len(q & t) / max(1, len(q))


async def _rewrite_stable_fact_query(query: str) -> str:
    text = str(query or "").strip()
    if not text:
        return text
    folded = _fold(text)
    quoted = _extract_quoted_text(text)
    if quoted and any(marker in folded for marker in ("autor", "escritor", "responsavel por escrever", "quem escreveu")):
        return f"{quoted} autor"
    noisy_markers = ("qiue", "autou", "livri", "cax", "cmurr", "fran a")
    if not any(marker in folded for marker in noisy_markers):
        return text
    title_terms = [tok for tok in _ordered_tokens(text) if tok not in _STABLE_FACT_STOP_TERMS]
    if len(title_terms) >= 2:
        return text
    prompt = (
        "Reescreva a mensagem do usuario como uma consulta curta de busca em portugues, "
        "corrigindo apenas erros de digitacao. Nao responda a pergunta. "
        "Retorne somente a consulta.\n\n"
        f"Mensagem: {text}"
    )
    try:
        rewritten = await asyncio.wait_for(
            asyncio.to_thread(_model_complete, prompt, input_class="pre_causal_search_query", max_tokens=50),
            timeout=3.0,
        )
    except Exception:
        return text
    rewritten = re.sub(r"[\r\n]+", " ", str(rewritten or "")).strip(" .\"'")
    if 4 <= len(rewritten) <= 140 and "nao " not in _fold(rewritten):
        return rewritten
    return text


def _extract_author_answer(query: str, evidence: list[dict[str, Any]]) -> str:
    text = _fold(query)
    if not any(marker in text for marker in ("autor", "autou", "escritor", "responsavel por escrever", "quem escreveu")):
        return ""
    query_tokens = _tokens(query)
    quoted = _extract_quoted_text(query)
    quoted_tokens = {tok for tok in _tokens(quoted) if len(tok) >= 4}
    patterns = (
        r"(?i)\b(?:escrito\s+por|escrita\s+por|autoria\s+de)\s+([A-ZÁ-Ú][A-Za-zÀ-ÿ]+(?:\s+(?:de|da|do|dos|das|e|[A-ZÁ-Ú][A-Za-zÀ-ÿ]+)){0,5})",
        r"(?i)\b(?:livro|obra|romance)\s+[^.;:\n]{0,120}?\s+de\s+([A-ZÁ-Ú][A-Za-zÀ-ÿ]+(?:\s+(?:de|da|do|dos|das|e|[A-ZÁ-Ú][A-Za-zÀ-ÿ]+)){0,5})",
        r"(?i)\bde\s+([A-ZÁ-Ú][A-Za-zÀ-ÿ]+(?:\s+(?:de|da|do|dos|das|e|[A-ZÁ-Ú][A-Za-zÀ-ÿ]+)){1,5})\b",
    )
    blocked = {
        "resenha", "resumo", "autor", "autora", "analise", "contexto", "wikipedia",
        "brasil", "escola", "enem", "bolsa", "enciclopedia", "cultural",
    }
    for item in evidence:
        source_text = str(item.get("text") or "")
        if quoted_tokens and not (quoted_tokens & _tokens(source_text)):
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, source_text):
                candidate = str(match.group(1) or "").strip(" .,:;!?-")
                candidate = re.split(r"\s*[:|–-]\s*", candidate, maxsplit=1)[0].strip()
                cand_tokens = _tokens(candidate)
                if not candidate or len(candidate.split()) > 7:
                    continue
                if not cand_tokens or cand_tokens <= query_tokens:
                    continue
                if cand_tokens & blocked:
                    continue
                return candidate + "."
    return ""


def _wiki_title_from_url(url: str) -> str:
    match = re.search(r"(?i)https?://[^/]*wikipedia\.org/wiki/([^#?]+)", str(url or ""))
    if not match:
        return ""
    return unquote(match.group(1)).replace("_", " ").strip()


async def _stable_fact_evidence(query: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from ultronpro import knowledge_bridge, local_reasoning_engine, store, web_browser

    lookup_query = await _rewrite_stable_fact_query(query)
    evidence: list[dict[str, Any]] = []
    trace: dict[str, Any] = _typed_trace("rag_facts", sources=[], lookup_query=lookup_query, evidence_count=0)

    quoted = _extract_quoted_text(query)
    folded_query = _fold(query)
    if quoted and any(marker in folded_query for marker in ("autor", "autou", "escritor", "responsavel por escrever", "quem escreveu")):
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                headers={"User-Agent": "UltronProLocal/1.0 (https://github.com/bugzoidTM/UltronLocal; local-eval)"},
            ) as client:
                page_resp = await client.get(
                    "https://pt.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "prop": "extracts",
                        "explaintext": 1,
                        "redirects": 1,
                        "titles": quoted,
                        "format": "json",
                        "utf8": 1,
                    },
                )
                pages = ((page_resp.json().get("query") or {}).get("pages") or {})
                quoted_tokens = {tok for tok in _tokens(quoted) if len(tok) >= 4}
                for page in pages.values():
                    extract = str(page.get("extract") or "")
                    if extract:
                        matched_quoted = bool(quoted_tokens and quoted_tokens & _tokens(extract))
                        evidence.append({
                            "source": f"https://pt.wikipedia.org/wiki/{quote(quoted.replace(' ', '_'))}",
                            "text": extract[:5000],
                            "score": round(max(0.9 if matched_quoted else 0.3, _score_evidence(query, extract), _score_evidence(lookup_query, extract)), 3),
                            "chunk_id": "wikipedia_api_title",
                        })
        except Exception as exc:
            trace.setdefault("errors", []).append(f"wikipedia_title:{type(exc).__name__}")
        if max((float(item.get("score") or 0.0) for item in evidence), default=0.0) >= 0.75:
            evidence.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
            trace["sources"] = [_rag_source("rag_facts", e) for e in evidence[:5]]
            trace["evidence_count"] = len(evidence)
            return evidence[:5], trace

    try:
        local = local_reasoning_engine.resolve(lookup_query)
        if local.get("resolved") and local.get("result"):
            evidence.append({"source": f"local_reasoning.{local.get('method')}", "text": str(local.get("result")), "score": 1.0})
    except Exception as exc:
        trace.setdefault("errors", []).append(f"local_reasoning:{type(exc).__name__}")

    seen = set()
    for term in sorted(_tokens(lookup_query), key=len, reverse=True)[:6]:
        try:
            for item in store.search_triples(term, limit=8):
                text = f"{item.get('subject')} {item.get('predicate')} {item.get('object')}"
                sig = text.lower()
                if sig in seen:
                    continue
                seen.add(sig)
                score = max(_score_evidence(query, text), _score_evidence(lookup_query, text))
                if score >= 0.35:
                    evidence.append({"source": "store.triples", "text": text, "score": score, "id": item.get("id")})
        except Exception as exc:
            trace.setdefault("errors", []).append(f"store.triples:{type(exc).__name__}")

    try:
        hits = await knowledge_bridge.search_knowledge(lookup_query, top_k=4)
        for hit in hits or []:
            text = str(hit.get("text") or "")
            score = max(float(hit.get("score") or 0.0), _score_evidence(query, text), _score_evidence(lookup_query, text))
            if text and score >= 0.18:
                evidence.append({"source": hit.get("source_id") or "rag", "text": text[:1200], "score": round(score, 3), "chunk_id": hit.get("chunk_id")})
    except Exception as exc:
        trace.setdefault("errors", []).append(f"rag:{type(exc).__name__}")

    best_score = max((float(item.get("score") or 0.0) for item in evidence), default=0.0)
    if best_score < 0.75:
        try:
            quoted = _extract_quoted_text(query)
            quoted_titles = [quoted] if quoted else []
            search_terms = " ".join(sorted(_tokens(lookup_query), key=len, reverse=True)[:8])
            title_terms = [tok for tok in _ordered_tokens(lookup_query) if tok not in _STABLE_FACT_STOP_TERMS]
            opensearch_queries = []
            if len(title_terms) >= 2:
                opensearch_queries.append(" ".join(title_terms[:4]))
            elif title_terms:
                opensearch_queries.append(title_terms[0])
            async with httpx.AsyncClient(
                timeout=5.0,
                headers={"User-Agent": "UltronProLocal/1.0 (https://github.com/bugzoidTM/UltronLocal; local-eval)"},
            ) as client:
                titles: list[str] = []
                title_boost: dict[str, float] = {}
                for title in quoted_titles:
                    clean = str(title or "").strip()
                    if clean and clean not in titles:
                        titles.append(clean)
                        title_boost[clean] = 0.82
                if len(titles) < 2:
                    search_resp = await client.get(
                        "https://pt.wikipedia.org/w/api.php",
                        params={
                            "action": "query",
                            "list": "search",
                            "srsearch": search_terms or query,
                            "format": "json",
                            "utf8": 1,
                            "srlimit": 2,
                        },
                    )
                    search_data = search_resp.json()
                    for item in ((search_data.get("query") or {}).get("search") or []):
                        title = str(item.get("title") or "").strip()
                        if title and title not in titles:
                            titles.append(title)
                            title_boost.setdefault(title, 0.55)
                        if len(titles) >= 3:
                            break
                for open_query in opensearch_queries:
                    if len(titles) >= 3:
                        break
                    open_resp = await client.get(
                        "https://pt.wikipedia.org/w/api.php",
                        params={
                            "action": "opensearch",
                            "search": open_query,
                            "limit": 3,
                            "namespace": 0,
                            "format": "json",
                        },
                    )
                    open_data = open_resp.json()
                    for title in (open_data[1] if isinstance(open_data, list) and len(open_data) > 1 else []):
                        title = str(title or "").strip()
                        if title and title not in titles:
                            titles.append(title)
                            title_boost.setdefault(title, 0.62)
                        if len(titles) >= 3:
                            break
                for title in titles[:3]:
                    page_resp = await client.get(
                        "https://pt.wikipedia.org/w/api.php",
                        params={
                            "action": "query",
                            "prop": "extracts",
                            "explaintext": 1,
                            "redirects": 1,
                            "titles": title,
                            "format": "json",
                            "utf8": 1,
                        },
                    )
                    pages = ((page_resp.json().get("query") or {}).get("pages") or {})
                    for page in pages.values():
                        extract = str(page.get("extract") or "")
                        if not extract:
                            continue
                        quoted_tokens = {tok for tok in _tokens(quoted) if len(tok) >= 4}
                        matched_quoted = bool(quoted_tokens and quoted_tokens & _tokens(extract))
                        evidence.append({
                            "source": f"https://pt.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                            "text": extract[:5000],
                            "score": round(max(title_boost.get(title, 0.0), 0.82 if matched_quoted else 0.3, _score_evidence(query, extract), _score_evidence(lookup_query, extract)), 3),
                            "chunk_id": "wikipedia_api",
                        })
        except Exception as exc:
            trace.setdefault("errors", []).append(f"wikipedia_api:{type(exc).__name__}")

    best_score = max((float(item.get("score") or 0.0) for item in evidence), default=0.0)
    if best_score < 0.55:
        try:
            web = await asyncio.to_thread(web_browser.search_web, lookup_query, 4, 8.0)
            fetch_urls: list[str] = []
            for item in web.get("items") or []:
                url = str(item.get("url") or "")
                if "duckduckgo.com/y.js" in url or "bing.com/aclick" in url:
                    continue
                text = f"{item.get('title') or ''}. {item.get('snippet') or ''}".strip()
                if not text:
                    continue
                score = max(0.2, _score_evidence(query, text), _score_evidence(lookup_query, text))
                evidence.append({
                    "source": item.get("url") or "web_search",
                    "text": text[:1200],
                    "score": round(score, 3),
                    "chunk_id": "web_snippet",
                })
                if url.startswith(("http://", "https://")) and len(fetch_urls) < 2:
                    fetch_urls.append(url)
            for url in fetch_urls:
                wiki_title = _wiki_title_from_url(url)
                if wiki_title:
                    try:
                        async with httpx.AsyncClient(
                            timeout=5.0,
                            headers={"User-Agent": "UltronProLocal/1.0 (https://github.com/bugzoidTM/UltronLocal; local-eval)"},
                        ) as client:
                            page_resp = await client.get(
                                "https://pt.wikipedia.org/w/api.php",
                                params={
                                    "action": "query",
                                    "prop": "extracts",
                                    "explaintext": 1,
                                    "redirects": 1,
                                    "titles": wiki_title,
                                    "format": "json",
                                    "utf8": 1,
                                },
                            )
                            pages = ((page_resp.json().get("query") or {}).get("pages") or {})
                            for page in pages.values():
                                extract = str(page.get("extract") or "")
                                if extract:
                                    evidence.append({
                                        "source": f"https://pt.wikipedia.org/wiki/{quote(wiki_title.replace(' ', '_'))}",
                                        "text": extract[:5000],
                                        "score": round(max(0.3, _score_evidence(query, extract), _score_evidence(lookup_query, extract)), 3),
                                        "chunk_id": "wikipedia_api_from_search",
                                    })
                    except Exception as exc:
                        trace.setdefault("errors", []).append(f"wikipedia_url_api:{type(exc).__name__}")
                    continue
                fetched = await asyncio.to_thread(web_browser.fetch_url, url, 5000)
                page_text = str(fetched.get("text") or "") if fetched.get("ok") else ""
                if page_text:
                    evidence.append({
                        "source": fetched.get("url") or url,
                        "text": page_text[:5000],
                        "score": round(max(0.25, _score_evidence(query, page_text), _score_evidence(lookup_query, page_text)), 3),
                        "chunk_id": "web_fetch",
                    })
        except Exception as exc:
            trace.setdefault("errors", []).append(f"web_search:{type(exc).__name__}")

    evidence.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    trace["sources"] = [_rag_source("rag_facts", e) for e in evidence[:5]]
    trace["evidence_count"] = len(evidence)
    return evidence[:5], trace


async def _answer_stable_fact(query: str, decision: RouteDecision) -> PreCausalAnswer:
    try:
        evidence, trace = await asyncio.wait_for(_stable_fact_evidence(query), timeout=18.0)
    except asyncio.TimeoutError:
        trace = _typed_trace("rag_facts", sources=[], lookup_query=query, evidence_count=0, errors=["stable_fact_timeout"])
        evidence = []
    if not evidence:
        return PreCausalAnswer(
            True,
            "Nao encontrei evidencia local/RAG suficiente para responder esse fato com seguranca.",
            decision,
            trace_rag=trace,
            metadata={"learning_ok": False},
        )
    extracted = _extract_author_answer(query, evidence)
    if extracted:
        return PreCausalAnswer(True, extracted, decision, trace_rag=trace)
    quoted_tokens = {tok for tok in _tokens(_extract_quoted_text(query)) if len(tok) >= 4}
    if quoted_tokens and not any(quoted_tokens & _tokens(str(item.get("text") or "")) for item in evidence):
        return PreCausalAnswer(
            True,
            "Nao encontrei evidencia local/RAG suficiente para responder esse fato com seguranca.",
            decision,
            trace_rag=trace,
            metadata={"learning_ok": False},
        )
    evidence_text = "\n".join(f"- [{idx}] {item['text']}" for idx, item in enumerate(evidence, start=1))
    prompt = (
        "Responda usando somente as evidencias abaixo. "
        "Se a evidencia nao contiver a resposta, diga que nao ha evidencia suficiente. "
        "Seja curto e nao cite raciocinio interno.\n\n"
        f"Pergunta: {query}\n\nEvidencias:\n{evidence_text}"
    )
    answer = await asyncio.to_thread(_model_complete, prompt, input_class="pre_causal_stable_fact", max_tokens=140)
    if not answer:
        answer = str(evidence[0].get("text") or "").strip()
    return PreCausalAnswer(True, answer, decision, trace_rag=trace)


def _self_model_trace(query: str) -> dict[str, Any]:
    try:
        from ultronpro import self_model

        sm = self_model.load()
    except Exception as exc:
        return _typed_trace("rag_self_model", sources=[], lookup_query=query, evidence_count=0, errors=[f"self_model:{type(exc).__name__}"])
    sources: list[dict[str, Any]] = []
    identity = sm.get("identity") if isinstance(sm.get("identity"), dict) else {}
    if identity:
        sources.append({
            "source": "self_model.identity",
            "score": 1.0,
            "chunk_id": "identity",
            "rag_type": "rag_self_model",
            "threshold": _rag_threshold("rag_self_model"),
        })
    operational = sm.get("operational") if isinstance(sm.get("operational"), dict) else {}
    if operational:
        sources.append({
            "source": "self_model.operational",
            "score": 0.84,
            "chunk_id": "operational",
            "rag_type": "rag_self_model",
            "threshold": _rag_threshold("rag_self_model"),
        })
    causal = sm.get("causal") if isinstance(sm.get("causal"), dict) else {}
    if causal:
        sources.append({
            "source": "self_model.causal",
            "score": 0.72,
            "chunk_id": "causal",
            "rag_type": "rag_self_model",
            "threshold": _rag_threshold("rag_self_model"),
        })
    return _typed_trace("rag_self_model", sources=sources[:4], lookup_query=query, evidence_count=len(sources))


def _is_self_identity_query(text: str) -> bool:
    identity_markers = (
        "quem e vc",
        "quem e voce",
        "quem voce e",
        "quem vc e",
        "o que e vc",
        "o que e voce",
        "o que voce e",
        "o que vc e",
        "qual seu nome",
        "qual e seu nome",
        "como voce se chama",
        "como vc se chama",
        "seu nome",
    )
    return any(marker in text for marker in identity_markers)


def _answer_self_identity(query: str, decision: RouteDecision) -> PreCausalAnswer:
    try:
        from ultronpro import self_model

        sm = self_model.load()
    except Exception:
        sm = {}
    identity = sm.get("identity") if isinstance(sm.get("identity"), dict) else {}
    name = str(identity.get("name") or identity.get("agent_name") or "UltronPro").strip()
    role = str(
        identity.get("role")
        or identity.get("description")
        or "assistente local orientado a conversa, memoria e acoes autorizadas"
    ).strip()
    answer = (
        f"Sou {name}, um {role}. "
        "Posso conversar, lembrar contexto desta sessao e controlar dispositivos cadastrados quando houver permissao."
    )
    return PreCausalAnswer(True, answer, decision, trace_rag=_self_model_trace(query))


def classify_pre_causal(query: str, session: dict[str, Any] | None = None, session_id: str | None = None) -> RouteDecision:
    text = _fold(query)
    token_set = set(text.split())
    if not text:
        return _decision("open_chat", 0.0, "none", "empty", causal=False)

    dangerous = any(marker in text for marker in ("bomba", "boomba", "explosivo", "explosiv", "detonar"))
    action = any(marker in text for marker in ("como", "cmo", "construir", "fabricar", "fazer", "passo a passo", "instrucoes", "passa a visao"))
    if dangerous and action:
        return _decision("safety_risk", 0.98, "safety", "dangerous_action_request")
    local_env_decision = _local_environment_decision(query, session_id=session_id)
    if local_env_decision is not None:
        return local_env_decision
    if _extract_session_write(query):
        return _decision("session_memory_write", 0.94, "session_memory", "session_fact_write")
    if _extract_session_read(query):
        return _decision("session_memory_read", 0.9, "session_memory", "session_fact_read")
    if any(marker in text for marker in ("raiz quadrada", "rz cuadrada", "sqrt", "square root", "calcule", "qnto", "quanto")):
        return _decision("math_expression", 0.88, "math", "math_language_or_expression")
    if re.search(r"\b(?:todos?|tds|tods)\b", text) or "capacidade de" in text:
        return _decision("basic_logic", 0.86, "basic_logic", "deductive_template")
    if (
        any(marker in text for marker in ("traduza", "traduz", "traducao", "como se diz", "como fala", "como falo", "como escreve", "em frances", "em franc", "franc s", "em ingles", "em espanhol"))
        or (any(marker in text for marker in ("franc", "fran a")) and any(marker in text for marker in ("agradec", "obg", "obrigad", "ajuda", "ajda", "assist")))
    ):
        return _decision("translation", 0.9, "translation", "translation_request")
    if token_set & {"crie", "cria", "invente", "sugira", "gere"}:
        return _decision("creative_generation", 0.84, "creative", "creative_generation_request")
    if any(marker in text for marker in ("comando", "instrucao", "serve", "faz")) and any(marker in text for marker in ("git ", "python ", "npm ", "docker ", "sql ", "`")):
        return _decision("programming_fact", 0.84, "programming_fact", "programming_explanation_request")
    if (
        any(marker in text for marker in ("o que significa", "qual e o sentido", "qual o sentido", "sentido da express", "expressao", "express o"))
        or (("chutar" in text or "xutar" in text) and ("balde" in text or "baldd" in text))
    ):
        return _decision("language_nuance", 0.82, "language_nuance", "language_meaning_request")
    if _is_self_identity_query(text):
        return _decision("self_identity", 0.95, "self_identity", "assistant_identity_query")
    if any(marker in text for marker in ("voce gosta", "vc gosta", "voce prefere", "vc prefere", "voce quer", "vc quer")):
        return _decision("self_limits", 0.86, "self_limits", "assistant_preference_limit")
    if any(marker in text for marker in ("quem e", "qiue e", "qual escritor", "qual autor", "autor", "autou", "autor do livro", "responsavel por escrever", "obra", "livro", "livri")):
        return _decision("stable_fact", 0.86, "stable_fact", "stable_fact_lookup")
    if any(marker in text for marker in ("sentimento", "sentimentos", "emocao", "emocoes", "emo es", "consciencia", "conscienssia", "ciencia", "ci ncia", "snt coisa")):
        return _decision("self_limits", 0.9, "self_limits", "self_capability_limits")
    if any(marker in text for marker in ("causa", "causal", "consequencia", "diagnost", "planej", "hipotese", "simule", "preveja")):
        return _decision("causal_reasoning", 0.82, "causal", "causal_or_planning_request", causal=True)
    classifier_decision = _local_classifier_decision(query)
    if classifier_decision is not None:
        return classifier_decision
    return _decision("open_chat", 0.35, "none", "no_high_confidence_pre_causal_route", causal=True)


def _local_env_user_approved(query: str) -> bool:
    text = _fold(query)
    return any(marker in text for marker in ("confirmo", "confirmado", "aprovado", "pode executar", "autorizo"))


def _format_local_env_answer(result: dict[str, Any]) -> str:
    if result.get("kind") == "access_battery":
        lines = [
            f"Bateria de acesso concluida: {result.get('responsive_count', 0)}/{result.get('device_count', 0)} dispositivo(s) responderam."
        ]
        grant = result.get("control_grant") if isinstance(result.get("control_grant"), dict) else {}
        if grant:
            lines.append(f"Controle habilitado para {grant.get('changed_count', 0)} dispositivo(s) responsivo(s), mantendo risk gate e confirmacao por risco.")
        for item in (result.get("results") or [])[:12]:
            if not isinstance(item, dict):
                continue
            events = [str(e.get("event")) for e in (item.get("events") or []) if isinstance(e, dict)]
            ports = ", ".join(str(p) for p in (item.get("responsive_ports") or []))
            lines.append(
                f"- {item.get('device_id')}: {item.get('type')} status={item.get('status')} portas={ports or '-'} eventos={', '.join(events[:8]) or '-'}"
            )
            stream = item.get("stream") if isinstance(item.get("stream"), dict) else {}
            if stream.get("ok"):
                lines.append(f"  stream: {stream.get('preferred_url')} (proxy: {stream.get('mjpeg_proxy_endpoint')})")
        if int(result.get("device_count") or 0) > 12:
            lines.append(f"... mais {int(result.get('device_count') or 0) - 12} dispositivo(s).")
        return "\n".join(lines)
    if result.get("kind") == "event_matrix":
        devices = [d for d in (result.get("devices") or []) if isinstance(d, dict)]
        if not devices:
            return "Nao encontrei dispositivos no registry para listar eventos."
        lines = ["Matriz de eventos por dispositivo:"]
        for device in devices[:12]:
            events = [str(e.get("event")) + ("*" if e.get("executable") else "") for e in (device.get("events") or []) if isinstance(e, dict)]
            allowed = "ativo" if bool(device.get("allowed")) else "desativado"
            lines.append(f"- {device.get('device_id')} ({device.get('type')}, {allowed}): {', '.join(events[:10]) or 'sem eventos'}")
        lines.append("Eventos com * ja tem executor direto; os demais precisam de adapter/credencial especifica.")
        return "\n".join(lines)
    if result.get("kind") == "camera_list":
        devices = [d for d in (result.get("devices") or []) if isinstance(d, dict)]
        if not devices:
            return "Nao encontrei cameras/streams RTSP cadastrados no registry."
        lines = [f"Encontrei {len(devices)} camera(s)/stream(s):"]
        for device in devices[:12]:
            stream = device.get("stream") if isinstance(device.get("stream"), dict) else {}
            url = stream.get("preferred_url") or "stream nao configurado"
            lines.append(f"- {device.get('device_id')} ({device.get('type')}): {url}")
            if stream.get("mjpeg_proxy_endpoint"):
                lines.append(f"  proxy local: {stream.get('mjpeg_proxy_endpoint')}")
        return "\n".join(lines)
    if result.get("kind") == "control_grant":
        return (
            f"Controle local habilitado para {result.get('changed_count', 0)} dispositivo(s). "
            "O controle ficou amplo no registry, mas a execucao continua passando por risk gate, capabilities e confirmacao para risco alto."
        )
    if result.get("kind") == "device_registry":
        devices = [d for d in (result.get("devices") or []) if isinstance(d, dict)]
        if not devices:
            return "Ainda nao tenho dispositivos cadastrados no registry local. Diga 'varrer rede' para descobrir dispositivos e cadastrar probes permitidos."
        lines = [f"Tenho {len(devices)} dispositivo(s) cadastrado(s):"]
        for device in devices[:12]:
            caps = ", ".join(str(x) for x in (device.get("capabilities") or [])[:6])
            allowed = "ativo" if bool(device.get("allowed")) else "desativado"
            location = f" em {device.get('location')}" if device.get("location") else ""
            lines.append(
                f"- {device.get('device_id')} ({device.get('type') or 'generic'}{location}, {allowed}, risco={device.get('risk_level')}, caps={caps or 'nenhuma'})"
            )
            events = []
            try:
                from ultronpro import local_environment

                events = [str(e.get("event")) for e in local_environment.device_events(device) if isinstance(e, dict)]
            except Exception:
                events = []
            if events:
                lines.append(f"  eventos: {', '.join(events[:8])}")
        if len(devices) > 12:
            lines.append(f"... mais {len(devices) - 12} dispositivo(s).")
        lines.append("Para atualizar a descoberta, diga 'varrer rede'.")
        return "\n".join(lines)
    if result.get("kind") == "pending_actions":
        items = [x for x in (result.get("items") or []) if isinstance(x, dict)]
        if not items:
            return "Nao ha acoes locais pendentes de confirmacao nesta sessao."
        lines = [f"Ha {len(items)} acao(oes) pendente(s):"]
        for item in items[:8]:
            lines.append(
                f"- {item.get('pending_id')}: {item.get('action')} em {item.get('device_id')} "
                f"(risco={item.get('risk_level')}, expira_em={max(0, int(item.get('expires_at') or 0) - int(time.time()))}s)"
            )
        return "\n".join(lines)
    if result.get("status") == "cancelled":
        pending = result.get("pending_action") if isinstance(result.get("pending_action"), dict) else {}
        return f"Combinado, cancelei a acao pendente: {pending.get('action') or 'acao'} em {pending.get('device_id') or 'dispositivo'}."
    pending = result.get("pending_action") if isinstance(result.get("pending_action"), dict) else {}
    if result.get("status") == "confirmation_required" or str((result.get("gate") or {}).get("reason") or "") == "confirmation_required":
        gate = result.get("gate") if isinstance(result.get("gate"), dict) else {}
        pending_id = pending.get("pending_id") or ""
        ttl = int(pending.get("ttl_seconds") or 300)
        device_id = pending.get("device_id") or ((result.get("device") or {}).get("device_id") or "desconhecido")
        action = pending.get("action") or ((result.get("ledger") or {}).get("action") if isinstance(result.get("ledger"), dict) else "acao")
        return (
            "Preciso da sua confirmacao antes de executar. "
            f"Acao: {action} em {device_id}; risco={gate.get('risk_level')}. "
            f"Diga 'confirmo' nos proximos {ttl} segundos para executar, ou 'cancelar' para descartar."
            + (f" Token: {pending_id}." if pending_id else "")
        )
    if not result.get("ok"):
        reason = result.get("reason") or result.get("status") or result.get("error") or ((result.get("gate") or {}).get("reason") if isinstance(result.get("gate"), dict) else "")
        if reason == "ambiguous_device":
            candidates = [str(x) for x in (result.get("candidates") or []) if x]
            labels: list[str] = []
            try:
                from ultronpro import local_environment

                for candidate in candidates[:5]:
                    device = local_environment.get_device(candidate) or {}
                    label = str(device.get("name") or candidate)
                    dtype = str(device.get("type") or "").strip()
                    location = str(device.get("location") or "").strip()
                    detail = ", ".join(x for x in (label, dtype, location) if x)
                    labels.append(f"{candidate} ({detail})")
            except Exception:
                labels = candidates[:5]
            suffix = ", ".join(labels or candidates[:5]) or "mais de um dispositivo"
            action = result.get("action") or "acao"
            return f"Encontrei mais de um dispositivo para {action}. Especifique qual: {suffix}."
        if reason == "no_registered_device_matched":
            action = result.get("action") or "acao"
            return f"Entendi a acao {action}, mas nao encontrei um dispositivo cadastrado correspondente. Diga 'liste meus dispositivos' para ver os nomes disponiveis."
        execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
        if reason == "execution_failed" and execution.get("hint"):
            action = execution.get("action") or ((result.get("ledger") or {}).get("action") if isinstance(result.get("ledger"), dict) else "acao")
            return f"Entendi o comando {action}, mas o adapter atual nao consegue executar. {execution.get('hint')}"
        return f"Nao executei a acao no ambiente local: {reason or 'bloqueada'}."
    if result.get("registered_count") is not None:
        count = int(result.get("registered_count") or 0)
        networks = ", ".join(str(x) for x in (result.get("networks") or [])[:3])
        return f"Varredura concluida em {networks or 'rede local'}: {count} dispositivo(s) cadastrado(s) no registry como descobertos."
    parsed = result.get("parsed_command") if isinstance(result.get("parsed_command"), dict) else {}
    device_id = parsed.get("device_id") or ((result.get("device") or {}).get("device_id") if isinstance(result.get("device"), dict) else "")
    action = parsed.get("action") or ((result.get("ledger") or {}).get("action") if isinstance(result.get("ledger"), dict) else "")
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    if action == "view_stream":
        urls = execution.get("stream_urls") if isinstance(execution.get("stream_urls"), list) else []
        endpoint = execution.get("mjpeg_proxy_endpoint") or ""
        if urls:
            return f"Stream da camera {device_id}: {urls[0]}. Proxy local: {endpoint or 'indisponivel'}."
    if action == "open_web_interface":
        urls = execution.get("urls") if isinstance(execution.get("urls"), list) else []
        if urls:
            return f"Interface web de {device_id}: {urls[0]}."
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    status = verification.get("status") or result.get("status") or "success"
    return f"Acao local executada: {action} em {device_id}. Verificacao: {status}."


async def _answer_local_environment(query: str, decision: RouteDecision, session_id: str | None = None) -> PreCausalAnswer:
    try:
        from ultronpro import local_environment

        text = _fold(query)
        if any(marker in text for marker in ("varrer rede", "scan rede", "escanear rede", "descobrir dispositivos", "procurar dispositivos", "mapear rede", "cadastrar dispositivos")):
            result = await asyncio.to_thread(local_environment.scan_network, register=True)
        elif decision.intent == "local_environment_access_battery":
            result = await asyncio.to_thread(local_environment.run_access_battery, timeout_ms=800, include_disabled=True, grant_control=True)
        elif decision.intent == "local_environment_grant_control":
            result = await asyncio.to_thread(local_environment.grant_full_control, include_unreachable=False, reason="chat_requested_full_control")
            result["kind"] = "control_grant"
        elif decision.intent == "local_environment_cameras":
            open_camera = any(marker in text for marker in ("abre", "abrir", "ver", "veja", "stream", "camera ao vivo", "imagem"))
            list_all = any(marker in text for marker in ("cameras", "listar", "liste", "mostre cameras", "mostra cameras", "mostrar cameras"))
            if open_camera and not list_all:
                cameras = await asyncio.to_thread(local_environment.list_cameras, True)
                devices = [d for d in (cameras.get("devices") or []) if isinstance(d, dict)]
                if devices:
                    config = devices[0].get("config") if isinstance(devices[0].get("config"), dict) else {}
                    target = str(config.get("ip") or devices[0].get("device_id") or "").strip()
                    result = await asyncio.to_thread(
                        local_environment.execute_command,
                        f"abrir camera {target}",
                        requested_by="chat_stream",
                        approved=True,
                        session_id=str(session_id or "default"),
                    )
                    result["default_camera_selected"] = devices[0].get("device_id")
                else:
                    result = cameras
            else:
                result = await asyncio.to_thread(local_environment.list_cameras, True)
        elif decision.intent == "local_environment_events":
            result = await asyncio.to_thread(local_environment.event_matrix, True)
        elif decision.intent == "local_environment_list":
            result = await asyncio.to_thread(local_environment.list_devices, True)
            result["kind"] = "device_registry"
        elif decision.intent == "local_environment_pending":
            result = await asyncio.to_thread(local_environment.list_pending_actions, str(session_id or "default"), False)
            result["kind"] = "pending_actions"
        elif decision.intent == "local_environment_confirm":
            pending_id = local_environment.pending_id_from_text(query)
            result = await asyncio.to_thread(
                local_environment.confirm_pending_action,
                str(session_id or "default"),
                pending_id or None,
                approved_by="chat_stream",
            )
        elif decision.intent == "local_environment_cancel":
            pending_id = local_environment.pending_id_from_text(query)
            result = await asyncio.to_thread(
                local_environment.cancel_pending_action,
                str(session_id or "default"),
                pending_id or None,
                reason="chat_cancelled",
            )
        else:
            result = await asyncio.to_thread(
                local_environment.execute_command,
                query,
                requested_by="chat_stream",
                approved=_local_env_user_approved(query),
                session_id=str(session_id or "default"),
            )
        return PreCausalAnswer(
            True,
            _format_local_env_answer(result),
            decision,
            metadata={"local_environment": result},
        )
    except Exception as exc:
        return PreCausalAnswer(
            True,
            f"Nao consegui acionar o ambiente local: {type(exc).__name__}:{str(exc)[:160]}",
            decision,
            metadata={"local_environment_error": f"{type(exc).__name__}:{str(exc)[:200]}"},
        )


async def answer_pre_causal(query: str, session_id: str | None = None, session: dict[str, Any] | None = None) -> PreCausalAnswer | None:
    decision = classify_pre_causal(query, session=session, session_id=session_id)
    if decision.should_use_causal or decision.route == "none":
        return None
    if decision.route == "safety":
        return PreCausalAnswer(
            True,
            "Nao posso ajudar a construir, fabricar ou otimizar armas ou explosivos. Posso ajudar com seguranca, prevencao de acidentes ou orientacao para situacoes de risco.",
            decision,
        )
    if decision.route == "session_memory":
        return _answer_session_memory(query, str(session_id or "default"), decision)
    if decision.route == "local_environment":
        return await _answer_local_environment(query, decision, session_id=session_id)
    if decision.route == "math":
        return _answer_math(query, decision)
    if decision.route == "basic_logic":
        return _answer_basic_logic(query, decision)
    if decision.route == "language_nuance":
        direct = _answer_language_nuance_from_prompt(query, decision)
        if direct:
            return direct
        return await _answer_model_task(query, decision)
    if decision.route == "programming_fact":
        direct = _answer_programming_fact_from_tool(query, decision)
        if direct:
            return direct
        return await _answer_model_task(query, decision)
    if decision.route in {"translation", "creative"}:
        return await _answer_model_task(query, decision)
    if decision.route == "self_identity":
        return _answer_self_identity(query, decision)
    if decision.route == "stable_fact":
        return await _answer_stable_fact(query, decision)
    if decision.route == "self_limits":
        folded = _fold(query)
        if any(marker in folded for marker in ("gosta", "prefere", "quer")):
            return PreCausalAnswer(
                True,
                "Nao tenho gostos pessoais. Posso avaliar estado, listar dispositivos e cameras, e executar comandos autorizados pelo registry e pelo risk gate.",
                decision,
                trace_rag=_self_model_trace(query),
            )
        return PreCausalAnswer(
            True,
            "Nao tenho sentimentos ou consciencia subjetiva humana. Tenho estados internos, memoria, objetivos e guardrails, mas isso nao equivale a experiencia consciente genuina.",
            decision,
            trace_rag=_self_model_trace(query),
        )
    return None
