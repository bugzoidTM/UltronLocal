"""
UltronPro Patch Worktree System

Sistema de worktree isolado para patches cognitivos:
- Cada patch nasce em worktree própria
- Roda benchmark no sandbox
- Avaliação por judge
- Comparação de delta
- Merge só se passar na avaliação

Isso evita que o sistema "auto-saboteur" quebre o ambiente principal.
"""

import os
import re
import json
import time
import hashlib
import subprocess
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime


class PatchStatus(str, Enum):
    """Status de um patch."""
    CREATED = "created"
    BENCHMARKING = "benchmarking"
    BENCHMARK_PASS = "benchmark_pass"
    BENCHMARK_FAIL = "benchmark_fail"
    JUDGE_EVAL = "judge_eval"
    JUDGE_PASS = "judge_pass"
    JUDGE_FAIL = "judge_fail"
    MERGED = "merged"
    REJECTED = "rejected"
    REVERTED = "reverted"


class DeltaResult(str, Enum):
    """Resultado da comparação de delta."""
    IMPROVED = "improved"
    DEGRADED = "degraded"
    NEUTRAL = "neutral"
    ERROR = "error"


@dataclass
class PatchDelta:
    """Delta de um patch (antes/depois)."""
    metric: str
    before: float
    after: float
    delta: float
    delta_pct: float
    result: DeltaResult


@dataclass
class PatchBenchmark:
    """Resultado de benchmark de um patch."""
    patch_id: str
    worktree_path: str
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    tests_passed: int = 0
    tests_failed: int = 0
    metrics: Dict[str, float] = field(default_factory=dict)
    deltas: List[PatchDelta] = field(default_factory=list)
    passed: bool = False
    error: Optional[str] = None
    
    @property
    def duration_ms(self) -> int:
        if self.ended_at:
            return int((self.ended_at - self.started_at) * 1000)
        return 0


@dataclass
class PatchJudge:
    """Resultado de avaliação do judge."""
    patch_id: str
    quality_score: float
    risk_score: float
    reasoning: str
    recommendation: str  # "approve", "reject", "needs_review"
    passed: bool = False


@dataclass
class PatchWorktree:
    """
    Worktree isolado para um patch.
    
    Fluxo:
    1. CREATE: Worktree criada com branch isolada
    2. APPLY: Patch aplicado no worktree
    3. BENCHMARK: Roda benchmarks no sandbox
    4. JUDGE: Avaliação de qualidade/risco
    5. DELTA: Comparação antes/depois
    6. MERGE ou REJECT: Decisão final
    """
    patch_id: str
    branch_name: str
    worktree_path: str
    base_commit: str
    patch_content: str
    created_at: float = field(default_factory=time.time)
    status: PatchStatus = PatchStatus.CREATED
    
    benchmark: Optional[PatchBenchmark] = None
    judge: Optional[PatchJudge] = None
    deltas: List[PatchDelta] = field(default_factory=list)
    
    merged_at: Optional[float] = None
    error: Optional[str] = None


class PatchWorktreeManager:
    """
    Gerenciador de worktrees para patches cognitivos.
    
    Responsabilidades:
    1. Criar/remover worktrees isoladas
    2. Aplicar patches em worktrees
    3. Executar benchmarks em sandbox
    4. Avaliar com judge
    5. Controlar merge
    """
    
    def __init__(self, repo_path: Optional[str] = None):
        self.repo_path = Path(repo_path) if repo_path else Path(__file__).resolve().parent.parent.parent
        self.worktrees_root = self.repo_path / ".patch-worktrees"
        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        
        self._patches: Dict[str, PatchWorktree] = {}
        self._audit_path = self.repo_path / "data" / "patch_audit.jsonl"
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _run_git(self, *args, cwd: Optional[Path] = None) -> tuple[int, str, str]:
        """Executa comando git."""
        cwd = cwd or self.repo_path
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "git command timeout"
        except Exception as e:
            return -1, "", str(e)
    
    def _generate_branch_name(self, patch_id: str) -> str:
        """Gera nome de branch para o patch."""
        return f"patch/{patch_id[:8]}-{int(time.time())}"
    
    # ==================== WORKTREE LIFECYCLE ====================
    
    def create_worktree(self, patch_id: str, patch_content: str) -> Optional[PatchWorktree]:
        """Cria worktree isolada para um patch."""
        branch_name = self._generate_branch_name(patch_id)
        worktree_path = self.worktrees_root / patch_id[:12]
        
        worktree_path.mkdir(parents=True, exist_ok=True)
        
        rc, out, err = self._run_git("rev-parse", "HEAD")
        if rc != 0:
            self.error = f"Failed to get HEAD: {err}"
            return None
        
        base_commit = out.strip()
        
        rc, out, err = self._run_git(
            "checkout", "-b", branch_name,
            cwd=self.repo_path
        )
        if rc != 0:
            self.error = f"Failed to create branch: {err}"
            return None
        
        rc, out, err = self._run_git(
            "worktree", "add", "--detach",
            str(worktree_path),
            cwd=self.repo_path
        )
        if rc != 0:
            self.error = f"Failed to create worktree: {err}"
            return None
        
        patch = PatchWorktree(
            patch_id=patch_id,
            branch_name=branch_name,
            worktree_path=str(worktree_path),
            base_commit=base_commit,
            patch_content=patch_content,
        )
        
        self._patches[patch_id] = patch
        self._write_audit(patch, "created")
        
        return patch
    
    def apply_patch(self, patch: PatchWorktree) -> bool:
        """Aplica o patch no worktree."""
        worktree_path = Path(patch.worktree_path)
        
        patch_file = worktree_path / f"{patch.patch_id}.patch"
        patch_file.write_text(patch.patch_content, encoding="utf-8")
        
        rc, out, err = self._run_git(
            "apply", str(patch_file),
            cwd=worktree_path
        )
        
        if rc != 0:
            patch.error = f"Patch apply failed: {err}"
            patch.status = PatchStatus.REJECTED
            self._write_audit(patch, "apply_failed")
            return False
        
        rc, out, err = self._run_git(
            "add", ".",
            cwd=worktree_path
        )
        
        rc, out, err = self._run_git(
            "commit", "-m", f"Apply patch {patch.patch_id}",
            cwd=worktree_path
        )
        
        if rc != 0:
            patch.error = f"Commit failed: {err}"
            patch.status = PatchStatus.REJECTED
            self._write_audit(patch, "commit_failed")
            return False
        
        patch.status = PatchStatus.BENCHMARKING
        self._write_audit(patch, "patch_applied")
        return True
    
    def remove_worktree(self, patch: PatchWorktree) -> bool:
        """Remove worktree e branch."""
        worktree_path = Path(patch.worktree_path)
        
        self._run_git("worktree", "remove", "--force", str(worktree_path))
        
        self._run_git("branch", "-D", patch.branch_name, cwd=self.repo_path)
        
        if worktree_path.exists():
            import shutil
            shutil.rmtree(worktree_path, ignore_errors=True)
        
        if patch.patch_id in self._patches:
            del self._patches[patch.patch_id]
        
        self._write_audit(patch, "worktree_removed")
        return True
    
    # ==================== BENCHMARK ====================
    
    def run_benchmark(self, patch: PatchWorktree) -> PatchBenchmark:
        """Executa benchmarks no worktree isolado."""
        patch.status = PatchStatus.BENCHMARKING
        benchmark = PatchBenchmark(
            patch_id=patch.patch_id,
            worktree_path=patch.worktree_path,
        )
        
        worktree_path = Path(patch.worktree_path)
        
        tests_passed = 0
        tests_failed = 0
        
        test_patterns = ["test_*.py", "*_test.py", "tests/"]
        for pattern in test_patterns:
            rc, out, err = self._run_git(
                "python", "-m", "pytest", pattern, "-v", "--tb=short",
                cwd=worktree_path
            )
            if rc == 0:
                tests_passed += 1
            else:
                tests_failed += 1
        
        benchmark.tests_passed = tests_passed
        benchmark.tests_failed = tests_failed
        
        import ast
        import sys
        sys.path.insert(0, str(worktree_path / "backend"))
        
        benchmark_result = self._run_python_benchmark(worktree_path)
        benchmark.metrics = benchmark_result.get("metrics", {})
        
        baseline = self._run_python_benchmark(self.repo_path)
        baseline_metrics = baseline.get("metrics", {})
        
        for metric, value in benchmark.metrics.items():
            baseline_val = baseline_metrics.get(metric, value)
            delta_val = value - baseline_val
            delta_pct = (delta_val / baseline_val * 100) if baseline_val != 0 else 0
            
            result = DeltaResult.IMPROVED
            if delta_val < -0.05 * abs(baseline_val):
                result = DeltaResult.DEGRADED
            elif abs(delta_val) <= 0.05 * abs(baseline_val):
                result = DeltaResult.NEUTRAL
            
            patch.deltas.append(PatchDelta(
                metric=metric,
                before=baseline_val,
                after=value,
                delta=delta_val,
                delta_pct=delta_pct,
                result=result,
            ))
        
        benchmark.deltas = patch.deltas
        benchmark.passed = (
            benchmark.tests_failed == 0 and
            not any(d.result == DeltaResult.DEGRADED for d in patch.deltas)
        )
        
        patch.benchmark = benchmark
        patch.status = PatchStatus.BENCHMARK_PASS if benchmark.passed else PatchStatus.BENCHMARK_FAIL
        benchmark.ended_at = time.time()
        
        self._write_audit(patch, "benchmark_complete")
        
        return benchmark
    
    def _run_python_benchmark(self, path: Path) -> Dict[str, Any]:
        """Roda benchmark Python no path."""
        benchmark_script = path / "backend" / "benchmark_suite.py"
        if not benchmark_script.exists():
            return {"ok": False, "metrics": {}}
        
        try:
            result = subprocess.run(
                ["python", str(benchmark_script)],
                cwd=str(path / "backend"),
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout)
                except:
                    return {"ok": True, "metrics": {}}
            
            return {"ok": False, "metrics": {}}
        except:
            return {"ok": False, "metrics": {}}
    
    # ==================== JUDGE ====================
    
    def evaluate_judge(self, patch: PatchWorktree) -> PatchJudge:
        """Avalia patch com judge."""
        patch.status = PatchStatus.JUDGE_EVAL
        
        quality_score = 0.7
        risk_score = 0.3
        reasoning = "Automated evaluation"
        
        if patch.benchmark:
            if patch.benchmark.passed:
                quality_score += 0.1
            if patch.benchmark.tests_failed > 0:
                quality_score -= 0.2
                risk_score += 0.1
        
        improved_deltas = sum(1 for d in patch.deltas if d.result == DeltaResult.IMPROVED)
        degraded_deltas = sum(1 for d in patch.deltas if d.result == DeltaResult.DEGRADED)
        
        if degraded_deltas > 0:
            quality_score -= 0.3
            risk_score += 0.3
        
        if improved_deltas > degraded_deltas:
            quality_score += 0.1
        
        quality_score = max(0.0, min(1.0, quality_score))
        risk_score = max(0.0, min(1.0, risk_score))
        
        if quality_score >= 0.7 and risk_score <= 0.3:
            recommendation = "approve"
            passed = True
        elif quality_score >= 0.5 and risk_score <= 0.5:
            recommendation = "needs_review"
            passed = True
        else:
            recommendation = "reject"
            passed = False
        
        judge = PatchJudge(
            patch_id=patch.patch_id,
            quality_score=quality_score,
            risk_score=risk_score,
            reasoning=reasoning,
            recommendation=recommendation,
            passed=passed,
        )
        
        patch.judge = judge
        patch.status = PatchStatus.JUDGE_PASS if passed else PatchStatus.JUDGE_FAIL
        
        self._write_audit(patch, "judge_complete")
        
        return judge
    
    # ==================== DELTA ====================
    
    def get_delta_summary(self, patch: PatchWorktree) -> Dict[str, Any]:
        """Retorna resumo de deltas do patch."""
        if not patch.deltas:
            return {"error": "No deltas computed"}
        
        improved = [d for d in patch.deltas if d.result == DeltaResult.IMPROVED]
        degraded = [d for d in patch.deltas if d.result == DeltaResult.DEGRADED]
        neutral = [d for d in patch.deltas if d.result == DeltaResult.NEUTRAL]
        
        return {
            "patch_id": patch.patch_id,
            "total_metrics": len(patch.deltas),
            "improved": len(improved),
            "degraded": len(degraded),
            "neutral": len(neutral),
            "overall": DeltaResult.IMPROVED.value if len(improved) > len(degraded) else DeltaResult.DEGRADED.value,
            "deltas": [
                {
                    "metric": d.metric,
                    "before": d.before,
                    "after": d.after,
                    "delta": d.delta,
                    "delta_pct": d.delta_pct,
                    "result": d.result.value,
                }
                for d in patch.deltas
            ],
        }
    
    # ==================== MERGE ====================
    
    def attempt_merge(self, patch: PatchWorktree) -> bool:
        """Tenta fazer merge do patch no repositório principal."""
        if not patch.benchmark or not patch.benchmark.passed:
            patch.error = "Benchmark not passed"
            patch.status = PatchStatus.REJECTED
            self._write_audit(patch, "merge_rejected_no_benchmark")
            return False
        
        if not patch.judge or not patch.judge.passed:
            patch.error = "Judge evaluation not passed"
            patch.status = PatchStatus.REJECTED
            self._write_audit(patch, "merge_rejected_no_judge")
            return False
        
        worktree_path = Path(patch.worktree_path)
        
        rc, out, err = self._run_git(
            "checkout", "main",
            cwd=self.repo_path
        )
        if rc != 0:
            self._run_git("checkout", "master", cwd=self.repo_path)
        
        rc, out, err = self._run_git(
            "merge", patch.branch_name,
            "--no-ff", "-m", f"Merge patch {patch.patch_id}",
            cwd=self.repo_path
        )
        
        if rc != 0:
            patch.error = f"Merge conflict: {err}"
            patch.status = PatchStatus.REJECTED
            self._write_audit(patch, "merge_conflict")
            return False
        
        patch.status = PatchStatus.MERGED
        patch.merged_at = time.time()
        self._write_audit(patch, "merged")
        
        self.remove_worktree(patch)
        
        return True
    
    def revert_patch(self, patch: PatchWorktree) -> bool:
        """Reverte o patch se foi mergeado."""
        if patch.status != PatchStatus.MERGED:
            return False
        
        rc, out, err = self._run_git(
            "revert", "--no-commit", "HEAD",
            cwd=self.repo_path
        )
        
        if rc == 0:
            self._run_git("commit", "-m", f"Revert patch {patch.patch_id}", cwd=self.repo_path)
            patch.status = PatchStatus.REVERTED
            self._write_audit(patch, "reverted")
            return True
        
        return False
    
    # ==================== FULL PIPELINE ====================
    
    def process_patch(self, patch_id: str, patch_content: str) -> Dict[str, Any]:
        """
        Processa um patch pelo pipeline completo:
        1. Criar worktree
        2. Aplicar patch
        3. Rodar benchmark
        4. Avaliar judge
        5. Retornar delta e decisão
        """
        patch = self.create_worktree(patch_id, patch_content)
        if not patch:
            return {"ok": False, "error": self.error}
        
        if not self.apply_patch(patch):
            self.remove_worktree(patch)
            return {"ok": False, "error": patch.error}
        
        benchmark = self.run_benchmark(patch)
        
        judge = self.evaluate_judge(patch)
        
        delta_summary = self.get_delta_summary(patch)
        
        merge_ok = self.attempt_merge(patch) if judge.passed else False
        
        return {
            "ok": merge_ok,
            "patch_id": patch_id,
            "status": patch.status.value,
            "benchmark": {
                "passed": benchmark.passed,
                "tests_passed": benchmark.tests_passed,
                "tests_failed": benchmark.tests_failed,
                "metrics": benchmark.metrics,
                "duration_ms": benchmark.duration_ms,
            },
            "judge": {
                "passed": judge.passed,
                "quality_score": judge.quality_score,
                "risk_score": judge.risk_score,
                "recommendation": judge.recommendation,
            },
            "delta": delta_summary,
            "merged": merge_ok,
            "error": patch.error,
        }
    
    # ==================== AUDIT ====================
    
    def _write_audit(self, patch: PatchWorktree, action: str):
        """Escreve entrada no audit log."""
        entry = {
            "ts": int(time.time()),
            "patch_id": patch.patch_id,
            "branch": patch.branch_name,
            "status": patch.status.value,
            "action": action,
            "error": patch.error,
            "benchmark_passed": patch.benchmark.passed if patch.benchmark else None,
            "judge_passed": patch.judge.passed if patch.judge else None,
        }
        
        try:
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
    
    def get_audit_log(self, patch_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Retorna entradas do audit log."""
        if not self._audit_path.exists():
            return []
        
        entries = []
        try:
            with self._audit_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if patch_id and entry.get("patch_id") != patch_id:
                            continue
                        entries.append(entry)
                    except:
                        continue
        except Exception:
            pass
        
        return entries[-limit:]
    
    # ==================== STATUS ====================
    
    def get_status(self) -> Dict[str, Any]:
        """Retorna status do sistema."""
        by_status: Dict[str, int] = {}
        for patch in self._patches.values():
            status = patch.status.value
            by_status[status] = by_status.get(status, 0) + 1
        
        return {
            "total_patches": len(self._patches),
            "by_status": by_status,
            "worktrees_root": str(self.worktrees_root),
            "worktrees_count": len(list(self.worktrees_root.iterdir())) if self.worktrees_root.exists() else 0,
        }
    
    def get_patch(self, patch_id: str) -> Optional[PatchWorktree]:
        """Retorna patch pelo ID."""
        return self._patches.get(patch_id)


# ==================== GLOBAL INSTANCE ====================

_worktree_manager: Optional[PatchWorktreeManager] = None

def get_patch_worktree_manager(repo_path: Optional[str] = None) -> PatchWorktreeManager:
    """Retorna instância global do manager."""
    global _worktree_manager
    if _worktree_manager is None:
        _worktree_manager = PatchWorktreeManager(repo_path)
    return _worktree_manager
