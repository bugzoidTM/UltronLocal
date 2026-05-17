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


def _match_domain_rules(task: str, output: str, skill: dict[str, Any]) -> tuple[bool | None, str]:
    """
    Aplica regras de domínio ao par (task, output).
    Retorna (success, reason). success=None se nenhuma regra se aplica.
    """
    skill_name = str(skill.get("name") or "").lower()
    tags = [str(t).lower() for t in (skill.get("tags") or [])]
    all_tokens = skill_name + " " + " ".join(tags)

    for pattern, rule_fn in _DOMAIN_RULES.items():
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

