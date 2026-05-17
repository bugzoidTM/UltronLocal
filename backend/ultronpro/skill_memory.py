from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from threading import RLock
from typing import Any


logger = logging.getLogger("uvicorn")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_SKILLS_DIR = DATA_DIR / "learned_skills"
_LOCK = RLock()


def _enabled() -> bool:
    return str(os.getenv("ULTRON_SKILL_MEMORY_ENABLED", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}


def _db_path(db_path: str | Path | None = None) -> Path:
    if db_path:
        return Path(db_path)
    raw = str(os.getenv("ULTRON_SKILL_MEMORY_DB_PATH", "") or "").strip()
    if raw:
        return Path(raw)
    try:
        from ultronpro import store

        return Path(getattr(store.db, "path", getattr(store, "DB_PATH", DATA_DIR / "ultron.db")))
    except Exception:
        return DATA_DIR / "ultron.db"


def _skills_dir(skills_dir: str | Path | None = None) -> Path:
    raw = str(os.getenv("ULTRON_SKILL_MEMORY_DIR", "") or "").strip()
    return Path(skills_dir or raw or DEFAULT_SKILLS_DIR)


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> float:
    return time.time()


def _normalize(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9_\s-]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _tokens(text: str) -> set[str]:
    stop = {"que", "para", "com", "uma", "uns", "das", "dos", "por", "the", "and", "from"}
    return {t for t in re.findall(r"[a-z0-9_]{2,}", _normalize(text)) if t not in stop}


def _trigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", " ", _normalize(text))
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[i : i + 3] for i in range(len(compact) - 2)}


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalize(text)).strip("-")
    return slug[:80] or hashlib.sha256(str(text).encode("utf-8", errors="ignore")).hexdigest()[:16]


def ensure_schema(db_path: str | Path | None = None) -> dict[str, Any]:
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learned_skills(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              name TEXT NOT NULL UNIQUE,
              title TEXT NOT NULL,
              summary TEXT NOT NULL,
              when_to_use TEXT,
              instructions TEXT,
              action_kind TEXT,
              status TEXT NOT NULL DEFAULT 'candidate',
              tags_json TEXT,
              examples_json TEXT,
              success_count INTEGER NOT NULL DEFAULT 0,
              failure_count INTEGER NOT NULL DEFAULT 0,
              confidence REAL NOT NULL DEFAULT 0.0,
              source TEXT,
              skill_path TEXT,
              content TEXT,
              metadata_json TEXT,
              last_used_at REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learned_skills_name ON learned_skills(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learned_skills_status ON learned_skills(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learned_skills_action ON learned_skills(action_kind)")
        fts_ok = True
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS learned_skills_fts USING fts5(
                  skill_id UNINDEXED,
                  name,
                  title,
                  summary,
                  when_to_use,
                  instructions,
                  content,
                  examples,
                  tags
                )
                """
            )
        except Exception as exc:
            fts_ok = False
            logger.debug("learned skill FTS disabled: %s", exc)
        return {"ok": True, "db_path": str(_db_path(db_path)), "fts": fts_ok}


def _sync_fts(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    try:
        conn.execute("DELETE FROM learned_skills_fts WHERE skill_id=?", (int(row["id"]),))
        conn.execute(
            """
            INSERT INTO learned_skills_fts(skill_id, name, title, summary, when_to_use, instructions, content, examples, tags)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                int(row["id"]),
                str(row.get("name") or ""),
                str(row.get("title") or ""),
                str(row.get("summary") or ""),
                str(row.get("when_to_use") or ""),
                str(row.get("instructions") or ""),
                str(row.get("content") or ""),
                str(row.get("examples_json") or ""),
                str(row.get("tags_json") or ""),
            ),
        )
    except Exception:
        pass


def _write_skill_files(row: dict[str, Any], skills_dir: str | Path | None = None) -> tuple[str, str]:
    root = _skills_dir(skills_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = str(row.get("name") or "learned-skill")
    md_path = root / f"{name}.md"
    meta_path = root / f"{name}.meta.json"
    examples = _json_loads(str(row.get("examples_json") or ""), [])
    tags = _json_loads(str(row.get("tags_json") or ""), [])
    metadata = _json_loads(str(row.get("metadata_json") or ""), {})
    example_lines = []
    for item in examples[-8:]:
        q = str((item or {}).get("query") or "").strip()
        if q:
            example_lines.append(f"- {q[:180]}")
    if not example_lines:
        example_lines.append("- Sem exemplos suficientes ainda.")
    content = (
        f"# {row.get('title') or name}\n\n"
        "## Resumo curto\n"
        f"{row.get('summary') or ''}\n\n"
        "## Quando usar\n"
        f"{row.get('when_to_use') or ''}\n\n"
        "## Instrucoes\n"
        f"{row.get('instructions') or ''}\n\n"
        "## Acao reutilizavel\n"
        f"- action_kind: {row.get('action_kind') or 'unknown'}\n"
        f"- status: {row.get('status') or 'candidate'}\n"
        f"- confidence: {float(row.get('confidence') or 0):.3f}\n\n"
        "## Exemplos observados\n"
        + "\n".join(example_lines)
        + "\n"
    )
    meta = {
        "name": name,
        "title": row.get("title") or name,
        "summary": row.get("summary") or "",
        "tags": tags,
        "language": "pt-BR",
        "source_skill_path": str(md_path),
        "status": row.get("status") or "candidate",
        "action_kind": row.get("action_kind") or "",
        "success_count": int(row.get("success_count") or 0),
        "failure_count": int(row.get("failure_count") or 0),
        "confidence": float(row.get("confidence") or 0),
        "created_at": float(row.get("created_at") or 0),
        "updated_at": float(row.get("updated_at") or 0),
        "version": int(metadata.get("version") or 1),
    }
    md_path.write_text(content, encoding="utf-8")
    meta_path.write_text(_json_dumps(meta), encoding="utf-8")
    return str(md_path), str(meta_path)


def _row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["tags"] = _json_loads(data.get("tags_json"), [])
    data["examples"] = _json_loads(data.get("examples_json"), [])
    data["metadata"] = _json_loads(data.get("metadata_json"), {})
    return data


def _skill_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("name", "title", "summary", "when_to_use", "instructions", "content", "examples_json", "tags_json")
    )


def _score(query: str, row: dict[str, Any]) -> float:
    q_norm = _normalize(query)
    doc = _skill_text(row)
    doc_norm = _normalize(doc)
    q_tokens = _tokens(q_norm)
    doc_tokens = _tokens(doc_norm)
    overlap = len(q_tokens & doc_tokens)
    token_score = overlap / max(1, min(len(q_tokens), max(1, len(doc_tokens))))
    q_tri = _trigrams(q_norm)
    doc_tri = _trigrams(doc_norm)
    tri_score = len(q_tri & doc_tri) / max(1, len(q_tri | doc_tri))
    phrase_score = 0.25 if q_norm and q_norm in doc_norm else 0.0
    confidence = max(0.0, min(1.0, float(row.get("confidence") or 0.0)))
    status_bonus = 0.08 if str(row.get("status") or "") == "promoted" else 0.0
    return min(1.0, (token_score * 0.48) + (tri_score * 0.24) + phrase_score + (confidence * 0.12) + status_bonus)


def upsert_skill(
    *,
    name: str,
    title: str,
    summary: str,
    when_to_use: str = "",
    instructions: str = "",
    action_kind: str = "",
    status: str = "candidate",
    tags: list[str] | None = None,
    examples: list[dict[str, Any]] | None = None,
    success_count: int = 0,
    failure_count: int = 0,
    confidence: float = 0.0,
    source: str = "",
    metadata: dict[str, Any] | None = None,
    content: str = "",
    db_path: str | Path | None = None,
    skills_dir: str | Path | None = None,
) -> dict[str, Any]:
    ensure_schema(db_path)
    now = _now()
    name = _slug(name)
    tags_json = _json_dumps(list(dict.fromkeys(tags or [])))
    examples_json = _json_dumps((examples or [])[-20:])
    metadata_json = _json_dumps(metadata or {})
    with _LOCK, _connect(db_path) as conn:
        existing = conn.execute("SELECT * FROM learned_skills WHERE name=?", (name,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE learned_skills
                SET updated_at=?, title=?, summary=?, when_to_use=?, instructions=?, action_kind=?,
                    status=?, tags_json=?, examples_json=?, success_count=?, failure_count=?,
                    confidence=?, source=?, content=?, metadata_json=?
                WHERE name=?
                """,
                (
                    now,
                    title,
                    summary,
                    when_to_use,
                    instructions,
                    action_kind,
                    status,
                    tags_json,
                    examples_json,
                    int(success_count),
                    int(failure_count),
                    float(confidence),
                    source,
                    content,
                    metadata_json,
                    name,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO learned_skills(
                  created_at, updated_at, name, title, summary, when_to_use, instructions,
                  action_kind, status, tags_json, examples_json, success_count, failure_count,
                  confidence, source, content, metadata_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    now,
                    now,
                    name,
                    title,
                    summary,
                    when_to_use,
                    instructions,
                    action_kind,
                    status,
                    tags_json,
                    examples_json,
                    int(success_count),
                    int(failure_count),
                    float(confidence),
                    source,
                    content,
                    metadata_json,
                ),
            )
        row = conn.execute("SELECT * FROM learned_skills WHERE name=?", (name,)).fetchone()
        data = _row_to_dict(row)
        skill_path, meta_path = _write_skill_files(data, skills_dir=skills_dir)
        conn.execute("UPDATE learned_skills SET skill_path=? WHERE id=?", (skill_path, int(data["id"])))
        data["skill_path"] = skill_path
        _sync_fts(conn, data)
        data["meta_path"] = meta_path
        return data


def _action_profile(strategy: str) -> dict[str, str] | None:
    low = str(strategy or "").strip().lower()
    if low.startswith("intent_"):
        intent = low.removeprefix("intent_")
        title = f"Chat intent {intent}"
        return {
            "name": f"chat-{low.replace('_', '-')}",
            "title": title,
            "summary": f"Reconhecer e resolver rapidamente interacoes de chat do tipo {intent}.",
            "when_to_use": "Quando a mensagem do usuario se parece com exemplos anteriores bem-sucedidos dessa intencao.",
            "instructions": "Classifique a mensagem pela skill aprendida, responda por rota deterministica e registre o episodio. Use LLM apenas se a skill nao tiver confianca suficiente.",
            "action_kind": low,
        }
    if low.startswith("skill_"):
        skill = low.removeprefix("skill_")
        return {
            "name": f"chat-route-{low.replace('_', '-')}",
            "title": f"Reutilizar skill {skill}",
            "summary": f"Roteamento aprendido para reutilizar a skill {skill} antes de RAG/LLM.",
            "when_to_use": "Quando a tarefa atual combina com exemplos anteriores que foram resolvidos por essa skill.",
            "instructions": f"Consultar e executar a skill {skill}; se falhar, continuar o pipeline cognitivo normal.",
            "action_kind": low,
        }
    return None


def learn_from_chat_turn(
    query: str,
    answer: str,
    *,
    strategy: str,
    ok: bool = True,
    latency_ms: int = 0,
    source: str = "chat",
    meta: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
    skills_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not _enabled():
        return {"ok": False, "reason": "disabled"}
    if not ok or not str(query or "").strip() or not str(answer or "").strip():
        return {"ok": False, "reason": "not_learnable"}
    profile = _action_profile(strategy)
    if not profile:
        return {"ok": False, "reason": "strategy_not_reusable"}

    ensure_schema(db_path)
    name = _slug(profile["name"])
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM learned_skills WHERE name=?", (name,)).fetchone()
    if row:
        current = _row_to_dict(row)
        examples = current.get("examples") or []
        success_count = int(current.get("success_count") or 0) + 1
        failure_count = int(current.get("failure_count") or 0)
    else:
        current = {}
        examples = []
        success_count = 1
        failure_count = 0

    q_norm = _normalize(query)
    if q_norm and all(_normalize(item.get("query") or "") != q_norm for item in examples):
        examples.append(
            {
                "query": str(query or "")[:360],
                "answer_summary": str(answer or "")[:360],
                "strategy": str(strategy or ""),
                "source": str(source or "chat"),
                "latency_ms": int(latency_ms or 0),
                "created_at": _now(),
            }
        )
    examples = examples[-20:]
    promote_after = max(1, int(os.getenv("ULTRON_SKILL_MEMORY_PROMOTE_SUCCESSES", "2") or 2))
    status = "promoted" if success_count >= promote_after else "candidate"
    confidence = min(0.96, max(float(current.get("confidence") or 0.0), 0.34 + (success_count * 0.13) - (failure_count * 0.08)))
    tags = list(
        dict.fromkeys(
            [
                "chat",
                "learned",
                "autoreflex",
                str(profile["action_kind"]),
                str(source or "chat"),
                "pt-BR",
            ]
        )
    )
    data = upsert_skill(
        name=name,
        title=profile["title"],
        summary=profile["summary"],
        when_to_use=profile["when_to_use"],
        instructions=profile["instructions"],
        action_kind=profile["action_kind"],
        status=status,
        tags=tags,
        examples=examples,
        success_count=success_count,
        failure_count=failure_count,
        confidence=confidence,
        source=source,
        metadata={"last_strategy": strategy, "last_meta": meta or {}, "version": 1},
        db_path=db_path,
        skills_dir=skills_dir,
    )
    try:
        from ultronpro import store

        payload = {
            "skill": data.get("name"),
            "status": data.get("status"),
            "action_kind": data.get("action_kind"),
            "confidence": data.get("confidence"),
            "source": source,
        }
        store.publish_workspace("skill_memory", "skill.learned", _json_dumps(payload), salience=0.58, ttl_sec=1800)
    except Exception:
        pass

    # Hook automático: quando uma skill é promovida, aciona a bridge imediatamente
    # para materializar o SKILL.md sem esperar o próximo ciclo periódico.
    if status == "promoted":
        try:
            from ultronpro import skill_memory_bridge
            skill_memory_bridge.run_bridge(dry_run=False, limit=10)
        except Exception:
            pass

    return {"ok": True, "skill": data}


def search(
    query: str,
    *,
    limit: int = 5,
    include_candidates: bool = True,
    min_score: float | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    if not _enabled() or not str(query or "").strip():
        return []
    ensure_schema(db_path)
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM learned_skills ORDER BY updated_at DESC LIMIT 1000"
        ).fetchall()
    results: list[dict[str, Any]] = []
    threshold = 0.0 if min_score is None else float(min_score)
    for row in rows:
        data = _row_to_dict(row)
        if not include_candidates and str(data.get("status") or "") != "promoted":
            continue
        score = _score(query, data)
        if score < threshold:
            continue
        data["score"] = round(float(score), 4)
        results.append(data)
    results.sort(key=lambda item: (float(item.get("score") or 0), float(item.get("confidence") or 0)), reverse=True)
    return results[: max(1, min(25, int(limit or 5)))]


def deterministic_chat_intent(query: str, *, db_path: str | Path | None = None) -> dict[str, Any] | None:
    threshold = float(os.getenv("ULTRON_SKILL_MEMORY_INTENT_THRESHOLD", "0.42") or 0.42)
    use_candidates = str(os.getenv("ULTRON_SKILL_MEMORY_USE_CANDIDATES", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    for item in search(query, limit=3, include_candidates=use_candidates, min_score=threshold, db_path=db_path):
        action_kind = str(item.get("action_kind") or "")
        if action_kind in {"intent_greeting", "intent_thanks"}:
            intent = action_kind.removeprefix("intent_")
            try:
                with _LOCK, _connect(db_path) as conn:
                    conn.execute("UPDATE learned_skills SET last_used_at=? WHERE id=?", (_now(), int(item["id"])))
            except Exception:
                pass
            return {
                "intent": intent,
                "skill": item.get("name"),
                "score": item.get("score"),
                "confidence": item.get("confidence"),
                "status": item.get("status"),
            }
    return None


def get_skill(name: str, *, db_path: str | Path | None = None) -> dict[str, Any] | None:
    ensure_schema(db_path)
    key = _slug(name)
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM learned_skills WHERE name=? OR skill_path=?", (key, str(name or ""))).fetchone()
    return _row_to_dict(row) if row else None


def resolve_skill_path(skill_path: str | Path, *, skills_dir: str | Path | None = None) -> Path:
    root = _skills_dir(skills_dir).resolve()
    raw = Path(skill_path)
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("skill path outside learned skill memory")
    return candidate


def get_skill_content(skill_path: str | Path, *, skills_dir: str | Path | None = None) -> str:
    path = resolve_skill_path(skill_path, skills_dir=skills_dir)
    return path.read_text(encoding="utf-8")


def index_skill_file(path: str | Path, *, db_path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    content = p.read_text(encoding="utf-8")
    title = p.stem
    for line in content.splitlines():
        if line.strip().startswith("#"):
            title = line.strip().lstrip("#").strip() or title
            break
    summary = " ".join(line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#"))[:260]
    return upsert_skill(
        name=p.stem,
        title=title,
        summary=summary or title,
        when_to_use="Skill Markdown importada e pesquisavel pela memoria operacional.",
        instructions="Consultar o conteudo da skill antes de acionar raciocinio caro.",
        action_kind="skill_markdown",
        status="promoted",
        tags=["markdown", "autoreflex", "imported"],
        examples=[],
        confidence=0.72,
        source="skill_memory.index",
        content=content,
        db_path=db_path,
        skills_dir=None,
    )


def index_all(*, skills_dir: str | Path | None = None, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    root = _skills_dir(skills_dir)
    if not root.exists():
        return []
    indexed = []
    for path in root.glob("*.md"):
        indexed.append(index_skill_file(path, db_path=db_path))
    return indexed


def ensure_autoreflex_base_skill(*, db_path: str | Path | None = None, skills_dir: str | Path | None = None) -> dict[str, Any]:
    return upsert_skill(
        name="criar-skills-operacionais",
        title="Criar skills operacionais",
        summary="Transformar interacoes uteis em skills Markdown pequenas, indexadas e reutilizaveis.",
        when_to_use="Quando um problema, rota de chat ou correcao for reutilizavel e puder economizar LLM no futuro.",
        instructions=(
            "Use contexto de sessao e episodios primeiro; pesquise skill_memory; se uma skill resolver, reutilize; "
            "se a solucao nova for repetivel, crie/atualize uma skill candidata; promova apenas apos sucesso observado."
        ),
        action_kind="skill_memory_policy",
        status="promoted",
        tags=["autoreflex", "skill-memory", "procedural", "pt-BR"],
        examples=[],
        success_count=1,
        confidence=0.78,
        source="autoreflex_adaptation",
        db_path=db_path,
        skills_dir=skills_dir,
    )


def status(*, db_path: str | Path | None = None) -> dict[str, Any]:
    schema = ensure_schema(db_path)
    with _LOCK, _connect(db_path) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM learned_skills").fetchone()[0])
        promoted = int(conn.execute("SELECT COUNT(*) FROM learned_skills WHERE status='promoted'").fetchone()[0])
        candidates = int(conn.execute("SELECT COUNT(*) FROM learned_skills WHERE status='candidate'").fetchone()[0])
    return {
        "ok": True,
        "enabled": _enabled(),
        "db_path": schema.get("db_path"),
        "skills_dir": str(_skills_dir()),
        "total": total,
        "promoted": promoted,
        "candidates": candidates,
        "fts": schema.get("fts"),
    }
