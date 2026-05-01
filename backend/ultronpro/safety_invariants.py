"""
Safety Invariants Checker
=========================

Verifica propriedades comportamentais de um patch (AST level) antes da
aplicação dinâmica. Sintaxe válida e imports não garantem que o modelo não tenha
mutilado invariantes críticas (ex: rate limits, loops infinitos, persistência).
"""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger("uvicorn")

class InvariantViolation(Exception):
    pass

def check_behavioral_invariants(module_name: str, original_code: str, fixed_code: str) -> dict:
    """
    Compara duas árvores AST para garantir que restrições críticas não foram violadas.
    Retorna {'ok': True} ou {'ok': False, 'reason': ...}.
    """
    try:
        orig_tree = ast.parse(original_code)
        fixed_tree = ast.parse(fixed_code)
    except SyntaxError as e:
        return {'ok': False, 'reason': f"SyntaxError during invariant check: {e}"}

    try:
        _check_top_level_preservation(orig_tree, fixed_tree)
        _check_throttling_preservation(orig_tree, fixed_tree)
        _check_persistence_preservation(orig_tree, fixed_tree)
        _check_except_blocks(orig_tree, fixed_tree)
        return {'ok': True}
    except InvariantViolation as e:
        logger.warning(f"Safety Invariant Violation in {module_name}: {e}")
        return {'ok': False, 'reason': str(e)}
    except Exception as e:
        return {'ok': False, 'reason': f"Invariant checker crashed: {e}"}

def _get_top_level_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names

def _check_top_level_preservation(orig_tree: ast.AST, fixed_tree: ast.AST):
    """Garante que funções/classes exportadas não sumiram."""
    orig_names = _get_top_level_names(orig_tree)
    fixed_names = _get_top_level_names(fixed_tree)
    
    missing = orig_names - fixed_names
    if missing:
        raise InvariantViolation(f"O patch deletou estruturas top-level necessárias: {', '.join(missing)}")

def _get_call_names(tree: ast.AST) -> set[str]:
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    return calls

def _check_throttling_preservation(orig_tree: ast.AST, fixed_tree: ast.AST):
    """Se o código original possuía sleep/throttling, o patch não pode apagar completamente."""
    orig_calls = _get_call_names(orig_tree)
    fixed_calls = _get_call_names(fixed_tree)

    for sleep_func in ['sleep', 'rate_limit', 'cooldown']:
        if sleep_func in orig_calls and sleep_func not in fixed_calls:
            raise InvariantViolation(f"Risco catastrófico de loop infinito: a função '{sleep_func}' foi removida do código.")

def _check_persistence_preservation(orig_tree: ast.AST, fixed_tree: ast.AST):
    """Se o código original salvava estado, o fix não pode remover os métodos de salvar."""
    orig_calls = _get_call_names(orig_tree)
    fixed_calls = _get_call_names(fixed_tree)

    critical_saves = ['_save', 'commit', 'execute', 'add_event']
    for save_func in critical_saves:
        if save_func in orig_calls and save_func not in fixed_calls:
            raise InvariantViolation(f"Risco de amnésia permanente: a chamada de persistência '{save_func}' foi deletada.")

def _check_except_blocks(orig_tree: ast.AST, fixed_tree: ast.AST):
    """
    O patch não deve introduzir um bare `except:` que ignore exceptions silenciosamente
    com um simples `pass`, a menos que o original já fosse assim (mas mesmo o original não deveria).
    Verificamos se há aumento de `pass` desnudo.
    """
    def count_bare_pass(tree: ast.AST) -> int:
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # Node exception type is None => bare except (e.g., except:) or catching Exception
                is_broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in ['Exception', 'BaseException'])
                
                # Check body length
                if is_broad and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    count += 1
        return count

    orig_bare_passes = count_bare_pass(orig_tree)
    fixed_bare_passes = count_bare_pass(fixed_tree)

    if fixed_bare_passes > orig_bare_passes:
        raise InvariantViolation("O patch introduziu um 'except Exception: pass' silencioso. Erros devem ser ao menos printados/logados.")
