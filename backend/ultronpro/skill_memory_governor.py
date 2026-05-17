"""
skill_memory_governor.py
========================
Governança de qualidade das skills aprendidas (mem_*).

Responsabilidades:
  - Calcular health score de cada skill promovida
  - Rebaixar (demote) skills com degradação de qualidade
  - Remover SKILL.md correspondente e recarregar skill_loader
  - Registrar decisões em JSONL para auditoria

Critérios de demoção (configuráveis via env):
  ULTRON_GOV_MAX_FAILURE_RATE   (padrão: 0.25) → taxa de falha recente
  ULTRON_GOV_MIN_RECENT_USES    (padrão: 5)    → mínimo de usos para avaliar
  ULTRON_GOV_MAX_IDLE_DAYS      (padrão: 30)   → dias sem uso → idle demotion
  ULTRON_GOV_WINDOW             (padrão: 50)   → N últimas interações para rate recente
  ULTRON_GOV_ENABLED            (padrão: 1)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("uvicorn")

# ── Configuração ───────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GOV_LOG_PATH = DATA_DIR / "skill_memory_governor_log.jsonl"
SKILLS_ROOT = Path(__file__).resolve().parent.parent / "ultron_skills"


def _enabled() -> bool:
    return str(os.getenv("ULTRON_GOV_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}


def _max_failure_rate() -> float:
    return float(os.getenv("ULTRON_GOV_MAX_FAILURE_RATE", "0.25"))


def _min_recent_uses() -> int:
    return int(os.getenv("ULTRON_GOV_MIN_RECENT_USES", "5"))


def _max_idle_days() -> float:
    return float(os.getenv("ULTRON_GOV_MAX_IDLE_DAYS", "30"))


def _window_size() -> int:
    return int(os.getenv("ULTRON_GOV_WINDOW", "50"))


def _now() -> float:
    return time.time()


# ── Registro de eventos ────────────────────────────────────────────────────────

def _record_gov_event(skill_name: str, action: str, reason: str, detail: dict[str, Any]) -> None:
    GOV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _now(),
        "skill": skill_name,
        "action": action,
        "reason": reason,
        **detail,
    }
    try:
        with GOV_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── Health score ───────────────────────────────────────────────────────────────

def compute_health(skill: dict[str, Any], *, db_path: str | Path | None = None) -> dict[str, Any]:
    """
    Calcula o health score de uma skill promovida.

    Retorna:
        {
            "healthy": bool,
            "score": float (0-1),
            "failure_rate": float,
            "idle_days": float | None,
            "issues": list[str],
        }
    """
    skill_name = skill.get("name")
    
    # Tenta pegar histórico recente
    recent_total = 0
    recent_failure = 0
    try:
        from ultronpro import skill_memory
        with skill_memory._LOCK, skill_memory._connect(db_path) as conn:
            rows = conn.execute(
                "SELECT success FROM skill_execution_log WHERE skill_name=? ORDER BY ts DESC LIMIT ?",
                (skill_name, _window_size())
            ).fetchall()
            recent_total = len(rows)
            recent_success = sum(1 for r in rows if r["success"])
            recent_failure = recent_total - recent_success
    except Exception:
        pass

    if recent_total > 0:
        total = recent_total
        failure = recent_failure
    else:
        # Fallback para o acumulado
        success = int(skill.get("success_count") or 0)
        failure = int(skill.get("failure_count") or 0)
        total = success + failure
        
    last_used = skill.get("last_used_at")

    issues: list[str] = []

    # Taxa de falha
    failure_rate = failure / total if total > 0 else 0.0
    if total >= _min_recent_uses() and failure_rate > _max_failure_rate():
        issues.append(
            f"failure_rate={failure_rate:.2%} > threshold={_max_failure_rate():.2%}"
        )

    # Idle (sem uso recente)
    idle_days: float | None = None
    if last_used:
        idle_days = (_now() - float(last_used)) / 86400
        if idle_days > _max_idle_days():
            issues.append(f"idle={idle_days:.1f}d > max={_max_idle_days():.0f}d")

    # Score composto (simples)
    success_rate = 1.0 - failure_rate
    recency_factor = 1.0
    if idle_days is not None:
        recency_factor = max(0.0, 1.0 - idle_days / (_max_idle_days() * 2))

    score = round(success_rate * recency_factor * float(skill.get("confidence") or 0.5), 3)

    return {
        "healthy": len(issues) == 0,
        "score": score,
        "failure_rate": round(failure_rate, 4),
        "idle_days": round(idle_days, 1) if idle_days is not None else None,
        "total_interactions": total,
        "issues": issues,
    }


# ── Remoção de SKILL.md ────────────────────────────────────────────────────────

def _remove_skill_md(skill_name: str) -> dict[str, Any]:
    """Remove o diretório mem_* correspondente do ultron_skills/."""
    slug = "mem_" + skill_name.replace("-", "_")
    skill_dir = SKILLS_ROOT / slug
    if skill_dir.exists():
        try:
            shutil.rmtree(str(skill_dir))
            return {"ok": True, "removed": str(skill_dir)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "removed": None, "note": "dir_not_found"}


# ── Demoção ────────────────────────────────────────────────────────────────────

def demote_skill(
    skill_name: str,
    reason: str,
    *,
    db_path: str | Path | None = None,
    remove_skill_md: bool = True,
) -> dict[str, Any]:
    """
    Rebaixa uma skill de 'promoted' → 'candidate'.
    Remove o SKILL.md e recarrega o skill_loader.
    """
    try:
        from ultronpro import skill_memory

        with skill_memory._LOCK, skill_memory._connect(db_path) as conn:
            conn.execute(
                "UPDATE learned_skills SET status='candidate', updated_at=? WHERE name=?",
                (_now(), skill_name),
            )
        logger.warning(f"[GOV] Skill demovida: {skill_name} — {reason}")
    except Exception as e:
        return {"ok": False, "error": str(e)}

    removal = {"ok": True, "removed": None}
    if remove_skill_md:
        removal = _remove_skill_md(skill_name)

    # Recarrega skill_loader para remover da memória ativa
    reload_result: dict[str, Any] = {}
    try:
        from ultronpro import skill_loader
        loader = skill_loader.get_skill_loader()
        reload_result = loader.load_skills(force=True)
    except Exception:
        pass

    _record_gov_event(skill_name, "demoted", reason, {
        "skill_md_removal": removal,
        "reload": reload_result,
    })

    return {
        "ok": True,
        "skill": skill_name,
        "action": "demoted",
        "reason": reason,
        "skill_md_removal": removal,
        "reload": reload_result,
    }


# ── Pipeline principal ─────────────────────────────────────────────────────────

def run_governor(
    *,
    db_path: str | Path | None = None,
    dry_run: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """
    Avalia todas as skills promovidas e demove as que estão degradadas.

    Args:
        dry_run: Se True, apenas reporta sem modificar nada.
        limit: Máximo de skills a avaliar.

    Returns:
        {
            "ok": bool,
            "dry_run": bool,
            "evaluated": int,
            "healthy": int,
            "demoted": int,
            "would_demote": int,
            "details": list[dict],
        }
    """
    if not _enabled():
        return {"ok": True, "skipped": True, "reason": "governor_disabled"}

    lock_file = GOV_LOG_PATH.with_suffix(".lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    def _try_acquire_lock() -> bool:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            return False

    if not _try_acquire_lock():
        if lock_file.exists() and time.time() - lock_file.stat().st_mtime > 300:
            logger.warning("skill_memory_governor: removendo lock orfao antigo")
            try:
                lock_file.unlink()
            except Exception:
                pass
            if not _try_acquire_lock():
                return {"ok": True, "skipped": True, "reason": "governor_already_running"}
        else:
            return {"ok": True, "skipped": True, "reason": "governor_already_running"}

    try:
        started = _now()
    
        try:
            from ultronpro import skill_memory
            with skill_memory._LOCK, skill_memory._connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM learned_skills WHERE status='promoted' ORDER BY confidence DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            promoted = [skill_memory._row_to_dict(r) for r in rows]
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
        details: list[dict[str, Any]] = []
        healthy_count = 0
        demoted_count = 0
        would_demote_count = 0
    
        for skill in promoted:
            name = str(skill.get("name") or "")
            health = compute_health(skill, db_path=db_path)

            if health["healthy"]:
                healthy_count += 1
                details.append({
                    "skill": name,
                    "action": "kept",
                    "health": health,
                })
                continue
    
            # Skill com problema detectado
            reason = "; ".join(health["issues"])
    
            if dry_run:
                would_demote_count += 1
                details.append({
                    "skill": name,
                    "action": "would_demote",
                    "reason": reason,
                    "health": health,
                })
            else:
                result = demote_skill(name, reason, db_path=db_path, remove_skill_md=True)
                demoted_count += 1
                details.append({
                    "skill": name,
                    "action": "demoted",
                    "reason": reason,
                    "health": health,
                    "result": result,
                })

        elapsed = _now() - started
        return {
            "ok": True,
            "dry_run": dry_run,
            "evaluated": len(promoted),
            "healthy": healthy_count,
            "demoted": demoted_count,
            "would_demote": would_demote_count,
            "elapsed_sec": round(elapsed, 3),
            "details": details,
        }
    finally:
        try:
            if lock_file.exists():
                lock_file.unlink()
        except Exception:
            pass


# ── Status ─────────────────────────────────────────────────────────────────────

def status(*, db_path: str | Path | None = None) -> dict[str, Any]:
    """Retorna resumo de saúde de todas as skills promovidas."""
    try:
        from ultronpro import skill_memory
        with skill_memory._LOCK, skill_memory._connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM learned_skills WHERE status='promoted' ORDER BY confidence DESC"
            ).fetchall()
        promoted = [skill_memory._row_to_dict(r) for r in rows]
    except Exception as e:
        return {"ok": False, "error": str(e)}

    healths = [
        {"skill": s.get("name"), **compute_health(s, db_path=db_path)}
        for s in promoted
    ]
    unhealthy = [h for h in healths if not h["healthy"]]

    # Tail do log de governança
    log_tail: list[dict] = []
    if GOV_LOG_PATH.exists():
        lines = GOV_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        for ln in lines[-20:]:
            try:
                log_tail.append(json.loads(ln))
            except Exception:
                pass

    return {
        "ok": True,
        "promoted_count": len(promoted),
        "healthy_count": len(promoted) - len(unhealthy),
        "unhealthy_count": len(unhealthy),
        "unhealthy_skills": [h["skill"] for h in unhealthy],
        "max_failure_rate": _max_failure_rate(),
        "min_recent_uses": _min_recent_uses(),
        "max_idle_days": _max_idle_days(),
        "skills": healths,
        "recent_events": log_tail,
    }
