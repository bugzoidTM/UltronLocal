from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .local_llm import LocalQwenClient


_DANGEROUS_IMPORTS = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "pathlib",
    "shutil",
    "ctypes",
    "multiprocessing",
    "threading",
    "httpx",
    "openai",
}
_ALLOWED_IMPORTS = {"math", "re", "statistics", "datetime", "decimal"}
_DANGEROUS_CALLS = {"eval", "exec", "compile", "open", "__import__", "input", "globals", "locals", "vars"}


@dataclass
class TaskSpec:
    name: str
    filename: str
    description: str
    trigger_examples: list[str]
    test_command: str
    code: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSpec":
        return cls(
            name=str(data.get("name") or "tarefa_local").strip(),
            filename=_safe_filename(str(data.get("filename") or data.get("name") or "tarefa_local")),
            description=str(data.get("description") or "").strip(),
            trigger_examples=[str(x).strip() for x in (data.get("trigger_examples") or []) if str(x).strip()],
            test_command=str(data.get("test_command") or "").strip(),
            code=str(data.get("code") or "").strip(),
        )


class DynamicTaskManager:
    def __init__(self, *, root: Path | None = None, llm: LocalQwenClient | None = None) -> None:
        self.root = root or paths.tasks_dir()
        self.pending_dir = self.root / ".pending"
        self.sandbox_dir = self.root / ".sandbox"
        self.rollback_dir = self.root / ".rollback"
        self.manifest_path = self.root / "manifest.json"
        self.llm = llm or LocalQwenClient()
        for directory in (self.root, self.pending_dir, self.sandbox_dir, self.rollback_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def wants_task_creation(self, command: str) -> bool:
        text = _normalize_text(command)
        return any(
            marker in text
            for marker in (
                "cria uma tarefa",
                "crie uma tarefa",
                "criar uma tarefa",
                "nova tarefa",
                "gere uma tarefa",
            )
        )

    def prepare_task(self, command: str) -> dict[str, Any]:
        spec = self._generate_spec(command)
        validation = validate_task_code(spec.code)
        if not validation["ok"]:
            return {"ok": False, "stage": "validate", "error": validation["error"], "spec": spec.__dict__}
        sandbox = self._sandbox_code(spec.code, spec.test_command or command)
        pending_path = self.pending_dir / spec.filename
        pending_path.write_text(spec.code + "\n", encoding="utf-8")
        return {
            "ok": bool(sandbox["ok"]),
            "stage": "sandbox",
            "error": sandbox.get("error"),
            "sandbox": sandbox,
            "spec": spec.__dict__,
            "pending_path": str(pending_path),
        }

    def approve_task(self, spec_data: dict[str, Any]) -> dict[str, Any]:
        spec = TaskSpec.from_dict(spec_data)
        validation = validate_task_code(spec.code)
        if not validation["ok"]:
            return {"ok": False, "error": validation["error"], "stage": "validate"}
        sandbox = self._sandbox_code(spec.code, spec.test_command)
        if not sandbox["ok"]:
            return {"ok": False, "error": sandbox.get("error"), "stage": "sandbox", "sandbox": sandbox}

        dest = self.root / spec.filename
        backup_path = None
        if dest.exists():
            backup_path = self.rollback_dir / f"{dest.stem}.{int(time.time())}.py.bak"
            shutil.copy2(dest, backup_path)
        try:
            dest.write_text(spec.code + "\n", encoding="utf-8")
            manifest = self._load_manifest()
            manifest["tasks"][spec.filename] = {
                "name": spec.name,
                "filename": spec.filename,
                "description": spec.description,
                "trigger_examples": spec.trigger_examples,
                "status": "approved",
                "approved_at": int(time.time()),
                "backup": str(backup_path) if backup_path else "",
            }
            self._save_manifest(manifest)
            return {"ok": True, "path": str(dest), "sandbox": sandbox, "backup": str(backup_path) if backup_path else ""}
        except Exception as exc:
            if backup_path and backup_path.exists():
                shutil.copy2(backup_path, dest)
            return {"ok": False, "error": f"approve_failed:{type(exc).__name__}:{str(exc)[:180]}"}

    def execute_best_match(self, command: str) -> dict[str, Any]:
        task = self._match_task(command)
        if not task:
            return {"ok": False, "matched": False, "error": "no_task_match"}
        path = self.root / task["filename"]
        if not path.exists():
            return {"ok": False, "matched": True, "error": "task_file_missing", "task": task}
        result = self._run_task_file(path, command)
        if result["ok"]:
            return {"ok": True, "matched": True, "task": task, "reply": result["stdout"].strip(), "result": result}
        rollback = self._rollback_task(path, task)
        return {"ok": False, "matched": True, "task": task, "error": result.get("error"), "result": result, "rollback": rollback}

    def list_approved(self) -> list[dict[str, Any]]:
        manifest = self._load_manifest()
        return [
            task
            for task in manifest.get("tasks", {}).values()
            if isinstance(task, dict) and task.get("status") == "approved"
        ]

    def _generate_spec(self, command: str) -> TaskSpec:
        if "imc" in _normalize_text(command):
            return _imc_task_spec()
        system = (
            "Você gera tarefas Python locais e seguras para o Ultron UI. "
            "Responda somente JSON válido, sem markdown."
        )
        prompt = (
            "Crie uma tarefa Python para este pedido do usuário:\n"
            f"{command}\n\n"
            "Formato obrigatório:\n"
            '{"name":"...","filename":"nome_seguro.py","description":"...",'
            '"trigger_examples":["..."],"test_command":"...", "code":"..."}\n\n'
            "O code deve definir exatamente uma função run(command: str) -> str. "
            "Não use arquivos, rede, subprocess, eval, exec, input, os, sys, pathlib ou shutil. "
            "Prefira regex, math e lógica pura. A resposta da função deve ser texto curto em português."
        )
        raw = self.llm.complete(prompt, system=system, max_tokens=900, temperature=0.1)
        data = _extract_json_object(raw)
        if not data:
            raise RuntimeError("qwen_task_generation_empty_or_invalid")
        return TaskSpec.from_dict(data)

    def _sandbox_code(self, code: str, command: str) -> dict[str, Any]:
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        path = self.sandbox_dir / f"candidate_{int(time.time() * 1000)}.py"
        path.write_text(_wrap_task_code(code), encoding="utf-8")
        try:
            return _run_python_file(path, command, cwd=self.sandbox_dir, timeout_sec=5)
        finally:
            try:
                path.unlink()
            except Exception:
                pass

    def _run_task_file(self, path: Path, command: str) -> dict[str, Any]:
        temp_path = self.sandbox_dir / f"run_{path.stem}_{int(time.time() * 1000)}.py"
        temp_path.write_text(_wrap_task_code(path.read_text(encoding="utf-8")), encoding="utf-8")
        try:
            return _run_python_file(temp_path, command, cwd=self.sandbox_dir, timeout_sec=8)
        finally:
            try:
                temp_path.unlink()
            except Exception:
                pass

    def _match_task(self, command: str) -> dict[str, Any] | None:
        query = _normalize_text(command)
        scored: list[tuple[int, dict[str, Any]]] = []
        for task in self.list_approved():
            haystack = _normalize_text(
                " ".join(
                    [
                        str(task.get("name") or ""),
                        str(task.get("description") or ""),
                        " ".join(task.get("trigger_examples") or []),
                        str(task.get("filename") or ""),
                    ]
                )
            )
            score = sum(1 for token in set(query.split()) if len(token) > 2 and token in haystack)
            if task.get("filename") == "calcular_imc.py" and "imc" in query:
                score += 10
            if score > 0:
                scored.append((score, task))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def _rollback_task(self, path: Path, task: dict[str, Any]) -> dict[str, Any]:
        backup = Path(str(task.get("backup") or ""))
        if backup.exists():
            shutil.copy2(backup, path)
            return {"ok": True, "restored": str(backup)}
        manifest = self._load_manifest()
        filename = str(task.get("filename") or path.name)
        if filename in manifest.get("tasks", {}):
            manifest["tasks"][filename]["status"] = "disabled_after_error"
            self._save_manifest(manifest)
        return {"ok": False, "reason": "no_backup_available"}

    def _load_manifest(self) -> dict[str, Any]:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("tasks"), dict):
                return data
        except Exception:
            pass
        return {"version": 1, "tasks": {}}

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        manifest["version"] = 1
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_task_code(code: str) -> dict[str, Any]:
    src = str(code or "").strip()
    if not src:
        return {"ok": False, "error": "empty_code"}
    if len(src) > 12000:
        return {"ok": False, "error": "code_too_large"}
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return {"ok": False, "error": f"syntax_error:{exc}"}

    has_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            has_run = True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in _DANGEROUS_IMPORTS:
                    return {"ok": False, "error": f"blocked_import:{name}"}
                if name not in _ALLOWED_IMPORTS:
                    return {"ok": False, "error": f"unknown_import:{name}"}
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _DANGEROUS_CALLS:
                return {"ok": False, "error": f"blocked_call:{func.id}"}
            if isinstance(func, ast.Attribute) and str(func.attr).startswith("__"):
                return {"ok": False, "error": "blocked_dunder_attribute_call"}
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("__"):
            return {"ok": False, "error": "blocked_dunder_attribute"}
    if not has_run:
        return {"ok": False, "error": "missing_run_function"}
    return {"ok": True}


def _run_python_file(path: Path, command: str, *, cwd: Path, timeout_sec: int) -> dict[str, Any]:
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PATH": os.getenv("PATH", ""),
    }
    try:
        proc = subprocess.run(
            [sys.executable, str(path), str(command or "")],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_sec)),
            env=env,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip()[:2000],
            "error": "" if proc.returncode == 0 else f"returncode:{proc.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "", "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "returncode": -2, "stdout": "", "stderr": str(exc), "error": type(exc).__name__}


def _wrap_task_code(code: str) -> str:
    return (
        str(code or "").strip()
        + "\n\nif __name__ == '__main__':\n"
        + "    import sys\n"
        + "    result = run(' '.join(sys.argv[1:]))\n"
        + "    print(str(result))\n"
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    candidates = [raw]
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else None
        except Exception:
            continue
    return None


def _safe_filename(value: str) -> str:
    stem = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^a-zA-Z0-9_]+", "_", stem.lower()).strip("_") or "tarefa_local"
    if stem.endswith("_py"):
        stem = stem[:-3]
    if stem.endswith(".py"):
        stem = stem[:-3]
    return stem[:64] + ".py"


def _normalize_text(text: str) -> str:
    clean = unicodedata.normalize("NFKD", str(text or "").lower())
    clean = "".join(ch for ch in clean if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9À-ÿ]+", " ", clean).strip()


def _imc_task_spec() -> TaskSpec:
    code = '''import re


def run(command: str) -> str:
    text = str(command or "").lower().replace(",", ".")
    numbers = [float(item) for item in re.findall(r"\\d+(?:\\.\\d+)?", text)]
    if len(numbers) < 2:
        return "Informe peso e altura. Exemplo: peso 70, altura 1.75."
    peso = numbers[0]
    altura = numbers[1]
    if altura > 3:
        altura = altura / 100.0
    if peso <= 0 or altura <= 0:
        return "Peso e altura precisam ser maiores que zero."
    imc = peso / (altura * altura)
    if imc < 18.5:
        faixa = "abaixo do peso"
    elif imc < 25:
        faixa = "peso normal"
    elif imc < 30:
        faixa = "sobrepeso"
    else:
        faixa = "obesidade"
    return f"Seu IMC é {imc:.1f}, faixa: {faixa}."
'''
    return TaskSpec(
        name="calcular_imc",
        filename="calcular_imc.py",
        description="Calcula IMC a partir de peso e altura informados no comando.",
        trigger_examples=["calcula meu imc peso 70 altura 1.75", "imc 70 1.75"],
        test_command="Calcula meu IMC: peso 70, altura 1.75",
        code=code,
    )

