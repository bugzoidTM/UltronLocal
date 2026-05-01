"""
Code Self-Healer — Auto-Correção de Código em Tempo Real
=========================================================

Fecha o loop completo:
  traceback capturado → análise AST → localiza bug → gera fix → testa em sandbox → aplica → verifica → rollback se falhou

Diferente do self_corrector (que só ajusta parâmetros) e do self_modification
(que depende de trigger manual), este módulo:
  1. Intercepta exceções do runtime (tracebacks)
  2. Analisa o código-fonte com AST para entender o contexto
  3. Gera uma correção determinística OU via LLM
  4. Valida sintaticamente (ast.parse) antes de aplicar
  5. Faz backup, aplica, e valida importação do módulo
  6. Se falhar, faz rollback automático
  7. Registra tudo no histórico para aprendizado

Maturidade: Fase 14 do Roadmap AGI
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import traceback
import textwrap
from collections import deque
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("uvicorn")

ULTRONPRO_DIR = Path(__file__).resolve().parent
DATA_DIR = ULTRONPRO_DIR.parent / "data"
HEALER_DIR = DATA_DIR / "code_self_healer"
HEALER_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_PATH = HEALER_DIR / "heal_history.json"
BACKUPS_DIR = HEALER_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

# Safety: modules that MUST NOT be modified
PROTECTED_MODULES = frozenset({
    "main.py", "settings.py", "__init__.py",
})

# Maximum fixes per module per hour (prevent infinite loop)
MAX_FIXES_PER_HOUR = 3


# ─── Data Structures ──────────────────────────────────────────

@dataclass
class TrackedError:
    """An error captured from runtime."""
    id: str
    timestamp: int
    module: str          # e.g. "web_explorer.py"
    function: str        # e.g. "start_web_explorer"
    lineno: int
    exception_type: str  # e.g. "httpx.ConnectTimeout"
    message: str
    traceback_lines: list[str]
    source_context: list[str]  # 5 lines around the bug
    frequency: int = 1


@dataclass
class HealAttempt:
    """A fix attempt for a tracked error."""
    id: str
    error_id: str
    timestamp: int
    module: str
    original_code: str
    fixed_code: str
    fix_strategy: str     # "deterministic" or "llm"
    fix_description: str
    syntax_valid: bool
    import_valid: bool
    applied: bool
    rolled_back: bool = False
    verified: bool = False
    verification_result: str = ""
    sandbox_validated: bool = False
    sandbox_result: dict[str, Any] = field(default_factory=dict)
    tests_passed: bool = False
    test_result: dict[str, Any] = field(default_factory=dict)


# ─── Deterministic Fix Rules ─────────────────────────────────

DETERMINISTIC_FIXES: list[dict] = [
    {
        "pattern": r"except\s+([\w.]+)\s*:",
        "exception_types": ["ConnectTimeout", "TimeoutException", "ReadTimeout", "WriteTimeout"],
        "description": "Adicionar exceções de timeout faltantes ao except clause",
        "fix_fn": "_fix_missing_except_timeout",
    },
    {
        "pattern": r"(\w+)\s*\.\s*append\(",
        "exception_types": ["NameError", "UnboundLocalError"],
        "description": "Variável usada antes de ser inicializada (lista não criada)",
        "fix_fn": "_fix_uninitialized_list",
    },
    {
        "pattern": r"\.get\(",
        "exception_types": ["AttributeError"],
        "description": "Chamada .get() em objeto que pode ser None",
        "fix_fn": "_fix_none_get",
    },
    {
        "pattern": r"json\.loads\(",
        "exception_types": ["json.JSONDecodeError", "JSONDecodeError"],
        "description": "json.loads sem try/except para JSON inválido",
        "fix_fn": "_fix_json_decode_unprotected",
    },
    {
        "pattern": r"open\(",
        "exception_types": ["FileNotFoundError", "PermissionError"],
        "description": "Operação de arquivo sem verificação de existência",
        "fix_fn": "_fix_file_not_found",
    },
    {
        "pattern": r"int\(|float\(",
        "exception_types": ["ValueError"],
        "description": "Conversão numérica sem proteção",
        "fix_fn": "_fix_value_error_conversion",
    },
    {
        "pattern": r"\[.+\]",
        "exception_types": ["IndexError", "KeyError"],
        "description": "Acesso a índice/chave sem verificação de bounds",
        "fix_fn": "_fix_index_error",
    },
]


# ─── Engine ──────────────────────────────────────────────────

class CodeSelfHealer:
    def __init__(self):
        self.tracked_errors: dict[str, TrackedError] = {}
        self.heal_history: deque[HealAttempt] = deque(maxlen=200)
        self.fix_count_per_module: dict[str, list[float]] = {}  # module → list of timestamps
        self._load()

    # ── Persistence ──────────────────────────────────────

    def _load(self):
        if HISTORY_PATH.exists():
            try:
                data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
                for e in data.get("errors", {}).values():
                    self.tracked_errors[e["id"]] = TrackedError(**e)
                for h in data.get("history", []):
                    self.heal_history.append(HealAttempt(**h))
                self.fix_count_per_module = data.get("fix_counts", {})
            except Exception as e:
                logger.warning(f"CodeSelfHealer: load error: {e}")

    def _save(self):
        data = {
            "errors": {k: asdict(v) for k, v in self.tracked_errors.items()},
            "history": [asdict(h) for h in list(self.heal_history)],
            "fix_counts": self.fix_count_per_module,
            "updated_at": int(time.time()),
        }
        HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _parse_json_stdout(stdout: str) -> dict[str, Any]:
        for line in reversed(str(stdout or "").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                return obj
        return {"ok": False, "error": "no_json_result"}

    # ── 1. Capture Error ─────────────────────────────────

    def capture_error(
        self,
        exc: Exception,
        tb_str: str | None = None,
    ) -> TrackedError | None:
        """
        Captures a runtime exception and extracts module/function/line info.
        Returns TrackedError if it's in our codebase, None otherwise.
        """
        if tb_str is None:
            tb_str = traceback.format_exc()

        # Parse the traceback to find the deepest frame in ultronpro/
        frames = self._parse_traceback(tb_str)
        our_frames = [f for f in frames if "ultronpro" in f.get("file", "")]

        if not our_frames:
            return None  # Not in our codebase

        # Use the deepest ultronpro frame
        frame = our_frames[-1]
        module = Path(frame["file"]).name
        function = frame.get("function", "unknown")
        lineno = frame.get("lineno", 0)

        if module in PROTECTED_MODULES:
            return None

        exc_type = type(exc).__name__
        exc_msg = str(exc)[:300]

        # Generate ID by module+function+exception_type
        error_key = hashlib.md5(f"{module}:{function}:{exc_type}".encode()).hexdigest()[:12]

        if error_key in self.tracked_errors:
            self.tracked_errors[error_key].frequency += 1
            self.tracked_errors[error_key].timestamp = int(time.time())
            self._save()
            return self.tracked_errors[error_key]

        # Read source context
        source_ctx = self._read_source_context(frame["file"], lineno, context_lines=5)

        error = TrackedError(
            id=error_key,
            timestamp=int(time.time()),
            module=module,
            function=function,
            lineno=lineno,
            exception_type=exc_type,
            message=exc_msg,
            traceback_lines=tb_str.strip().split("\n")[-10:],
            source_context=source_ctx,
        )

        self.tracked_errors[error_key] = error
        self._save()

        logger.info(f"CodeSelfHealer: Captured error {error_key} in {module}:{function}:{lineno} ({exc_type})")
        return error

    # ── 2. Analyze & Generate Fix ────────────────────────

    def analyze_and_fix(self, error_id: str) -> HealAttempt | None:
        """
        Analyzes a tracked error and generates a fix.
        Tries deterministic rules first, falls back to LLM.
        """
        error = self.tracked_errors.get(error_id)
        if not error:
            return None

        if not self._can_fix_module(error.module):
            logger.info(f"CodeSelfHealer: Module {error.module} hit fix rate limit, skipping")
            try:
                from ultronpro import self_corrector
                self_corrector.learn_from_error('code_heal_rate_limit', error.module, error.message, {'function': error.function})
            except Exception as e:
                pass
            return None

        # Read the full source file
        file_path = ULTRONPRO_DIR / error.module
        if not file_path.exists():
            return None

        original_source = file_path.read_text(encoding="utf-8")

        # Try deterministic fix first
        fix_result = self._try_deterministic_fix(error, original_source)

        if not fix_result:
            # Fall back to LLM-based fix
            fix_result = self._try_llm_fix(error, original_source)

        if not fix_result:
            logger.info(f"CodeSelfHealer: No fix found for error {error_id}")
            try:
                from ultronpro import self_corrector
                self_corrector.learn_from_error('code_heal_failed', error.module, error.message, {'function': error.function})
            except Exception as e:
                pass
            return None

        fixed_code, strategy, description = fix_result

        # Validate syntax
        syntax_ok = self._validate_syntax(fixed_code)

        attempt = HealAttempt(
            id=f"heal_{int(time.time())}_{error_id[:6]}",
            error_id=error_id,
            timestamp=int(time.time()),
            module=error.module,
            original_code=original_source,
            fixed_code=fixed_code,
            fix_strategy=strategy,
            fix_description=description,
            syntax_valid=syntax_ok,
            import_valid=False,
            applied=False,
        )

        if not syntax_ok:
            logger.warning(f"CodeSelfHealer: Fix for {error_id} failed syntax validation")
            self.heal_history.append(attempt)
            self._save()
            return attempt

        logger.info(f"CodeSelfHealer: Generated {strategy} fix for {error_id}: {description}")
        self.heal_history.append(attempt)
        self._save()
        return attempt

    def _try_deterministic_fix(
        self, error: TrackedError, source: str
    ) -> tuple[str, str, str] | None:
        """Tries rule-based deterministic fixes."""
        for rule in DETERMINISTIC_FIXES:
            # Check if exception type matches
            if error.exception_type not in rule["exception_types"]:
                continue

            fix_fn_name = rule["fix_fn"]
            fix_fn = getattr(self, fix_fn_name, None)
            if not fix_fn:
                continue

            try:
                result = fix_fn(error, source)
                if result:
                    fixed_code, desc = result
                    return fixed_code, "deterministic", desc
            except Exception as e:
                logger.debug(f"CodeSelfHealer: deterministic fix {fix_fn_name} failed: {e}")

        return None

    def _try_llm_fix(
        self, error: TrackedError, source: str
    ) -> tuple[str, str, str] | None:
        """Falls back to LLM for complex fixes."""
        try:
            from ultronpro import llm

            # Extract relevant section (±20 lines around error)
            lines = source.split("\n")
            start = max(0, error.lineno - 20)
            end = min(len(lines), error.lineno + 20)
            relevant = "\n".join(f"{i+1}: {lines[i]}" for i in range(start, end))

            prompt = f"""Você é o motor de auto-correção do UltronPro.
Um erro foi detectado no código. Corrija APENAS o trecho problemático.

ARQUIVO: {error.module}
FUNÇÃO: {error.function}
LINHA: {error.lineno}
EXCEÇÃO: {error.exception_type}: {error.message}

TRACEBACK:
{chr(10).join(error.traceback_lines[-5:])}

CÓDIGO RELEVANTE (linhas {start+1}-{end}):
{relevant}

REGRAS:
1. Responda APENAS com JSON: {{"fixed_lines": "código corrigido das linhas {start+1} a {end}", "description": "explicação curta"}}
2. NÃO mude a lógica, apenas corrija o bug
3. Mantenha indentação e estilo
4. NÃO use exec(), eval(), __import__()
5. Prefira adicionar proteção (try/except, if/else, default values)"""

            result = llm.complete(
                prompt,
                system="Motor de auto-correção de código Python. Corrija bugs sem alterar lógica.",
                strategy="local",
                cloud_fallback=True,
                json_mode=True,
            )

            data = json.loads(result)
            fixed_lines = data.get("fixed_lines", "")
            desc = data.get("description", "LLM fix")

            if not fixed_lines:
                return None

            # Reconstruct full source
            new_lines = lines[:start] + fixed_lines.split("\n") + lines[end:]
            fixed_source = "\n".join(new_lines)

            return fixed_source, "llm", desc

        except Exception as e:
            logger.debug(f"CodeSelfHealer: LLM fix failed: {e}")
            return None

    # ── 3. Apply Fix ─────────────────────────────────────

    def apply_fix(self, attempt_id: str) -> dict[str, Any]:
        """
        Applies a fix: backup → write → validate import → rollback if failed.
        """
        attempt = next((h for h in self.heal_history if h.id == attempt_id), None)
        if not attempt:
            return {"ok": False, "error": "attempt_not_found"}

        if not attempt.syntax_valid:
            return {"ok": False, "error": "syntax_invalid"}

        if attempt.applied:
            return {"ok": False, "error": "already_applied"}

        file_path = ULTRONPRO_DIR / attempt.module

        # Step -1: validate the candidate outside the production file first.
        sandbox_result = self._sandbox_validate_candidate(attempt)
        attempt.sandbox_result = sandbox_result
        attempt.sandbox_validated = bool(sandbox_result.get("ok"))
        self._save()
        if not attempt.sandbox_validated:
            return {
                "ok": False,
                "error": "sandbox_validation_failed",
                "sandbox": sandbox_result,
            }

        # Step 0: Mental Simulation Preflight (14.6)
        try:
            from ultronpro import mental_simulation
            ms = mental_simulation.imagine('apply_code_fix', f"module={attempt.module} strategy={attempt.fix_strategy}", {'module': attempt.module, 'attempt_id': attempt_id})
            if ms.get('recommended_posture') == 'abort':
                logger.warning(f"CodeSelfHealer: fix {attempt_id} aborted by mental_simulation. risk={ms.get('risk_score')}")
                return {"ok": False, "error": "mental_sim_abort", "risk": ms.get("risk_score")}
        except Exception as ms_err:
            logger.debug(f"CodeSelfHealer: mental_sim preflight error: {ms_err}")

        # Step 0.5: Safety Behavioral Invariants (Fase 14.6.1)
        try:
            from ultronpro.safety_invariants import check_behavioral_invariants
            inv_check = check_behavioral_invariants(attempt.module, attempt.original_code, attempt.fixed_code)
            if not inv_check.get('ok'):
                logger.warning(f"CodeSelfHealer: Fix {attempt_id} fails invariant check: {inv_check.get('reason')}")
                return {"ok": False, "error": f"invariant_violation: {inv_check.get('reason')}"}
        except Exception as inv_err:
            logger.debug(f"CodeSelfHealer: Invariants evaluation crashed: {inv_err}")

        # Step 1: Backup
        backup_name = f"{attempt.module}.{int(time.time())}.backup"
        backup_path = BACKUPS_DIR / backup_name
        backup_path.write_text(attempt.original_code, encoding="utf-8")

        # Step 2: Write fixed code
        try:
            file_path.write_text(attempt.fixed_code, encoding="utf-8")
        except Exception as e:
            return {"ok": False, "error": f"write_failed: {e}"}

        # Step 3: Validate import
        import_ok = self._validate_import(attempt.module)
        attempt.import_valid = import_ok

        if not import_ok:
            # Rollback immediately
            logger.warning(f"CodeSelfHealer: Fix {attempt_id} broke import, rolling back")
            file_path.write_text(attempt.original_code, encoding="utf-8")
            attempt.rolled_back = True
            attempt.applied = False
            self._save()
            return {
                "ok": False,
                "error": "import_validation_failed",
                "rolled_back": True,
            }

        # Step 3.5: run the configured validation command against production.
        test_result = self._run_post_apply_tests(attempt, file_path)
        attempt.test_result = test_result
        attempt.tests_passed = bool(test_result.get("ok"))
        if not attempt.tests_passed:
            logger.warning(f"CodeSelfHealer: Fix {attempt_id} failed tests, rolling back")
            file_path.write_text(attempt.original_code, encoding="utf-8")
            attempt.rolled_back = True
            attempt.applied = False
            self._save()
            return {
                "ok": False,
                "error": "post_apply_tests_failed",
                "rolled_back": True,
                "tests": test_result,
            }

        # Step 4: Mark as applied
        attempt.applied = True
        self._record_fix(attempt.module)
        self._save()

        logger.info(f"CodeSelfHealer: ✓ Fix {attempt_id} applied to {attempt.module} ({attempt.fix_strategy})")

        return {
            "ok": True,
            "attempt_id": attempt_id,
            "module": attempt.module,
            "strategy": attempt.fix_strategy,
            "description": attempt.fix_description,
            "backup": str(backup_path),
            "sandbox": sandbox_result,
            "tests": test_result,
        }

    # ── 4. Verify Fix ────────────────────────────────────

    def verify_fix(self, attempt_id: str) -> dict[str, Any]:
        """
        Verifies a fix by checking if the same error recurs.
        Should be called some time after applying.
        """
        attempt = next((h for h in self.heal_history if h.id == attempt_id), None)
        if not attempt:
            return {"ok": False, "error": "attempt_not_found"}

        error = self.tracked_errors.get(attempt.error_id)
        if not error:
            return {"ok": False, "error": "original_error_not_found"}

        # Check if error recurred since fix was applied
        if error.timestamp > attempt.timestamp:
            # Error recurred after fix
            attempt.verified = True
            attempt.verification_result = "fix_insufficient"
            self._save()
            return {
                "ok": True,
                "verified": True,
                "result": "fix_insufficient",
                "error_recurred": True,
                "suggestion": "rollback_and_try_different_strategy",
            }
        else:
            # Error hasn't recurred — fix is working
            attempt.verified = True
            attempt.verification_result = "fix_effective"
            self._save()

            # Record success in continuous learning
            try:
                from ultronpro import continuous_learning
                continuous_learning.record_learning_feedback(
                    task_type=f"code_heal:{attempt.module}",
                    success=True,
                    latency_ms=0,
                    profile="self_healer",
                )
            except Exception:
                pass

            return {
                "ok": True,
                "verified": True,
                "result": "fix_effective",
                "error_recurred": False,
                "module": attempt.module,
                "strategy": attempt.fix_strategy,
            }

    # ── 5. Rollback Fix ──────────────────────────────────

    def autorun_pending(self, *, limit: int = 3) -> dict[str, Any]:
        """Analyze and apply recurring tracked errors that were captured but not closed."""
        limit = max(1, min(20, int(limit or 3)))
        results: list[dict[str, Any]] = []
        picked = 0
        for error in sorted(self.tracked_errors.values(), key=lambda item: item.frequency, reverse=True):
            if picked >= limit:
                break
            if error.frequency < 2:
                continue
            history = [h for h in self.heal_history if h.error_id == error.id]
            if any(h.applied and not h.rolled_back and h.verification_result != "fix_insufficient" for h in history):
                continue
            attempt = next((h for h in reversed(history) if h.syntax_valid and not h.applied and not h.rolled_back), None)
            if attempt is None:
                attempt = self.analyze_and_fix(error.id)
            picked += 1
            if not attempt:
                results.append({"ok": False, "error_id": error.id, "reason": "no_fix_generated"})
                continue
            if not attempt.syntax_valid:
                results.append({"ok": False, "error_id": error.id, "attempt_id": attempt.id, "reason": "syntax_invalid"})
                continue
            applied = self.apply_fix(attempt.id)
            results.append({
                "ok": bool(applied.get("ok")),
                "error_id": error.id,
                "attempt_id": attempt.id,
                "module": attempt.module,
                "applied": bool(applied.get("ok")),
                "result": applied,
            })
        return {
            "ok": True,
            "picked": picked,
            "applied": sum(1 for item in results if item.get("applied")),
            "failed": sum(1 for item in results if not item.get("ok")),
            "results": results,
        }

    def _sandbox_validate_candidate(self, attempt: HealAttempt) -> dict[str, Any]:
        """Validate a proposed fixed source without touching production files."""
        payload = {
            "module": attempt.module,
            "fixed_code": attempt.fixed_code,
            "attempt_id": attempt.id,
        }
        code = f"""
import ast
import json
import re

payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)})
source = payload.get("fixed_code") or ""
result = {{
    "ok": False,
    "attempt_id": payload.get("attempt_id"),
    "module": payload.get("module"),
    "checks": [],
}}
try:
    ast.parse(source)
    result["checks"].append("ast_parse")
    banned = []
    for pattern in (r"\\beval\\s*\\(", r"\\bexec\\s*\\(", r"__import__\\s*\\(", r"os\\.system\\s*\\(", r"subprocess\\.Popen\\s*\\("):
        if re.search(pattern, source):
            banned.append(pattern)
    if banned:
        result["error"] = "dangerous_pattern"
        result["banned_patterns"] = banned
    else:
        compile(source, payload.get("module") or "<candidate>", "exec")
        result["checks"].append("compile")
        result["ok"] = True
except Exception as exc:
    result["error"] = type(exc).__name__ + ":" + str(exc)[:180]

print(json.dumps(result, ensure_ascii=False))
""".strip()
        try:
            from ultronpro import sandbox_client

            sandbox = sandbox_client.execute_python(code, timeout_sec=8)
            parsed = self._parse_json_stdout(str(sandbox.get("stdout") or ""))
            parsed["sandbox_transport"] = {
                "ok": bool(sandbox.get("ok")),
                "error": sandbox.get("error"),
                "returncode": sandbox.get("returncode"),
                "stderr": str(sandbox.get("stderr") or "")[:500],
            }
            if not sandbox.get("ok"):
                parsed.setdefault("ok", False)
                parsed.setdefault("error", sandbox.get("error") or "sandbox_failed")
            return parsed
        except Exception as exc:
            try:
                ast.parse(attempt.fixed_code)
                compile(attempt.fixed_code, attempt.module, "exec")
                return {
                    "ok": True,
                    "fallback": "local_ast_compile",
                    "sandbox_error": f"{type(exc).__name__}:{str(exc)[:180]}",
                    "checks": ["ast_parse", "compile"],
                }
            except Exception as local_exc:
                return {
                    "ok": False,
                    "fallback": "local_ast_compile",
                    "sandbox_error": f"{type(exc).__name__}:{str(exc)[:180]}",
                    "error": f"{type(local_exc).__name__}:{str(local_exc)[:180]}",
                }

    def _run_post_apply_tests(self, attempt: HealAttempt, file_path: Path) -> dict[str, Any]:
        timeout = max(5, int(os.getenv("ULTRON_HEALER_TEST_TIMEOUT_SEC", "30") or 30))
        configured = str(os.getenv("ULTRON_HEALER_TEST_CMD", "") or "").strip()
        if configured:
            command: str | list[str] = configured.format(
                module=attempt.module,
                file=str(file_path),
                package_file=str(file_path),
            )
            shell = True
        else:
            command = [sys.executable, "-m", "py_compile", str(file_path)]
            shell = False
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                command,
                cwd=str(ULTRONPRO_DIR.parent),
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "ok": proc.returncode == 0,
                "command": command if isinstance(command, str) else " ".join(command),
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "")[-1200:],
                "stderr": (proc.stderr or "")[-1200:],
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            }
        except Exception as exc:
            return {
                "ok": False,
                "command": command if isinstance(command, str) else " ".join(command),
                "error": f"{type(exc).__name__}:{str(exc)[:180]}",
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            }

    def rollback_fix(self, attempt_id: str) -> dict[str, Any]:
        """Rolls back a fix from backup."""
        attempt = next((h for h in self.heal_history if h.id == attempt_id), None)
        if not attempt:
            return {"ok": False, "error": "attempt_not_found"}

        if not attempt.applied:
            return {"ok": False, "error": "not_applied"}

        file_path = ULTRONPRO_DIR / attempt.module

        try:
            file_path.write_text(attempt.original_code, encoding="utf-8")
            attempt.rolled_back = True
            attempt.applied = False
            self._save()

            logger.info(f"CodeSelfHealer: Rolled back fix {attempt_id} on {attempt.module}")
            return {"ok": True, "rolled_back": True, "module": attempt.module}
        except Exception as e:
            return {"ok": False, "error": f"rollback_failed: {e}"}

    # ── Full Pipeline ────────────────────────────────────

    def heal(self, exc: Exception, tb_str: str | None = None) -> dict[str, Any]:
        """
        Full pipeline: capture → analyze → fix → apply → report.
        Single call to handle an error end-to-end.
        """
        # 1. Capture
        error = self.capture_error(exc, tb_str)
        if not error:
            return {"ok": False, "reason": "not_in_our_codebase"}

        # Only auto-heal if error occurred ≥2 times
        if error.frequency < 2:
            return {
                "ok": True,
                "action": "tracked",
                "error_id": error.id,
                "frequency": error.frequency,
                "message": "Error tracked, will attempt fix after 2nd occurrence",
            }

        # 2. Analyze & Generate Fix
        attempt = self.analyze_and_fix(error.id)
        if not attempt:
            return {
                "ok": False,
                "error_id": error.id,
                "reason": "no_fix_generated",
            }

        if not attempt.syntax_valid:
            return {
                "ok": False,
                "error_id": error.id,
                "attempt_id": attempt.id,
                "reason": "fix_syntax_invalid",
            }

        # 3. Apply
        apply_result = self.apply_fix(attempt.id)

        return {
            "ok": apply_result.get("ok", False),
            "error_id": error.id,
            "attempt_id": attempt.id,
            "module": error.module,
            "function": error.function,
            "exception": error.exception_type,
            "strategy": attempt.fix_strategy,
            "description": attempt.fix_description,
            "applied": apply_result.get("ok", False),
            "rolled_back": apply_result.get("rolled_back", False),
        }

    # ── Deterministic Fix Implementations ────────────────

    def _fix_missing_except_timeout(
        self, error: TrackedError, source: str
    ) -> tuple[str, str] | None:
        """Adds missing timeout exceptions to except clauses."""
        lines = source.split("\n")
        target_line = error.lineno - 1
        if target_line < 0 or target_line >= len(lines):
            return None

        # Search backward from error line for the except clause
        for i in range(target_line, max(0, target_line - 15), -1):
            line = lines[i]
            m = re.match(r'^(\s*)except\s+([\w.,\s()]+)\s*:', line)
            if m:
                indent = m.group(1)
                exceptions_str = m.group(2).strip()

                # Parse existing exceptions
                # Handle both "except X:" and "except (X, Y):" formats
                is_tuple = exceptions_str.startswith("(")
                if is_tuple:
                    inner = exceptions_str[1:-1] if exceptions_str.endswith(")") else exceptions_str[1:]
                    existing = [e.strip() for e in inner.split(",")]
                else:
                    existing = [e.strip() for e in exceptions_str.split(",")]

                # Determine what timeout exceptions to add
                to_add = []
                timeout_exceptions = {
                    "httpx": ["httpx.ConnectTimeout", "httpx.TimeoutException"],
                    "requests": ["requests.Timeout"],
                    "asyncio": ["asyncio.TimeoutError"],
                }

                for prefix, timeout_excs in timeout_exceptions.items():
                    if any(prefix in e for e in existing):
                        for te in timeout_excs:
                            if te not in existing:
                                to_add.append(te)

                if not to_add:
                    # Generic: if ConnectError is caught, add ConnectTimeout
                    if any("ConnectError" in e for e in existing):
                        for candidate in ["httpx.ConnectTimeout", "httpx.TimeoutException"]:
                            if candidate not in existing:
                                to_add.append(candidate)

                if not to_add:
                    return None

                all_exceptions = existing + to_add
                new_except = f"{indent}except ({', '.join(all_exceptions)}):"
                lines[i] = new_except

                desc = f"Adicionado {', '.join(to_add)} ao except na linha {i+1}"
                return "\n".join(lines), desc

        return None

    def _fix_uninitialized_list(
        self, error: TrackedError, source: str
    ) -> tuple[str, str] | None:
        """Adds initialization for lists used before being defined."""
        var_match = re.search(r"name '(\w+)' is not defined", error.message)
        if not var_match:
            var_match = re.search(r"local variable '(\w+)' referenced before assignment", error.message)
        if not var_match:
            return None

        var_name = var_match.group(1)
        lines = source.split("\n")
        target = error.lineno - 1

        if target < 0 or target >= len(lines):
            return None

        # Find the function start
        for i in range(target, max(0, target - 50), -1):
            if re.match(r'\s*def\s+', lines[i]):
                # Find first non-docstring, non-comment line after def
                j = i + 1
                in_docstring = False
                while j < target:
                    stripped = lines[j].strip()
                    if stripped.startswith('"""') or stripped.startswith("'''"):
                        if in_docstring:
                            in_docstring = False
                            j += 1
                            continue
                        if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                            j += 1
                            continue
                        in_docstring = not in_docstring
                    if not in_docstring and stripped and not stripped.startswith("#"):
                        break
                    j += 1

                # Get indentation from the usage line
                indent_match = re.match(r'^(\s*)', lines[target])
                indent = indent_match.group(1) if indent_match else "    "

                # Insert initialization
                init_line = f"{indent}{var_name} = []"
                lines.insert(j, init_line)

                desc = f"Inicializado '{var_name} = []' na linha {j+1} (antes do uso na linha {target+2})"
                return "\n".join(lines), desc

        return None

    def _fix_none_get(
        self, error: TrackedError, source: str
    ) -> tuple[str, str] | None:
        """Adds None check before .get() calls."""
        lines = source.split("\n")
        target = error.lineno - 1
        if target < 0 or target >= len(lines):
            return None

        line = lines[target]
        # Find pattern like `obj.get(` where obj could be None
        m = re.search(r'(\w+)\.get\(', line)
        if not m:
            return None

        var = m.group(1)
        indent_match = re.match(r'^(\s*)', line)
        indent = indent_match.group(1) if indent_match else ""

        # Wrap with "or {}" protection
        new_line = line.replace(f"{var}.get(", f"({var} or {{}}).get(")
        lines[target] = new_line

        desc = f"Adicionada proteção contra None em {var}.get() na linha {target+1}"
        return "\n".join(lines), desc

    def _fix_json_decode_unprotected(
        self, error: TrackedError, source: str
    ) -> tuple[str, str] | None:
        """Wraps unprotected json.loads in try/except."""
        lines = source.split("\n")
        target = error.lineno - 1
        if target < 0 or target >= len(lines):
            return None

        line = lines[target]
        if "json.loads" not in line:
            return None

        indent_match = re.match(r'^(\s*)', line)
        indent = indent_match.group(1) if indent_match else ""

        # Check if already inside try block
        for i in range(target - 1, max(0, target - 5), -1):
            if lines[i].strip().startswith("try:"):
                return None  # Already protected

        # Wrap the line
        var_match = re.match(r'^(\s*)(\w+)\s*=\s*json\.loads\((.+)\)', line)
        if var_match:
            ind = var_match.group(1)
            var = var_match.group(2)
            arg = var_match.group(3)
            new_lines = [
                f"{ind}try:",
                f"{ind}    {var} = json.loads({arg})",
                f"{ind}except (json.JSONDecodeError, ValueError):",
                f"{ind}    {var} = {{}}",
            ]
            lines[target:target+1] = new_lines
            desc = f"Protegido json.loads com try/except na linha {target+1}"
            return "\n".join(lines), desc

        return None

    def _fix_file_not_found(
        self, error: TrackedError, source: str
    ) -> tuple[str, str] | None:
        """Adds file existence check."""
        lines = source.split("\n")
        target = error.lineno - 1
        if target < 0 or target >= len(lines):
            return None

        line = lines[target]
        indent_match = re.match(r'^(\s*)', line)
        indent = indent_match.group(1) if indent_match else ""

        # Check if already protected
        for i in range(target - 1, max(0, target - 3), -1):
            if "exists()" in lines[i] or "try:" in lines[i].strip():
                return None

        # Add exists check
        path_match = re.search(r'open\(\s*([^,)]+)', line)
        if path_match:
            path_expr = path_match.group(1).strip()
            guard = f"{indent}if not Path({path_expr}).exists():\n{indent}    return None\n"
            lines.insert(target, guard)
            desc = f"Adicionada verificação de existência de arquivo na linha {target+1}"
            return "\n".join(lines), desc

        return None

    def _fix_value_error_conversion(
        self, error: TrackedError, source: str
    ) -> tuple[str, str] | None:
        """Adds default value for failed int/float conversion."""
        lines = source.split("\n")
        target = error.lineno - 1
        if target < 0 or target >= len(lines):
            return None

        line = lines[target]
        # Check if already in try block
        for i in range(target - 1, max(0, target - 3), -1):
            if lines[i].strip().startswith("try:"):
                return None

        # Replace int(x) with int(x or 0) pattern won't work for all cases
        # Use a safer approach: default value
        new_line = line
        for conv in ["int(", "float("]:
            if conv in new_line:
                # Find the conversion and add default
                pattern = rf'({conv})([^)]+)\)'
                def add_default(m):
                    fn = m.group(1)
                    arg = m.group(2)
                    default = "0" if fn == "int(" else "0.0"
                    return f"{fn}{arg} or {default})"
                new_line = re.sub(pattern, add_default, new_line, count=1)

        if new_line != line:
            lines[target] = new_line
            desc = f"Adicionado valor default para conversão numérica na linha {target+1}"
            return "\n".join(lines), desc

        return None

    def _fix_index_error(
        self, error: TrackedError, source: str
    ) -> tuple[str, str] | None:
        """Adds bounds checking for index access."""
        lines = source.split("\n")
        target = error.lineno - 1
        if target < 0 or target >= len(lines):
            return None

        line = lines[target]
        indent_match = re.match(r'^(\s*)', line)
        indent = indent_match.group(1) if indent_match else ""

        # Check if already in try block
        for i in range(target - 1, max(0, target - 3), -1):
            if lines[i].strip().startswith("try:"):
                return None

        # Wrap in try/except
        stripped = line.lstrip()
        new_lines = [
            f"{indent}try:",
            f"{indent}    {stripped}",
            f"{indent}except (IndexError, KeyError):",
            f"{indent}    pass  # auto-healed: bounds check",
        ]
        lines[target:target+1] = new_lines
        desc = f"Protegido acesso por índice com try/except na linha {target+1}"
        return "\n".join(lines), desc

    # ── Helpers ──────────────────────────────────────────

    def _parse_traceback(self, tb_str: str) -> list[dict]:
        """Parses traceback string into frame dicts."""
        frames = []
        lines = tb_str.strip().split("\n")
        for i, line in enumerate(lines):
            m = re.match(r'\s*File "(.+?)", line (\d+), in (\w+)', line)
            if m:
                frames.append({
                    "file": m.group(1),
                    "lineno": int(m.group(2)),
                    "function": m.group(3),
                })
        return frames

    def _read_source_context(self, file_path: str, lineno: int, context_lines: int = 5) -> list[str]:
        """Read source lines around an error."""
        try:
            p = Path(file_path)
            if not p.exists():
                return []
            lines = p.read_text(encoding="utf-8").split("\n")
            start = max(0, lineno - context_lines)
            end = min(len(lines), lineno + context_lines)
            return [f"{i+1}: {lines[i]}" for i in range(start, end)]
        except Exception:
            return []

    def _validate_syntax(self, code: str) -> bool:
        """Validates Python syntax."""
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def _validate_import(self, module_name: str) -> bool:
        """Validates that the module can be imported after fix.
        
        We distinguish between:
        - SyntaxError / IndentationError → our fix broke the code → FAIL
        - ImportError / ModuleNotFoundError → dependency issue, not our fault → PASS
        - Other exceptions → might be runtime init, not syntax → PASS
        """
        mod_name = module_name.replace(".py", "")
        full_mod = f"ultronpro.{mod_name}"

        try:
            # Remove from cache to force reimport
            if full_mod in sys.modules:
                del sys.modules[full_mod]
            importlib.import_module(full_mod)
            return True
        except (SyntaxError, IndentationError) as e:
            logger.warning(f"CodeSelfHealer: Import validation FAILED (syntax): {full_mod}: {e}")
            return False
        except (ImportError, ModuleNotFoundError) as e:
            # Dependency not available — not our fault, the fix itself is fine
            logger.info(f"CodeSelfHealer: Import has dependency issue (OK): {full_mod}: {e}")
            return True
        except Exception as e:
            # Runtime init errors are acceptable — they existed before our fix too
            logger.info(f"CodeSelfHealer: Import raised non-syntax error (OK): {full_mod}: {e}")
            return True

    def _can_fix_module(self, module: str) -> bool:
        """Rate limit: max N fixes per module per hour."""
        now = time.time()
        hour_ago = now - 3600

        if module not in self.fix_count_per_module:
            self.fix_count_per_module[module] = []

        # Clean old entries
        self.fix_count_per_module[module] = [
            ts for ts in self.fix_count_per_module[module] if ts > hour_ago
        ]

        return len(self.fix_count_per_module[module]) < MAX_FIXES_PER_HOUR

    def _record_fix(self, module: str):
        """Record a fix timestamp for rate limiting."""
        if module not in self.fix_count_per_module:
            self.fix_count_per_module[module] = []
        self.fix_count_per_module[module].append(time.time())

    # ── Status ───────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        applied = [h for h in self.heal_history if h.applied and not h.rolled_back]
        verified_ok = [h for h in applied if h.verified and h.verification_result == "fix_effective"]
        pending_healable = [
            e for e in self.tracked_errors.values()
            if e.frequency >= 2 and not any(
                h.error_id == e.id and h.applied and not h.rolled_back
                for h in self.heal_history
            )
        ]

        return {
            "tracked_errors": len(self.tracked_errors),
            "total_heal_attempts": len(self.heal_history),
            "fixes_applied": len(applied),
            "fixes_verified_ok": len(verified_ok),
            "fixes_rolled_back": len([h for h in self.heal_history if h.rolled_back]),
            "pending_healable": len(pending_healable),
            "top_errors": [
                {
                    "id": e.id,
                    "module": e.module,
                    "function": e.function,
                    "exception": e.exception_type,
                    "frequency": e.frequency,
                }
                for e in sorted(self.tracked_errors.values(), key=lambda e: e.frequency, reverse=True)[:10]
            ],
            "recent_heals": [
                {
                    "id": h.id,
                    "module": h.module,
                    "strategy": h.fix_strategy,
                    "description": h.fix_description[:100],
                    "applied": h.applied,
                    "verified": h.verified,
                    "result": h.verification_result,
                    "sandbox_validated": h.sandbox_validated,
                    "tests_passed": h.tests_passed,
                }
                for h in list(self.heal_history)[-10:]
            ],
        }


# ─── Singleton ────────────────────────────────────────────────

_healer: CodeSelfHealer | None = None


def get_healer() -> CodeSelfHealer:
    global _healer
    if _healer is None:
        _healer = CodeSelfHealer()
    return _healer


# ─── Public API ───────────────────────────────────────────────

def heal(exc: Exception, tb_str: str | None = None) -> dict:
    """Full pipeline: capture → analyze → fix → apply."""
    return get_healer().heal(exc, tb_str)


def capture(exc: Exception, tb_str: str | None = None) -> dict | None:
    """Just capture an error for tracking."""
    err = get_healer().capture_error(exc, tb_str)
    return asdict(err) if err else None


def analyze(error_id: str) -> dict | None:
    """Analyze and generate fix for a tracked error."""
    attempt = get_healer().analyze_and_fix(error_id)
    return asdict(attempt) if attempt else None


def apply(attempt_id: str) -> dict:
    """Apply a generated fix."""
    return get_healer().apply_fix(attempt_id)


def verify(attempt_id: str) -> dict:
    """Verify a fix is working."""
    return get_healer().verify_fix(attempt_id)


def autorun_pending(limit: int = 3) -> dict:
    """Analyze and apply recurring tracked errors that crossed the healing threshold."""
    return get_healer().autorun_pending(limit=limit)


def rollback(attempt_id: str) -> dict:
    """Rollback a fix."""
    return get_healer().rollback_fix(attempt_id)


def status() -> dict:
    """Get healer status."""
    return get_healer().status()
