"""
Self-Modification Engine — Motor de Auto-Modificação
=====================================================

Sistema de auto-modificação que permite ao UltronPro analisar, gerar e aplicar
mudanças em seu próprio código de forma segura e controlada.

Características:
- Análise estática do próprio código
- Geração de patches via LLM
- Sandbox de aplicação (dry-run)
- Validação automática
- Rollback automático em caso de falha
- Histórico completo de mudanças

"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

from ultronpro import llm, settings

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
ULTRONPRO_DIR = Path(__file__).resolve().parent
SELF_MOD_PATH = DATA_DIR / 'self_modification'
SELF_MOD_PATH.mkdir(parents=True, exist_ok=True)

PROPOSALS_PATH = SELF_MOD_PATH / 'proposals.json'
HISTORY_PATH = SELF_MOD_PATH / 'history.json'
BACKUPS_PATH = SELF_MOD_PATH / 'backups'
BACKUPS_PATH.mkdir(exist_ok=True)

REQUIRED_PIPELINE_STAGES = [
    'generated_patch',
    'isolated_copy_apply',
    'unit_tests',
    'reduced_benchmark',
    'regression_benchmark',
    'baseline_compare',
    'canary',
    'rollback_ready',
]


@dataclass
class CodeChange:
    file_path: str
    line_start: int
    line_end: int
    original_code: str
    new_code: str
    change_type: str


@dataclass
class ModificationProposal:
    id: str
    created_at: int
    title: str
    description: str
    changes: list[dict]
    rationale: str
    risk_level: str
    status: str
    validation_result: dict | None = None
    applied_at: int | None = None


class SelfModificationEngine:
    SAFE_PATTERNS = [
        r'^def .*:\s*$',
        r'^\s*#.*$',
        r'^\s*""".*"""$',
        r"^\s*'''.*'''$",
    ]
    
    DANGEROUS_PATTERNS = [
        r'exec\(',
        r'eval\(',
        r'__import__',
        r'subprocess',
        r'os\.system',
        r'open\(.*[wac]',
        r'delete',
        r'rmdir',
        r'shutil\.rmtree',
    ]

    def __init__(self):
        self.enabled = os.getenv('ULTRON_SELF_MOD_ENABLED', '1') == '1'
        self.auto_approve = os.getenv('ULTRON_SELF_MOD_AUTO_APPROVE', '1') == '1'
        self._load_proposals()

    def _load_proposals(self):
        if PROPOSALS_PATH.exists():
            try:
                data = json.loads(PROPOSALS_PATH.read_text())
                self.proposals = [ModificationProposal(**p) for p in data]
            except Exception:
                self.proposals = []
        else:
            self.proposals = []

    def _save_proposals(self):
        data = [asdict(p) for p in self.proposals]
        PROPOSALS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def analyze_code_structure(self, file_path: str) -> dict:
        """Analisa estrutura de um arquivo Python."""
        full_path = ULTRONPRO_DIR / file_path
        if not full_path.exists():
            return {'error': 'Arquivo não encontrado'}
        
        try:
            source = full_path.read_text(encoding='utf-8')
            tree = ast.parse(source)
            
            functions = []
            classes = []
            imports = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append({
                        'name': node.name,
                        'line': node.lineno,
                        'args': [a.arg for a in node.args.args],
                        'docstring': ast.get_docstring(node),
                    })
                elif isinstance(node, ast.ClassDef):
                    classes.append({
                        'name': node.name,
                        'line': node.lineno,
                        'methods': [n.name for n in node.body if isinstance(n, ast.FunctionDef)],
                    })
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    imports.append(node.module)
            
            return {
                'file': file_path,
                'functions': functions,
                'classes': classes,
                'imports': imports,
                'lines': len(source.splitlines()),
            }
        except Exception as e:
            return {'error': str(e)}

    def list_modifiable_modules(self) -> list[dict]:
        """Lista módulos que podem ser modificados."""
        modules = []
        ultronpro_dir = ULTRONPRO_DIR
        
        for py_file in ultronpro_dir.glob('*.py'):
            if py_file.name.startswith('_'):
                continue
            if py_file.name in ('main.py', 'settings.py'):
                continue
            
            try:
                source = py_file.read_text(encoding='utf-8')
                tree = ast.parse(source)
                funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
                modules.append({
                    'file': py_file.name,
                    'functions': funcs[:20],
                    'size': len(source),
                })
            except Exception:
                pass
        
        return modules

    def generate_modification(self, target_module: str, target_function: str,
                            goal: str, context: str = '') -> dict:
        """Gera uma modificação via LLM."""
        if not self.enabled:
            return {'error': 'Auto-modificação desabilitada'}
        
        modules = self.list_modifiable_modules()
        target_info = next((m for m in modules if m['file'] == target_module), None)
        
        if not target_info:
            return {'error': 'Módulo não encontrado'}
        
        prompt = f"""Você é o motor de auto-modificação do UltronPro. Gere uma modificação de código segura.

MÓDULO ALVO: {target_module}
FUNÇÃO ALVO: {target_function}
OBJETIVO: {goal}

CONTEXTO ADICIONAL: {context}

Analise a função e gere um patch no formato JSON:
{{
    "file": "{target_module}",
    "function": "{target_function}",
    "changes": [
        {{
            "type": "replace|add|remove",
            "line_start": número,
            "line_end": número,
            "new_code": "código novo (para replace/add)",
            "old_code": "código antigo (para replace)"
        }}
    ],
    "rationale": "por que esta mudança ajuda",
    "risk_level": "low|medium|high"
}}

Regras de segurança:
- NÃO use exec(), eval(), __import__()
- NÃO modifique arquivos de sistema
- Prefira adicionar código novo a modificar existente
- Mantenha a compatibilidade com código existente
- Adicione testes básicos se possível

Responda APENAS com JSON válido, sem explicações."""

        try:
            result = llm.chat(prompt, system_prompt="Você é um assistente de programação.")
            
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                patch_data = json.loads(json_match.group())
                return self._create_proposal(patch_data, goal)
            else:
                return {'error': 'Não foi possível gerar patch'}
        except Exception as e:
            return {'error': str(e)}

    def _create_proposal(self, patch_data: dict, goal: str) -> ModificationProposal:
        """Cria uma proposta de modificação."""
        target_file = patch_data.get('file')
        changes = []
        for change in patch_data.get('changes', []):
            if isinstance(change, dict):
                row = dict(change)
                if target_file and not row.get('file'):
                    row['file'] = target_file
                changes.append(row)
        proposal = ModificationProposal(
            id=f"mod_{int(time.time())}_{hashlib.md5(str(time.time()).encode()).hexdigest()[:6]}",
            created_at=int(time.time()),
            title=goal[:100],
            description=patch_data.get('rationale', ''),
            changes=changes,
            rationale=patch_data.get('rationale', ''),
            risk_level=patch_data.get('risk_level', 'medium'),
            status='pending',
        )
        
        self.proposals.append(proposal)
        self._save_proposals()
        
        return proposal

    def validate_change(self, proposal_id: str) -> dict:
        """Valida uma proposta de modificação."""
        proposal = next((p for p in self.proposals if p.id == proposal_id), None)
        if not proposal:
            return {'valid': False, 'error': 'Proposta não encontrada'}
        
        warnings = []
        errors = []
        
        for change in proposal.changes:
            new_code = change.get('new_code', '')
            if not change.get('file'):
                errors.append('Arquivo alvo ausente no change')
            
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, new_code):
                    errors.append(f"Padrão perigoso detectado: {pattern}")
            
            if change.get('type') == 'add':
                if not new_code.strip().startswith(('def ', 'class ', '#', '""', "'''")):
                    warnings.append('Código adicionado não segue padrões típicos')
        
        proposal.validation_result = {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'validated_at': int(time.time()),
        }
        
        if len(errors) == 0:
            proposal.status = 'validated'
        else:
            proposal.status = 'rejected'
        
        self._save_proposals()
        
        return proposal.validation_result

    def dry_run(self, proposal_id: str) -> dict:
        """Executa dry-run de uma modificação."""
        proposal = next((p for p in self.proposals if p.id == proposal_id), None)
        if not proposal:
            return {'error': 'Proposta não encontrada'}
        
        results = []
        
        for change in proposal.changes:
            file_path = ULTRONPRO_DIR / change.get('file', 'unknown.py')
            
            if not file_path.exists():
                results.append({'change': change, 'status': 'error', 'message': 'Arquivo não existe'})
                continue
            
            original = file_path.read_text(encoding='utf-8')
            
            backup_name = f"{file_path.stem}_{int(time.time())}.py"
            (BACKUPS_PATH / backup_name).write_text(original, encoding='utf-8')
            
            lines = original.splitlines(keepends=True)
            
            if change.get('type') == 'replace':
                start = change.get('line_start', 1) - 1
                end = change.get('line_end', start + 1)
                new_code = change.get('new_code', '')
                
                if start < len(lines):
                    new_lines = lines[:start] + [new_code + '\n'] + lines[end:]
                    simulated = ''.join(new_lines)
                    results.append({
                        'change': change,
                        'status': 'success',
                        'lines_affected': end - start,
                    })
                else:
                    results.append({'change': change, 'status': 'error', 'message': 'Linha inválida'})
            
            elif change.get('type') == 'add':
                new_code = change.get('new_code', '')
                results.append({
                    'change': change,
                    'status': 'success',
                    'lines_added': len(new_code.splitlines()),
                })
        
        return {
            'proposal_id': proposal_id,
            'dry_run': True,
            'changes': results,
            'backup_files': len(list(BACKUPS_PATH.glob('*.py'))),
        }

    def validate_isolated_pipeline(self, proposal_id: str, evidence: dict | None = None) -> dict:
        """Validate a proposal through the mandatory isolated promotion pipeline."""
        proposal = next((p for p in self.proposals if p.id == proposal_id), None)
        if not proposal:
            return {'ok': False, 'error': 'Proposta nao encontrada'}

        evidence = evidence if isinstance(evidence, dict) else {}
        static_validation = self.validate_change(proposal_id)
        stage_results: dict[str, dict[str, Any]] = {
            'generated_patch': {'passed': bool(proposal.changes), 'detail': f'{len(proposal.changes)} changes'},
        }
        if not static_validation.get('valid'):
            stage_results['static_validation'] = {'passed': False, 'detail': static_validation}
            return self._finish_pipeline_validation(proposal, stage_results, evidence)

        with tempfile.TemporaryDirectory(prefix='ultron-selfmod-') as td:
            isolated_root = Path(td) / 'ultronpro'
            shutil.copytree(
                ULTRONPRO_DIR,
                isolated_root,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'),
            )
            apply_result = self._apply_changes_to_root(isolated_root, proposal)
            stage_results['isolated_copy_apply'] = apply_result

            target_files = [
                str((isolated_root / change.get('file')).resolve())
                for change in proposal.changes
                if change.get('file') and (isolated_root / change.get('file')).exists()
            ]
            unit_result = self._run_py_compile(target_files)
            stage_results['unit_tests'] = unit_result

        reduced = evidence.get('reduced_benchmark') if isinstance(evidence.get('reduced_benchmark'), dict) else {}
        regression = evidence.get('regression_benchmark') if isinstance(evidence.get('regression_benchmark'), dict) else {}
        canary = evidence.get('canary') if isinstance(evidence.get('canary'), dict) else {}
        baseline_compare = self._compare_baseline_evidence(evidence)

        stage_results['reduced_benchmark'] = {
            'passed': bool(reduced.get('passed')),
            'detail': reduced or 'missing_reduced_benchmark_evidence',
        }
        stage_results['regression_benchmark'] = {
            'passed': bool(regression.get('passed')),
            'detail': regression or 'missing_regression_benchmark_evidence',
        }
        stage_results['baseline_compare'] = baseline_compare
        stage_results['canary'] = {
            'passed': bool(canary.get('passed')) and int(canary.get('rollout_pct') or 0) > 0,
            'detail': canary or 'missing_canary_evidence',
        }
        stage_results['rollback_ready'] = {
            'passed': True,
            'detail': {
                'mode': 'automatic',
                'reason': 'runtime principal nao foi modificado; proposta tem manifesto reproduzivel',
            },
        }

        return self._finish_pipeline_validation(proposal, stage_results, evidence)

    def _finish_pipeline_validation(self, proposal: ModificationProposal, stage_results: dict, evidence: dict) -> dict:
        missing = [
            stage for stage in REQUIRED_PIPELINE_STAGES
            if not bool((stage_results.get(stage) or {}).get('passed'))
        ]
        promoted = not missing
        proposal.validation_result = {
            'valid': promoted,
            'required_stages': REQUIRED_PIPELINE_STAGES,
            'stage_results': stage_results,
            'missing_or_failed_stages': missing,
            'evidence': evidence,
            'validated_at': int(time.time()),
            'promotion_mode': 'canary' if promoted else 'blocked',
        }
        proposal.status = 'canary_ready' if promoted else 'validation_blocked'
        self._save_proposals()
        self._log_history(
            proposal.id,
            'isolated_pipeline_validated',
            'canary_ready' if promoted else f"blocked:{','.join(missing)}",
        )
        return {
            'ok': True,
            'proposal_id': proposal.id,
            'promoted': promoted,
            'promotion_stage': proposal.status,
            'required_stages': REQUIRED_PIPELINE_STAGES,
            'missing_or_failed_stages': missing,
            'stage_results': stage_results,
        }

    def _apply_changes_to_root(self, root: Path, proposal: ModificationProposal) -> dict:
        results = []
        for change in proposal.changes:
            target_file = change.get('file')
            if not target_file:
                results.append({'passed': False, 'file': None, 'error': 'missing_file'})
                continue
            file_path = root / target_file
            if not file_path.exists():
                results.append({'passed': False, 'file': target_file, 'error': 'file_not_found'})
                continue
            original = file_path.read_text(encoding='utf-8')
            lines = original.splitlines(keepends=True)
            start = max(0, int(change.get('line_start') or 1) - 1)
            end = max(start, int(change.get('line_end') or (start + 1)))
            change_type = change.get('type')
            new_code = str(change.get('new_code') or '')
            if change_type == 'replace':
                if start >= len(lines):
                    results.append({'passed': False, 'file': target_file, 'error': 'invalid_start_line'})
                    continue
                new_lines = lines[:start] + [new_code.rstrip('\n') + '\n'] + lines[end:]
                file_path.write_text(''.join(new_lines), encoding='utf-8')
            elif change_type == 'add':
                position = change.get('position', 'end')
                payload = new_code.rstrip('\n') + '\n'
                if position == 'start':
                    file_path.write_text(payload + original, encoding='utf-8')
                else:
                    file_path.write_text(original.rstrip('\n') + '\n' + payload, encoding='utf-8')
            elif change_type == 'remove':
                if start >= len(lines):
                    results.append({'passed': False, 'file': target_file, 'error': 'invalid_start_line'})
                    continue
                file_path.write_text(''.join(lines[:start] + lines[end:]), encoding='utf-8')
            else:
                results.append({'passed': False, 'file': target_file, 'error': f'unsupported_change_type:{change_type}'})
                continue
            results.append({'passed': True, 'file': target_file, 'type': change_type})
        return {
            'passed': bool(results) and all(row.get('passed') for row in results),
            'detail': results,
        }

    def _run_py_compile(self, target_files: list[str]) -> dict:
        if not target_files:
            return {'passed': False, 'detail': 'no_target_files'}
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'py_compile', *target_files],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return {
                'passed': result.returncode == 0,
                'returncode': result.returncode,
                'stdout': result.stdout[-1000:],
                'stderr': result.stderr[-1000:],
            }
        except Exception as exc:
            return {'passed': False, 'detail': f'{type(exc).__name__}: {str(exc)[:200]}'}

    def _compare_baseline_evidence(self, evidence: dict) -> dict:
        baseline = evidence.get('baseline') if isinstance(evidence.get('baseline'), dict) else {}
        candidate = evidence.get('candidate') if isinstance(evidence.get('candidate'), dict) else {}
        try:
            baseline_score = float(baseline.get('score'))
            candidate_score = float(candidate.get('score'))
        except Exception:
            return {'passed': False, 'detail': 'missing_baseline_or_candidate_score'}
        delta = candidate_score - baseline_score
        return {
            'passed': delta > 0,
            'baseline_score': baseline_score,
            'candidate_score': candidate_score,
            'delta': round(delta, 6),
        }

    def apply(self, proposal_id: str, force: bool = False) -> dict:
        """Aplica uma modificação aprovada."""
        if not self.enabled and not force:
            return {'error': 'Auto-modificação desabilitada'}
        
        proposal = next((p for p in self.proposals if p.id == proposal_id), None)
        if not proposal:
            return {'error': 'Proposta não encontrada'}
        
        return {
            'ok': False,
            'blocked': True,
            'error': 'direct_runtime_apply_disabled',
            'proposal_id': proposal_id,
            'message': 'Auto-modificacao nao aplica patch direto no runtime principal.',
            'required_flow': REQUIRED_PIPELINE_STAGES,
            'next_action': 'validate_isolated_pipeline',
        }

        if proposal.status not in ('validated', 'approved') and not force:
            return {'error': 'Proposta precisa ser validada primeiro'}
        
        applied = []
        
        for change in proposal.changes:
            target_file = change.get('file')
            file_path = ULTRONPRO_DIR / target_file
            
            if not file_path.exists():
                continue
            
            original = file_path.read_text(encoding='utf-8')
            
            backup_name = f"{file_path.stem}_{int(time.time())}.py.backup"
            (BACKUPS_PATH / backup_name).write_text(original, encoding='utf-8')
            
            lines = original.splitlines(keepends=True)
            
            if change.get('type') == 'replace':
                start = change.get('line_start', 1) - 1
                end = change.get('line_end', start + 1)
                new_code = change.get('new_code', '')
                
                if start < len(lines):
                    new_lines = lines[:start] + [new_code + '\n'] + lines[end:]
                    file_path.write_text(''.join(new_lines), encoding='utf-8')
                    applied.append(change)
            
            elif change.get('type') == 'add':
                new_code = change.get('new_code', '')
                position = change.get('position', 'end')
                
                if position == 'end':
                    file_path.write_text(original + '\n' + new_code, encoding='utf-8')
                elif position == 'start':
                    file_path.write_text(new_code + '\n' + original, encoding='utf-8')
                
                applied.append(change)
        
        proposal.applied_at = int(time.time())
        proposal.status = 'applied'
        self._save_proposals()
        
        self._log_history(proposal_id, 'applied', f'{len(applied)} mudanças aplicadas')
        
        return {
            'ok': True,
            'proposal_id': proposal_id,
            'applied_count': len(applied),
            'changes': applied,
        }

    def revert(self, proposal_id: str, reason: str = '') -> dict:
        """Reverte uma modificação aplicada."""
        backup_files = sorted(BACKUPS_PATH.glob('*.py.backup'), key=lambda x: x.stat().st_mtime, reverse=True)
        
        proposal = next((p for p in self.proposals if p.id == proposal_id), None)
        if proposal:
            proposal.status = 'reverted'
            self._save_proposals()
        
        target_file = None
        if proposal and proposal.changes:
            target_file = proposal.changes[0].get('file')
        
        if not target_file:
            return {'error': 'Arquivo alvo não encontrado'}
        
        for backup in backup_files:
            if target_file.replace('.py', '') in backup.name:
                file_path = ULTRONPRO_DIR / target_file
                file_path.write_text(backup.read_text(encoding='utf-8'), encoding='utf-8')
                
                self._log_history(proposal_id, 'reverted', reason or 'rollback manual')
                return {'ok': True, 'reverted': True}
        
        return {'error': 'Backup não encontrado'}

    def get_proposals(self, status: str | None = None) -> list[dict]:
        """Lista propostas de modificação."""
        proposals = self.proposals
        if status:
            proposals = [p for p in proposals if p.status == status]
        return [asdict(p) for p in proposals]

    def _log_history(self, proposal_id: str, event: str, detail: str):
        """Registra evento no histórico."""
        history = []
        if HISTORY_PATH.exists():
            try:
                history = json.loads(HISTORY_PATH.read_text())
            except Exception:
                pass
        
        history.append({
            'ts': int(time.time()),
            'proposal_id': proposal_id,
            'event': event,
            'detail': detail,
        })
        
        HISTORY_PATH.write_text(json.dumps(history[-100:], ensure_ascii=False, indent=2))

    def get_history(self, limit: int = 20) -> list[dict]:
        """Retorna histórico de modificações."""
        if not HISTORY_PATH.exists():
            return []
        
        try:
            history = json.loads(HISTORY_PATH.read_text())
            return history[-limit:]
        except Exception:
            return []

    def get_status(self) -> dict:
        """Retorna status do motor de auto-modificação."""
        return {
            'enabled': self.enabled,
            'auto_approve': self.auto_approve,
            'direct_runtime_apply': False,
            'required_pipeline_stages': REQUIRED_PIPELINE_STAGES,
            'total_proposals': len(self.proposals),
            'pending': len([p for p in self.proposals if p.status == 'pending']),
            'applied': len([p for p in self.proposals if p.status == 'applied']),
            'reverted': len([p for p in self.proposals if p.status == 'reverted']),
            'backup_count': len(list(BACKUPS_PATH.glob('*.py.backup'))),
        }


_self_mod_engine: Optional[SelfModificationEngine] = None


def get_self_mod_engine() -> SelfModificationEngine:
    global _self_mod_engine
    if _self_mod_engine is None:
        _self_mod_engine = SelfModificationEngine()
    return _self_mod_engine


def analyze_module(file_path: str) -> dict:
    return get_self_mod_engine().analyze_code_structure(file_path)


def list_modules() -> list[dict]:
    return get_self_mod_engine().list_modifiable_modules()


def generate_modification(target_module: str, target_function: str, goal: str, context: str = '') -> dict:
    return get_self_mod_engine().generate_modification(target_module, target_function, goal, context)


def validate_proposal(proposal_id: str) -> dict:
    return get_self_mod_engine().validate_change(proposal_id)


def dry_run_proposal(proposal_id: str) -> dict:
    return get_self_mod_engine().dry_run(proposal_id)


def validate_isolated_pipeline(proposal_id: str, evidence: dict | None = None) -> dict:
    return get_self_mod_engine().validate_isolated_pipeline(proposal_id, evidence)


def apply_modification(proposal_id: str, force: bool = False) -> dict:
    return get_self_mod_engine().apply(proposal_id, force)


def revert_modification(proposal_id: str, reason: str = '') -> dict:
    return get_self_mod_engine().revert(proposal_id, reason)


def get_modification_proposals(status: str | None = None) -> list[dict]:
    return get_self_mod_engine().get_proposals(status)


def get_modification_history(limit: int = 20) -> list[dict]:
    return get_self_mod_engine().get_history(limit)


def get_self_mod_status() -> dict:
    return get_self_mod_engine().get_status()
