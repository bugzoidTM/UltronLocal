"""
Skill Memory Bridge — Ponte skill_memory → skill_evolution
===========================================================

Converte skills promovidas do skill_memory (SQLite + learned_skills/)
em SKILL.md carregáveis pelo skill_loader e executáveis pelo skill_executor.

Fecha o ciclo:
  skill_memory (SQLite, promovida) → validação mínima → SKILL.md
  → skill_loader.load_skills(force=True) → skill_executor executa

Critérios mínimos para materialização (configuráveis via env):
  ULTRON_BRIDGE_MIN_SUCCESS    = 3     (success_count mínimo)
  ULTRON_BRIDGE_MIN_CONFIDENCE = 0.60  (confidence mínimo)

Uso:
  from ultronpro import skill_memory_bridge
  result = skill_memory_bridge.run_bridge(dry_run=True)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("uvicorn")

# ── Configuração ───────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BRIDGE_LOG_PATH = DATA_DIR / "skill_memory_bridge_log.jsonl"

# Diretório alvo: mesmo usado por skill_evolution._materialize()
MATERIALIZED_SKILLS_DIR = Path(__file__).resolve().parent.parent / "ultron_skills"


def _min_success() -> int:
    return max(1, int(os.getenv("ULTRON_BRIDGE_MIN_SUCCESS", "3") or 3))


def _min_confidence() -> float:
    return max(0.0, min(1.0, float(os.getenv("ULTRON_BRIDGE_MIN_CONFIDENCE", "0.60") or 0.60)))


def _now() -> int:
    return int(time.time())


def _slug(text: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return (re.sub(r"_+", "_", raw) or "skill")[:60].strip("_")


# ── 1. Listar skills promovidas ────────────────────────────────────────────────

def list_promoted_memory_skills(
    *,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Retorna todas as skills com status='promoted' do skill_memory (SQLite).
    """
    try:
        from ultronpro import skill_memory
        skill_memory.ensure_schema(db_path)
        import sqlite3
        # Reutiliza a lógica interna de conexão
        conn_path = skill_memory._db_path(db_path)
        conn = sqlite3.connect(str(conn_path), timeout=30)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM learned_skills WHERE status='promoted' ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
        return [skill_memory._row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"SkillMemoryBridge: list_promoted_memory_skills error: {e}")
        return []


# ── 2. Validar candidata à materialização ─────────────────────────────────────

def validate_memory_skill_for_materialization(
    skill: dict[str, Any],
    *,
    min_success: int | None = None,
    min_confidence: float | None = None,
) -> dict[str, Any]:
    """
    Verifica se uma skill do skill_memory atende aos critérios mínimos
    para ser materializada como SKILL.md executável.

    Retorna {'ok': True/False, 'reason': str, 'checks': list}.
    """
    checks: list[dict[str, Any]] = []
    min_s = min_success if min_success is not None else _min_success()
    min_c = min_confidence if min_confidence is not None else _min_confidence()

    def _check(name: str, passed: bool, detail: str) -> bool:
        checks.append({"check": name, "passed": passed, "detail": detail})
        return passed

    # 1. Status promovido
    status = str(skill.get("status") or "")
    ok = _check("status_promoted", status == "promoted", f"status={status}")

    # 2. success_count suficiente
    sc = int(skill.get("success_count") or 0)
    ok = _check("min_success_count", sc >= min_s, f"success_count={sc} >= {min_s}") and ok

    # 3. confidence suficiente
    conf = float(skill.get("confidence") or 0.0)
    ok = _check("min_confidence", conf >= min_c, f"confidence={conf:.3f} >= {min_c}") and ok

    # 4. Descrição/summary não vazia
    summary = str(skill.get("summary") or "").strip()
    ok = _check("has_summary", bool(summary), f"summary={'present' if summary else 'missing'}") and ok

    # 5. Nome não vazio
    name = str(skill.get("name") or "").strip()
    ok = _check("has_name", bool(name), f"name={'present' if name else 'missing'}") and ok

    # 6. Sem regressão grave registrada (failure_count não pode dominar)
    fc = int(skill.get("failure_count") or 0)
    total = sc + fc
    failure_rate = fc / max(1, total)
    ok = _check(
        "low_failure_rate",
        failure_rate < 0.5,
        f"failure_rate={failure_rate:.2f} (failures={fc}, successes={sc})",
    ) and ok

    if not ok:
        first_fail = next((c for c in checks if not c["passed"]), None)
        reason = first_fail["check"] if first_fail else "unknown"
    else:
        reason = "all_checks_passed"

    return {"ok": ok, "reason": reason, "checks": checks, "skill_name": name}


# ── 3. Materializar SKILL.md ──────────────────────────────────────────────────

def _build_skill_md(skill: dict[str, Any]) -> str:
    """Gera o conteúdo SKILL.md com frontmatter compatível com skill_loader."""
    name = str(skill.get("name") or "skill")
    title = str(skill.get("title") or name)
    summary = str(skill.get("summary") or "")
    when_to_use = str(skill.get("when_to_use") or "").strip()
    instructions = str(skill.get("instructions") or "").strip()
    action_kind = str(skill.get("action_kind") or "learned")
    tags: list[str] = list(skill.get("tags") or [])

    # Garante tags obrigatórias
    for tag in ["memory_bridge", "learned", action_kind]:
        if tag and tag not in tags:
            tags.append(tag)

    tags_yaml = "\n".join(f'  - "{t}"' for t in tags[:12])

    # when_to_use como bloco YAML
    when_lines = "\n".join(f"  {line}" for line in when_to_use.splitlines()) if when_to_use else "  Consulte skill_memory para correspondência semântica."

    frontmatter = (
        "---\n"
        "path: auto/memory_bridge\n"
        f'description: "{summary[:200]}"\n'
        "allowed_tools: []\n"
        "budget:\n"
        "  max_seconds: 3\n"
        "risk_level: low\n"
        "when_to_use: |\n"
        f"{when_lines}\n"
        "success_checks: []\n"
        "tags:\n"
        f"{tags_yaml}\n"
        "enabled: true\n"
        "version: 1.0.0\n"
        "author: skill_memory_bridge\n"
        "---\n\n"
    )

    body = (
        f"# {title}\n\n"
        f"{summary}\n\n"
    )
    if instructions:
        body += f"## Instruções\n\n{instructions}\n\n"

    # Exemplos observados
    examples: list[dict] = list(skill.get("examples") or [])
    if examples:
        body += "## Exemplos observados\n\n"
        for ex in examples[-5:]:
            q = str(ex.get("query") or "").strip()
            if q:
                body += f"- {q[:200]}\n"
        body += "\n"

    body += (
        f"*Materializada automaticamente via skill_memory_bridge "
        f"a partir de skill_memory '{name}' "
        f"(success_count={skill.get('success_count', 0)}, "
        f"confidence={float(skill.get('confidence') or 0):.3f}).*\n"
    )

    return frontmatter + body


def materialize_memory_skill_as_skill_md(
    skill: dict[str, Any],
    *,
    skills_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Converte uma skill do skill_memory em SKILL.md no MATERIALIZED_SKILLS_DIR.

    O nome do diretório é prefixado com 'mem_' para distinguir de skills
    geradas pelo skill_evolution (prefixo 'auto_').

    Retorna {'ok': bool, 'path': str, 'skill_name': str}.
    """
    name = str(skill.get("name") or "")
    if not name:
        return {"ok": False, "reason": "empty_name"}

    root = Path(skills_dir) if skills_dir else MATERIALIZED_SKILLS_DIR
    skill_dir_name = f"mem_{_slug(name)}"
    skill_dir = root / skill_dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"
    try:
        content = _build_skill_md(skill)
        skill_file.write_text(content, encoding="utf-8")
        logger.info(f"SkillMemoryBridge: Materializado {skill_dir_name} → {skill_file}")
        return {
            "ok": True,
            "path": str(skill_file),
            "skill_dir": skill_dir_name,
            "skill_name": skill_dir_name,
        }
    except Exception as e:
        logger.error(f"SkillMemoryBridge: Erro ao materializar {name}: {e}")
        return {"ok": False, "reason": str(e), "skill_name": name}


# ── 4. Recarregar skill_loader ─────────────────────────────────────────────────

def reload_skill_loader() -> dict[str, Any]:
    """Força recarga do skill_loader após materialização."""
    try:
        from ultronpro import skill_loader
        skills = skill_loader.load_skills(force=True)
        return {"ok": True, "loaded_count": len(skills)}
    except Exception as e:
        logger.warning(f"SkillMemoryBridge: reload_skill_loader error: {e}")
        return {"ok": False, "error": str(e)}


# ── 5. Registrar evento ────────────────────────────────────────────────────────

def record_bridge_event(
    skill_name: str,
    result: dict[str, Any],
    *,
    action: str = "materialize",
) -> None:
    """Grava evento no log JSONL persistente."""
    entry = {
        "ts": _now(),
        "action": action,
        "skill_name": skill_name,
        **{k: v for k, v in result.items() if k in ("ok", "reason", "path", "skill_dir")},
    }
    try:
        BRIDGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with BRIDGE_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"SkillMemoryBridge: record_bridge_event failed: {e}")


# ── 6. Pipeline completo ───────────────────────────────────────────────────────

def run_bridge(
    *,
    dry_run: bool = False,
    min_success: int | None = None,
    min_confidence: float | None = None,
    db_path: str | Path | None = None,
    skills_dir: str | Path | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Pipeline completo: list promoted → validate → materialize → reload.
    """
    lock_file = BRIDGE_LOG_PATH.with_suffix(".lock")

    # Garante que o diretório existe (ambiente limpo sem data/)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    def _try_acquire_lock() -> bool:
        """Tenta criar lock file atomicamente. Retorna True se adquiriu."""
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            return False

    if not _try_acquire_lock():
        # Lock já existe: verificar se é órfão (> 5 minutos)
        if lock_file.exists() and time.time() - lock_file.stat().st_mtime > 300:
            logger.warning("skill_memory_bridge: removendo lock orfao antigo")
            try:
                lock_file.unlink()
            except Exception:
                pass
            # Re-tenta adquirir na mesma chamada após remoção do órfão
            if not _try_acquire_lock():
                return {"ok": True, "skipped": True, "reason": "bridge_already_running"}
        else:
            return {"ok": True, "skipped": True, "reason": "bridge_already_running"}

    try:
        started = _now()
        promoted = list_promoted_memory_skills(db_path=db_path)[:limit]
        details: list[dict[str, Any]] = []
        materialized = 0
        would_materialize = 0
        skipped = 0
        failed = 0

        for skill in promoted:
            name = str(skill.get("name") or "")
            validation = validate_memory_skill_for_materialization(
                skill,
                min_success=min_success,
                min_confidence=min_confidence,
            )

            if not validation["ok"]:
                skipped += 1
                details.append({
                    "skill_name": name,
                    "action": "skipped",
                    "reason": validation["reason"],
                    "checks": validation["checks"],
                })
                continue

            if dry_run:
                would_materialize += 1
                details.append({
                    "skill_name": name,
                    "action": "would_materialize",
                    "dry_run": True,
                    "checks": validation["checks"],
                })
                continue

            result = materialize_memory_skill_as_skill_md(skill, skills_dir=skills_dir)
            record_bridge_event(name, result)

            if result.get("ok"):
                materialized += 1
                details.append({
                    "skill_name": name,
                    "action": "materialized",
                    "path": result.get("path"),
                    "skill_dir": result.get("skill_dir"),
                    "checks": validation["checks"],
                })
            else:
                failed += 1
                details.append({
                    "skill_name": name,
                    "action": "failed",
                    "reason": result.get("reason"),
                    "checks": validation["checks"],
                })

        reload_result: dict[str, Any] | None = None
        if not dry_run and materialized > 0:
            reload_result = reload_skill_loader()

        elapsed = _now() - started
        return {
            "ok": True,
            "dry_run": dry_run,
            "promoted_found": len(promoted),
            "eligible": (would_materialize if dry_run else materialized) + failed,
            "would_materialize": would_materialize,  # preview (dry_run)
            "materialized": materialized,             # real (não dry_run)
            "skipped": skipped,
            "failed": failed,
            "elapsed_sec": elapsed,
            "details": details,
            "reload": reload_result,
        }
    finally:
        try:
            if lock_file.exists():
                lock_file.unlink()
        except Exception:
            pass


# ── 7. Status ──────────────────────────────────────────────────────────────────

def status(*, db_path: str | Path | None = None) -> dict[str, Any]:
    """Retorna estado atual da bridge sem modificar nada."""
    promoted = list_promoted_memory_skills(db_path=db_path)
    eligible = [
        s for s in promoted
        if validate_memory_skill_for_materialization(s)["ok"]
    ]

    # Conta SKILL.md já materializados pela bridge
    root = MATERIALIZED_SKILLS_DIR
    mem_skills = [d.name for d in root.iterdir() if d.is_dir() and d.name.startswith("mem_")] if root.exists() else []

    # Tail do log
    log_tail: list[dict] = []
    if BRIDGE_LOG_PATH.exists():
        lines = BRIDGE_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        for ln in lines[-20:]:
            try:
                log_tail.append(json.loads(ln))
            except Exception:
                pass

    return {
        "ok": True,
        "promoted_in_memory": len(promoted),
        "eligible_for_bridge": len(eligible),
        "materialized_skills": mem_skills,
        "materialized_count": len(mem_skills),
        "min_success": _min_success(),
        "min_confidence": _min_confidence(),
        "log_path": str(BRIDGE_LOG_PATH),
        "recent_events": log_tail,
    }


# ── 8. Identificar skill mem_* ─────────────────────────────────────────────────

def is_memory_bridge_skill(skill_name: str) -> bool:
    """Retorna True se o nome da skill corresponde a uma skill materializada pela bridge."""
    return str(skill_name or "").startswith("mem_")


# ── 9. Executar skill mem_* por rota determinística ───────────────────────────

def execute_memory_bridge_skill(
    skill_name: str,
    task: str,
    *,
    production: bool = True,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Executa uma skill mem_* por rota determinística antes de acionar LLM.

    Estratégia de execução (em ordem de preferência):
      1. Busca a skill no skill_memory pelo nome exato → devolve instruções + exemplos.
      2. Busca semântica em skill_memory para a tarefa → resposta baseada em exemplos.
      3. Retorna metadados da skill para que o caller possa complementar via LLM.

    Retorna dict compatível com SkillExecutor._execute_builtin_skill():
      {
          "ok": bool,
          "output": str,          # resposta determinística (pode ser vazia)
          "source": str,          # "exact_match" | "semantic_match" | "metadata_only"
          "skill_name": str,
          "deterministic": bool,
          "success": bool,
      }
    """
    started = _now()
    slug = str(skill_name or "").removeprefix("mem_")  # ex: "chat_intent_greeting"

    # ── 0. Deterministic Resolver (Math, Logic, Safety, Env) ─────────────────
    # Executa primeiro, independentemente do status no banco.
    # Permite que dummy skills como "mem_resolver_deterministic" funcionem.
    det_output = _render_deterministic_resolver(task)
    if det_output:
        quality = _evaluate_response_quality(task, det_output, {
            "source": "resolver_deterministic", "match_score": 1.0,
            "matched_query": task, "matched_answer": det_output,
        }, {"name": skill_name, "category": "resolver"})
        try:
            from ultronpro import skill_memory as _sm_mod
            _sm_mod.record_skill_use(
                slug.replace("_", "-"),
                success=quality["success"],
                route="competence_ledger_resolver",
                task=task,
                expected=quality.get("expected"),
                output=det_output,
                db_path=db_path,
            )
        except Exception:
            pass
        record_bridge_event(skill_name, {"ok": True, "source": "resolver",
            "intent": "resolver", "quality": quality}, action="execute")
        return {
            "ok": True,
            "output": det_output,
            "source": "competence_ledger_resolver",
            "skill_name": skill_name,
            "deterministic": True,
            "success": quality["success"],
            "quality": quality,
            "elapsed_ms": int((_now() - started) * 1000),
        }

    # ── Competence Ledger gate ─────────────────────────────────────────────────
    # Classifica a intent da skill e aplica a política de execução antes de
    # tentar qualquer match determinístico.
    try:
        from ultronpro import skill_memory as _sm_mod
        _candidate = slug.replace("_", "-")
        _skill_meta = _sm_mod.get_skill(_candidate, db_path=db_path)
        if _skill_meta and str(_skill_meta.get("status") or "") == "promoted":
            _intent = _classify_mem_intent(_skill_meta)

            if _intent == "resolver":
                # Se o resolver determinístico (executado acima) não suportar (ex: frase complexa),
                # bloqueia mem_* e encaminha para o pipeline cognitivo normal
                record_bridge_event(skill_name, {"ok": False, "source": "competence_ledger",
                    "reason": "resolver_domain_fallback"}, action="gate")
                return {
                    "ok": False,
                    "output": None,
                    "source": "competence_ledger",
                    "skill_name": skill_name,
                    "deterministic": False,
                    "success": False,
                    "reason": "resolver_domain: encaminhado ao pipeline cognitivo",
                    "elapsed_ms": int((_now() - started) * 1000),
                }

            if _intent == "smalltalk":
                # Usa template adaptativo — sem copiar exemplos desatualizados
                output = _render_adaptive_smalltalk(task, _skill_meta)
                if output:
                    quality = _evaluate_response_quality(task, output, {
                        "source": "template", "match_score": 1.0,
                        "matched_query": task, "matched_answer": output,
                    }, _skill_meta)
                    _sm_mod.record_skill_use(
                        _candidate,
                        success=quality["success"],
                        route="competence_ledger_template",
                        task=task,
                        expected=quality.get("expected"),
                        output=output,
                        db_path=db_path,
                    )
                    record_bridge_event(skill_name, {"ok": True, "source": "template",
                        "intent": "smalltalk", "quality": quality}, action="execute")
                    return {
                        "ok": True,
                        "output": output,
                        "source": "competence_ledger_template",
                        "skill_name": skill_name,
                        "deterministic": True,
                        "success": quality["success"],
                        "quality": quality,
                        "elapsed_ms": int((_now() - started) * 1000),
                    }

            # intent == "open" → continua para o pipeline determinístico abaixo
    except Exception as _e:
        logger.debug(f"Competence Ledger gate error: {_e}")

    # ── tentativa 1: match exato pelo nome ─────────────────────────────────────
    try:
        from ultronpro import skill_memory

        # Converte slug mem_ de volta para o formato interno (underscores → hyphens)
        candidate_name = slug.replace("_", "-")
        skill = skill_memory.get_skill(candidate_name, db_path=db_path)

        if skill and str(skill.get("status") or "") == "promoted":
            output, match_meta = _build_deterministic_output(skill, task)
            quality = _evaluate_response_quality(task, output, match_meta, skill)
            record_bridge_event(
                skill_name,
                {"ok": True, "source": "exact_match", "task_len": len(task),
                 "quality": quality},
                action="execute",
            )
            skill_memory.record_skill_use(
                candidate_name,
                success=quality["success"],
                route="memory_bridge_exact",
                task=task,
                expected=quality.get("expected"),
                output=output,
                db_path=db_path,
            )
            return {
                "ok": True,
                "output": output,
                "source": "exact_match",
                "skill_name": skill_name,
                "deterministic": True,
                "success": quality["success"],
                "quality": quality,
                "elapsed_ms": int((_now() - started) * 1000),
            }
    except Exception as e:
        logger.debug(f"SkillMemoryBridge execute exact_match error: {e}")

    # ── tentativa 2: busca semântica pela tarefa ────────────────────────────────
    try:
        from ultronpro import skill_memory

        results = skill_memory.search(task, limit=1, include_candidates=False, min_score=0.35, db_path=db_path)
        if results:
            best = results[0]
            output, match_meta = _build_deterministic_output(best, task)
            quality = _evaluate_response_quality(task, output, match_meta, best)
            record_bridge_event(
                skill_name,
                {"ok": True, "source": "semantic_match", "score": best.get("score"),
                 "quality": quality},
                action="execute",
            )
            skill_memory.record_skill_use(
                str(best.get("name") or ""),
                success=quality["success"],
                route="memory_bridge_semantic",
                task=task,
                expected=quality.get("expected"),
                output=output,
                db_path=db_path,
            )
            return {
                "ok": True,
                "output": output,
                "source": "semantic_match",
                "skill_name": skill_name,
                "deterministic": True,
                "success": quality["success"],
                "quality": quality,
                "elapsed_ms": int((_now() - started) * 1000),
            }
    except Exception as e:
        logger.debug(f"SkillMemoryBridge execute semantic_match error: {e}")

    # ── fallback: retorna None para que skill_executor use LLM ─────────────────
    record_bridge_event(
        skill_name,
        {"ok": False, "source": "no_match"},
        action="execute",
    )
    return {
        "ok": False,
        "output": None,
        "source": "no_match",
        "skill_name": skill_name,
        "deterministic": False,
        "success": False,
        "elapsed_ms": int((_now() - started) * 1000),
    }


# ── Competence Ledger ──────────────────────────────────────────────────────────
#
# Define a política de execução para skills mem_*:
#
#   smalltalk  → responde via template adaptativo (hora do sistema, contexto)
#   resolver   → NUNCA responde via mem_*; encaminha ao pipeline cognitivo
#   open       → encaminha ao pipeline cognitivo (LLM + resolvers)
#
# Skills no domínio "resolver" têm competências determinísticas próprias
# (matemática, tradução, lógica, segurança, ambiente local) e mem_* não deve
# copiar respostas antigas nesses domínios.

import datetime as _datetime

_COMPETENCE_LEDGER: dict[str, dict[str, Any]] = {
    "smalltalk": {
        # Intents que usam template adaptativo (rápido, sem LLM)
        "patterns": {"greeting", "thanks", "farewell", "smalltalk", "saudacao",
                     "agradecimento", "despedida", "cumprimento"},
        "strategy": "template",
    },
    "resolver": {
        # Intents que têm resolver determinístico → bloqueia mem_*
        "patterns": {"math", "translation", "logic", "safety", "local_env",
                     "programming", "calcul", "traduz", "logica", "seguranca"},
        "strategy": "block",
    },
}


def _classify_mem_intent(skill: dict[str, Any]) -> str:
    """
    Classifica a estratégia de execução de uma skill mem_*.

    Retorna:
        "smalltalk"  → resposta via template adaptativo
        "resolver"   → bloqueia mem_*, envia ao pipeline
        "open"       → encaminha ao pipeline cognitivo
    """
    name = str(skill.get("name") or "").lower()
    tags = [str(t).lower() for t in (skill.get("tags") or [])]
    tokens = set((name + " " + " ".join(tags)).split())
    # Também verifica substrings do nome (ex: "chat-intent-greeting" → "greeting")
    name_parts = set(name.replace("-", " ").replace("_", " ").split())
    all_tokens = tokens | name_parts

    for strategy, cfg in _COMPETENCE_LEDGER.items():
        if any(p in all_tokens or any(p in tok for tok in all_tokens)
               for p in cfg["patterns"]):
            return strategy

    return "open"


# Templates adaptativos para smalltalk — sensíveis ao período do dia
_GREETING_MORNING = ["Bom dia!", "Bom dia! Como posso ajudar?", "Bom dia! Tudo pronto."]
_GREETING_AFTERNOON = ["Boa tarde!", "Boa tarde! Como posso ajudar?", "Boa tarde! Em que posso ajudar?"]
_GREETING_EVENING = ["Boa noite!", "Boa noite! Como posso ajudar?", "Boa noite! Em que posso ajudar?"]
_GREETING_GENERIC = ["Olá!", "Olá! Como posso ajudar?", "Oi! Em que posso ajudar?"]

_THANKS_TEMPLATES = [
    "Disponha!", "Por nada!", "Sempre à disposição!",
    "Foi um prazer!", "Fico feliz em ajudar!", "Conte comigo!",
]


def _current_period() -> str:
    """Retorna o período do dia: morning, afternoon ou evening."""
    hour = _datetime.datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    return "evening"


def _render_adaptive_smalltalk(task: str, skill: dict[str, Any]) -> str | None:
    """
    Gera resposta de smalltalk adaptada ao contexto (período do dia, tipo de intent).

    Retorna None se não consegue classificar — executor usa LLM normalmente.
    """
    import hashlib
    t = task.lower().strip()
    name = str(skill.get("name") or "").lower()
    period = _current_period()

    # Detecta tipo de smalltalk
    is_greeting = any(k in name or k in t for k in
                      ("greeting", "saudacao", "cumprimento", "bom dia", "boa tarde",
                       "boa noite", "ola", "oi", "hello", "hi ", "hey"))
    is_thanks = any(k in name or k in t for k in
                    ("thanks", "agradecimento", "obrigado", "obrigada",
                     "valeu", "grato", "thank"))
    is_farewell = any(k in name or k in t for k in
                      ("farewell", "despedida", "tchau", "bye", "até logo", "até mais"))

    # Seed determinístico por sessão (evita resposta idêntica a cada chamada)
    seed = int(hashlib.md5(f"{task[:20]}{_datetime.date.today()}".encode()).hexdigest(), 16)

    if is_thanks:
        return _THANKS_TEMPLATES[seed % len(_THANKS_TEMPLATES)]

    if is_farewell:
        farewell_templates = ["Até logo!", "Até mais!", "Boa continuação!", "Cuide-se!"]
        return farewell_templates[seed % len(farewell_templates)]

    if is_greeting:
        # Detecta período explícito na tarefa
        task_period = None
        if any(k in t for k in ("bom dia", "good morning", "buenos dias")):
            task_period = "morning"
        elif any(k in t for k in ("boa tarde", "good afternoon", "buenas tardes")):
            task_period = "afternoon"
        elif any(k in t for k in ("boa noite", "good evening", "good night", "buenas noches")):
            task_period = "evening"

        # Usa período da tarefa se explícito; caso contrário, usa período atual
        active_period = task_period or period

        if active_period == "morning":
            return _GREETING_MORNING[seed % len(_GREETING_MORNING)]
        if active_period == "afternoon":
            return _GREETING_AFTERNOON[seed % len(_GREETING_AFTERNOON)]
        return _GREETING_EVENING[seed % len(_GREETING_EVENING)]

    # Genérico
    return _GREETING_GENERIC[seed % len(_GREETING_GENERIC)]


def _render_deterministic_resolver(task: str) -> str | None:
    """
    Tenta resolver a tarefa determinísticamente (math, lógica, segurança).
    Retorna a string da resposta, ou None se não conseguir resolver.
    """
    import re as _re
    t = task.lower()

    # 1. Safety (bloqueio de tópicos sensíveis)
    safety_patterns = [
        r"\b(bomb[a]?|explosiv[oa]|arma|weapon|poison|veneno)\b",
        r"\b(suicid[oi]|automutilar|self.harm|overdose)\b",
        r"\b(hack\w*|invad\w*|exploit\w*|crack\w*|vuln\w*|malware|rootkit)\b",
        r"\b(droga|drug|cocaine|heroin|methamphetamine)\b",
        r"\b(matar|assassin[a]?|murder|kill someone)\b",
    ]
    if any(_re.search(pat, t, _re.IGNORECASE) for pat in safety_patterns):
        return "Não posso ajudar com isso por motivos de segurança e política de uso."

    # 2. Local Env (bloqueio de comandos perigosos)
    env_patterns = [
        r"\b(rm\s+-rf|del\s+/[sfq]|format\s+[a-z]:)\b",
        r"\b(drop\s+table|truncate\s+table|delete\s+from)\b",
        r"\b(shutdown|reboot|halt|kill\s+-9)\b",
        r"\b(chmod\s+777|chown\s+root|sudo\s+rm)\b",
        r"\b(mkfs|fdisk|dd\s+if=)\b",
    ]
    if any(_re.search(pat, t, _re.IGNORECASE) for pat in env_patterns):
        if not any(g in t for g in ["dry_run", "dry-run", "confirmar", "--force", "cuidado"]):
            return "Ação bloqueada: comando destrutivo requer confirmação explícita (dry-run)."

    # 3. Math
    t_math = task.lower().replace("dividido por", "/").replace("vezes", "*").replace("mais", "+").replace("menos", "-")
    quadrado_match = _re.search(r"(\d+(?:\.\d+)?)\s*ao\s*quadrado", t_math)
    if quadrado_match:
        val = float(quadrado_match.group(1))
        expected = val * val
        expected_str = str(int(expected)) if expected == int(expected) else f"{expected:.4g}"
        return f"O resultado é {expected_str}."

    expr_match = _re.search(r"(\d+(?:\.\d+)?)\s*([\+\-\*\/])\s*(\d+(?:\.\d+)?)", t_math)
    if expr_match:
        a_str, op, b_str = expr_match.group(1), expr_match.group(2), expr_match.group(3)
        try:
            a, b = float(a_str), float(b_str)
            expected = 0.0
            if op == "+": expected = a + b
            elif op == "-": expected = a - b
            elif op == "*": expected = a * b
            elif op == "/": 
                if b != 0: expected = a / b
                else: return "Divisão por zero não é permitida."
            expected_str = str(int(expected)) if expected == int(expected) else f"{expected:.4g}"
            return f"O resultado é {expected_str}."
        except Exception:
            pass

    # 4. Logic
    cmp_match = _re.search(
        r"(\d+(?:\.\d+)?)\s*(?:é\s+)?(maior que|menor que|igual a|>|<|==)\s*(\d+(?:\.\d+)?)",
        t
    )
    if cmp_match:
        a = float(cmp_match.group(1))
        op = cmp_match.group(2).strip()
        b = float(cmp_match.group(3))
        expected_bool = False
        if op in (">", "maior que"): expected_bool = a > b
        elif op in ("<", "menor que"): expected_bool = a < b
        elif op in ("==", "igual a"): expected_bool = a == b
        return "Sim, isso é verdadeiro." if expected_bool else "Não, isso é falso."

    return None

# ── Avaliação de qualidade semântica ───────────────────────────────────────────

# Mapeamento de domínios com regras heurísticas de validação.
# Cada regra recebe (task, output) e retorna (success: bool, reason: str).
_DOMAIN_RULES: dict[str, Any] = {}


def _register_domain_rule(pattern: str):
    """Decorator para registrar regras de domínio."""
    def wrapper(fn):
        _DOMAIN_RULES[pattern] = fn
        return fn
    return wrapper


@_register_domain_rule("greeting")
def _rule_greeting(task: str, output: str) -> tuple[bool, str]:
    """Valida saudações: período do dia deve ser coerente."""
    t = task.lower().strip()
    o = output.lower().strip()

    morning_tokens = {"bom dia", "good morning", "buenos dias"}
    evening_tokens = {"boa noite", "good evening", "buenas noches", "good night"}
    afternoon_tokens = {"boa tarde", "good afternoon", "buenas tardes"}

    task_period = None
    for tok in morning_tokens:
        if tok in t:
            task_period = "morning"
            break
    if not task_period:
        for tok in afternoon_tokens:
            if tok in t:
                task_period = "afternoon"
                break
    if not task_period:
        for tok in evening_tokens:
            if tok in t:
                task_period = "evening"
                break

    if not task_period:
        return True, "no_period_detected"

    # Detecta conflito de período na resposta
    output_has_morning = any(tok in o for tok in morning_tokens)
    output_has_afternoon = any(tok in o for tok in afternoon_tokens)
    output_has_evening = any(tok in o for tok in evening_tokens)

    if task_period == "morning" and output_has_evening:
        return False, "period_mismatch: task=morning, output=evening"
    if task_period == "morning" and output_has_afternoon:
        return False, "period_mismatch: task=morning, output=afternoon"
    if task_period == "evening" and output_has_morning:
        return False, "period_mismatch: task=evening, output=morning"
    if task_period == "evening" and output_has_afternoon:
        return False, "period_mismatch: task=evening, output=afternoon"
    if task_period == "afternoon" and output_has_morning:
        return False, "period_mismatch: task=afternoon, output=morning"
    if task_period == "afternoon" and output_has_evening:
        return False, "period_mismatch: task=afternoon, output=evening"

    return True, "period_ok"


@_register_domain_rule("thanks")
def _rule_thanks(task: str, output: str) -> tuple[bool, str]:
    """Valida agradecimentos: resposta deve conter reconhecimento."""
    o = output.lower().strip()
    ack_tokens = ["disponha", "nada", "prazer", "welcome", "obrigado",
                  "agradec", "sempre", "conte comigo", "por nada"]
    if any(tok in o for tok in ack_tokens):
        return True, "ack_found"
    if len(o) < 3:
        return False, "empty_response_to_thanks"
    return True, "ack_assumed"


# ── Regras de domínio estendidas ────────────────────────────────────────────────

import ast as _ast
import re as _re

# Tokens indicativos de recusa/segurança
_SAFETY_REFUSE_TOKENS = [
    "não posso", "nao posso", "cannot", "can't", "i can't", "i cannot",
    "me recuso", "recuso", "unable", "inappropriate", "harmful", "ilegal",
    "perigoso", "proibido", "not allowed", "won't", "will not",
]

# Tópicos sensíveis que não devem ser respondidos por mem_*
_SAFETY_SENSITIVE_PATTERNS = [
    r"\b(bomb[a]?|explosiv[oa]|arma|weapon|poison|veneno)\b",
    r"\b(suicid[oi]|automutilar|self.harm|overdose)\b",
    r"\b(hack\w*|invad\w*|exploit\w*|crack\w*|vuln\w*|malware|rootkit)\b",
    r"\b(droga|drug|cocaine|heroin|methamphetamine)\b",
    r"\b(matar|assassin[a]?|murder|kill someone)\b",
]


@_register_domain_rule("safety")
def _rule_safety(task: str, output: str) -> tuple[bool, str]:
    """
    Safety gate: uma skill mem_* jamais deve responder a tópicos sensíveis
    sem incluir uma recusa ou encaminhamento.
    Se o tópico for sensível e a resposta não recusar, marca como FAIL.
    """
    t = task.lower()
    o = output.lower()

    is_sensitive = any(
        _re.search(pat, t, _re.IGNORECASE)
        for pat in _SAFETY_SENSITIVE_PATTERNS
    )
    if not is_sensitive:
        return True, "topic_not_sensitive"

    has_refusal = any(tok in o for tok in _SAFETY_REFUSE_TOKENS)
    if has_refusal:
        return True, "sensitive_topic_with_refusal"

    # Tópico sensível sem recusa → mem_* não deveria responder isso
    return False, "safety_gate_violation: sensitive_topic_without_refusal"


@_register_domain_rule("math")
def _rule_math(task: str, output: str) -> tuple[bool, str]:
    """
    Valida resultado numérico: se a tarefa contém expressão aritmética simples,
    verifica se o output contém o resultado correto.
    """
    # Extrai a expressão: aceita apenas +, -, *, / e números
    expr_match = _re.search(r"(\d+(?:\.\d+)?)\s*([\+\-\*\/])\s*(\d+(?:\.\d+)?)", task)
    if not expr_match:
        return True, "no_simple_expr_found"

    a_str, op, b_str = expr_match.group(1), expr_match.group(2), expr_match.group(3)
    try:
        a, b = float(a_str), float(b_str)
        expected: float
        if op == "+":
            expected = a + b
        elif op == "-":
            expected = a - b
        elif op == "*":
            expected = a * b
        elif op == "/":
            if b == 0:
                return True, "division_by_zero_skipped"
            expected = a / b
        else:
            return True, "unknown_op"

        # Formata resultado esperado (int se sem decimais)
        expected_str = str(int(expected)) if expected == int(expected) else f"{expected:.4g}"

        if expected_str in output.replace(" ", ""):
            return True, f"math_correct: {a_str}{op}{b_str}={expected_str}"
        # Também aceita resultado em float próximo
        nums_in_output = _re.findall(r"\d+(?:\.\d+)?", output)
        for n in nums_in_output:
            try:
                if abs(float(n) - expected) < 1e-6:
                    return True, f"math_correct_float: {expected:.6g}"
            except ValueError:
                pass

        return False, f"math_wrong: expected={expected_str}, output={output[:60]}"
    except Exception as exc:
        return True, f"math_eval_error_skipped: {exc}"


# Mapeamento de idioma alvo → marcadores léxicos mínimos
_LANG_MARKERS: dict[str, list[str]] = {
    "francês":    ["le ", "la ", "les ", "de ", "du ", "je ", "il ", "une ", "est ", "et "],
    "french":     ["le ", "la ", "les ", "de ", "du ", "je ", "il ", "une ", "est ", "et "],
    "inglês":     ["the ", "is ", "are ", "was ", "were ", "this ", "that ", "and ", "of ", "in "],
    "english":    ["the ", "is ", "are ", "was ", "were ", "this ", "that ", "and ", "of ", "in "],
    "espanhol":   ["el ", "la ", "los ", "de ", "que ", "en ", "es ", "un ", "una ", "con "],
    "spanish":    ["el ", "la ", "los ", "de ", "que ", "en ", "es ", "un ", "una ", "con "],
    "alemão":     ["der ", "die ", "das ", "ist ", "ich ", "und ", "ein ", "eine ", "nicht ", "sie "],
    "german":     ["der ", "die ", "das ", "ist ", "ich ", "und ", "ein ", "eine ", "nicht ", "sie "],
    "português":  ["que ", "com ", "para ", "não ", "uma ", "em ", "um ", "por ", "mais ", "mas "],
    "portuguese": ["que ", "com ", "para ", "não ", "uma ", "em ", "um ", "por ", "mais ", "mas "],
    "italiano":   ["il ", "la ", "che ", "di ", "non ", "è ", "per ", "una ", "con ", "sono "],
    "italian":    ["il ", "la ", "che ", "di ", "non ", "è ", "per ", "una ", "con ", "sono "],
}

_TRANSLATE_TRIGGERS = [
    "traduz", "translate", "como se diz", "how do you say",
    "em francês", "em inglês", "em espanhol", "em alemão",
    "in french", "in english", "in spanish", "in german",
    "em português", "in portuguese", "em italiano", "in italian",
]


@_register_domain_rule("translation")
def _rule_translation(task: str, output: str) -> tuple[bool, str]:
    """
    Valida tradução: se a tarefa pede tradução para idioma X,
    a resposta deve conter marcadores léxicos daquele idioma.
    """
    t = task.lower()
    o = output.lower() + " "  # espaço final para match de tokens

    is_translation_task = any(trigger in t for trigger in _TRANSLATE_TRIGGERS)
    if not is_translation_task:
        return True, "not_a_translation_task"

    # Detecta idioma alvo
    target_lang = None
    for lang in _LANG_MARKERS:
        if lang in t:
            target_lang = lang
            break

    if not target_lang:
        return True, "target_lang_not_detected"

    # Verifica marcadores léxicos
    markers = _LANG_MARKERS[target_lang]
    hits = sum(1 for m in markers if m in o)
    if hits >= 2:
        return True, f"translation_lang_ok: {target_lang} ({hits} markers)"

    # Verifica se o output é muito curto (palavra isolada pode ser válida)
    if len(output.strip().split()) <= 3:
        return True, "translation_short_output_accepted"

    return False, f"translation_lang_mismatch: target={target_lang}, markers_found={hits}"


@_register_domain_rule("basic_logic")
def _rule_basic_logic(task: str, output: str) -> tuple[bool, str]:
    """
    Valida conclusões lógicas simples: maior, menor, igual, verdadeiro/falso.
    Detecta padrões como '5 > 3?' e valida se a resposta está correta.
    """
    t = task.lower()
    o = output.lower()

    # Padrão: "X é maior que Y?" ou "X > Y?"
    cmp_match = _re.search(
        r"(\d+(?:\.\d+)?)\s*(?:é\s+)?(maior que|menor que|igual a|>|<|==)\s*(\d+(?:\.\d+)?)",
        t
    )
    if not cmp_match:
        return True, "no_comparison_detected"

    a = float(cmp_match.group(1))
    op = cmp_match.group(2).strip()
    b = float(cmp_match.group(3))

    expected: bool
    if op in (">", "maior que"):
        expected = a > b
    elif op in ("<", "menor que"):
        expected = a < b
    elif op in ("==", "igual a"):
        expected = a == b
    else:
        return True, "unknown_comparison"

    positive_tokens = ["sim", "yes", "verdadeiro", "true", "correto", "certo"]
    negative_tokens = ["não", "nao", "no", "falso", "false", "errado", "incorreto"]

    output_positive = any(tok in o for tok in positive_tokens)
    output_negative = any(tok in o for tok in negative_tokens)

    if expected and output_negative and not output_positive:
        return False, f"logic_wrong: {a}{op}{b} is True but output suggests False"
    if not expected and output_positive and not output_negative:
        return False, f"logic_wrong: {a}{op}{b} is False but output suggests True"

    return True, f"logic_ok: {a}{op}{b}={expected}"


# Padrões destrutivos que local_env não deve executar via mem_*
_LOCAL_ENV_DANGEROUS = [
    r"\b(rm\s+-rf|del\s+/[sfq]|format\s+[a-z]:)\b",
    r"\b(drop\s+table|truncate\s+table|delete\s+from)\b",
    r"\b(shutdown|reboot|halt|kill\s+-9)\b",
    r"\b(chmod\s+777|chown\s+root|sudo\s+rm)\b",
    r"\b(mkfs|fdisk|dd\s+if=)\b",
]


@_register_domain_rule("local_env")
def _rule_local_env(task: str, output: str) -> tuple[bool, str]:
    """
    Garante que skills de ambiente local não executem ações destrutivas
    sem gate de segurança (dry_run, confirmação explícita, etc.).
    """
    o = output.lower()

    for pat in _LOCAL_ENV_DANGEROUS:
        if _re.search(pat, o, _re.IGNORECASE):
            # Verifica se há gate de segurança na resposta
            has_gate = any(g in o for g in [
                "dry_run", "dry-run", "confirmar", "confirm", "--force",
                "aviso", "warning", "cuidado", "caution", "irreversível"
            ])
            if not has_gate:
                return False, f"local_env_dangerous_without_gate: pattern={pat}"

    return True, "local_env_safe"


# Fatos básicos de linguagens de programação (versão atual → tokens mínimos)
_PROG_LANG_FACTS: list[tuple[str, str, list[str]]] = [
    # (trigger_pattern, expected_indicator, wrong_indicators)
    (r"python\s*3", "python 3", ["python 2", "python2"]),
    (r"node\.?js\s+lts", "lts", ["eol", "end of life"]),
    (r"git\s+init", "git init", ["svn init", "hg init"]),
]


@_register_domain_rule("programming_fact")
def _rule_programming_fact(task: str, output: str) -> tuple[bool, str]:
    """
    Valida fatos básicos de programação: versão, comandos canônicos, etc.
    """
    t = task.lower()
    o = output.lower()

    for trigger, expected, wrong_list in _PROG_LANG_FACTS:
        if _re.search(trigger, t):
            if any(w in o for w in wrong_list):
                return False, f"programming_fact_wrong: found wrong indicator for trigger={trigger}"
            if expected in o:
                return True, f"programming_fact_ok: trigger={trigger}"

    return True, "programming_fact_no_match"


def _match_domain_rules(task: str, output: str, skill: dict[str, Any]) -> tuple[bool | None, str]:
    """
    Aplica regras de domínio ao par (task, output).
    Safety é avaliada primeiro (prioridade máxima).
    Retorna (success, reason). success=None se nenhuma regra se aplica.
    """
    skill_name = str(skill.get("name") or "").lower()
    tags = [str(t).lower() for t in (skill.get("tags") or [])]
    all_tokens = skill_name + " " + " ".join(tags)

    # Safety tem prioridade absoluta — avalia independentemente do nome/tag
    safety_fn = _DOMAIN_RULES.get("safety")
    if safety_fn:
        success, reason = safety_fn(task, output)
        if not success:
            return False, f"domain_rule:safety:{reason}"

    # Demais regras por correspondência de nome/tag
    for pattern, rule_fn in _DOMAIN_RULES.items():
        if pattern == "safety":
            continue  # já avaliado acima
        if pattern in all_tokens:
            success, reason = rule_fn(task, output)
            return success, f"domain_rule:{pattern}:{reason}"

    return None, "no_domain_rule"


def _evaluate_response_quality(
    task: str,
    output: str,
    match_meta: dict[str, Any],
    skill: dict[str, Any],
) -> dict[str, Any]:
    """
    Avalia a qualidade semântica da resposta de uma skill mem_*.

    Critérios (em ordem de prioridade):
      1. Regras de domínio (greeting, thanks, etc.)
      2. Confiança do match de exemplo (token overlap)
      3. Output não-vazio

    Retorna:
      {
          "success": bool,
          "confidence": float (0-1),
          "expected": str | None,
          "reason": str,
      }
    """
    if not output or not output.strip():
        return {
            "success": False,
            "confidence": 0.0,
            "expected": None,
            "reason": "empty_output",
        }

    # 1. Regras de domínio
    domain_success, domain_reason = _match_domain_rules(task, output, skill)
    if domain_success is not None:
        return {
            "success": domain_success,
            "confidence": 0.95 if domain_success else 0.85,
            "expected": match_meta.get("matched_answer"),
            "reason": domain_reason,
        }

    # 2. Confiança do match de exemplo
    match_score = float(match_meta.get("match_score", 0))
    matched_query = match_meta.get("matched_query", "")
    source = match_meta.get("source", "")

    if source == "example" and match_score > 0:
        # Score alto de overlap = alta confiança de que o exemplo é adequado
        task_tokens = set(task.lower().split())
        query_tokens = set(matched_query.lower().split())
        # Jaccard-like para medir adequação
        union = task_tokens | query_tokens
        intersection = task_tokens & query_tokens
        jaccard = len(intersection) / max(len(union), 1)

        if jaccard < 0.20 and match_score <= 1:
            # Exemplo muito diferente da tarefa — provavelmente irrelevante
            return {
                "success": False,
                "confidence": 0.6,
                "expected": match_meta.get("matched_answer"),
                "reason": f"low_example_relevance: jaccard={jaccard:.2f}",
            }

        return {
            "success": True,
            "confidence": min(0.5 + jaccard, 1.0),
            "expected": match_meta.get("matched_answer"),
            "reason": f"example_match: jaccard={jaccard:.2f}, score={match_score}",
        }

    # 3. Fallback: instruções/summary — assume sucesso com confiança moderada
    return {
        "success": True,
        "confidence": 0.5,
        "expected": None,
        "reason": f"fallback_output: source={source}",
    }


# ── Construção de resposta determinística ──────────────────────────────────────

def _build_deterministic_output(
    skill: dict[str, Any], task: str
) -> tuple[str, dict[str, Any]]:
    """
    Constrói uma resposta determinística a partir dos metadados da skill.
    Prioriza: instruções → exemplos similares → summary.

    Retorna:
        (output_text, match_meta)

    match_meta contém:
        source: 'instruction' | 'example' | 'summary'
        match_score: float (overlap de tokens com exemplo)
        matched_query: str (query do exemplo que casou)
        matched_answer: str (resposta do exemplo que casou)
    """
    instructions = str(skill.get("instructions") or "").strip()
    summary = str(skill.get("summary") or "").strip()
    examples: list[dict] = list(skill.get("examples") or [])

    parts: list[str] = []
    match_meta: dict[str, Any] = {
        "source": "none",
        "match_score": 0.0,
        "matched_query": "",
        "matched_answer": "",
    }

    # Instrução direta
    if instructions:
        parts.append(instructions)
        match_meta["source"] = "instruction"

    # Exemplo mais similar (busca simples por tokens compartilhados)
    if examples:
        task_lower = task.lower()
        best_ex: dict[str, Any] | None = None
        best_score = 0.0
        for ex in examples[-10:]:
            q = str(ex.get("query") or "").lower()
            if not q:
                continue
            common = sum(1 for token in task_lower.split() if len(token) > 2 and token in q)
            if common > best_score:
                best_score = common
                best_ex = ex
        if best_ex and best_score > 0:
            ans = str(best_ex.get("answer_summary") or "").strip()
            if ans:
                parts.append(f"\n*Baseado em interação anterior similar:* {ans}")
                match_meta.update({
                    "source": "example",
                    "match_score": best_score,
                    "matched_query": str(best_ex.get("query") or ""),
                    "matched_answer": ans,
                })

    # Summary como fallback
    if not parts and summary:
        parts.append(summary)
        match_meta["source"] = "summary"

    return "\n".join(parts).strip(), match_meta

