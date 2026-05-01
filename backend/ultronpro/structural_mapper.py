"""
Structural Mapper (Fase E)
===========================
Mapeia Estruturas Causais Reais desenvolvidas num Domínio A
para serem utilizadas no Domínio B, abstraindo e adaptando.
Compila "Skills" cross-domínio.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ultronpro import episodic_compiler, llm, store

DATA_PATH = Path(__file__).resolve().parent.parent / 'data' / 'structural_mappings_v2.jsonl'
CROSS_SKILLS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'cross_domain_skills.json'


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def load_cross_skills() -> dict[str, Any]:
    if CROSS_SKILLS_PATH.exists():
        try:
            return json.loads(CROSS_SKILLS_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'skills': []}


def save_cross_skills(data: dict[str, Any]):
    _ensure_parent(CROSS_SKILLS_PATH)
    CROSS_SKILLS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def evaluate_cross_domain_transfer(abs_id: str, target_domain: str) -> dict[str, Any] | None:
    """Usa o LLM para verificar se um invariante isolado tem equivalentes causais válidos no target_domain."""
    lib = episodic_compiler._load_abstractions()
    source_abs = next((a for a in lib.get('abstractions', []) if a.get('id') == abs_id), None)
    
    if not source_abs:
        return None
        
    prompt = f"""Temos um invariante causal (Abstração) garantido empiricamente no domínio: '{source_abs.get('domain')}'.
A Estrutura Causal: {source_abs.get('causal_structure')}
Condições de Aplicabilidade: {source_abs.get('applicability_conditions')}

Sua tarefa: Como Mapeador Estrutural, avalie se essa MESMA estrutura causal é válida e aplicável no domínio '{target_domain}'.
Responda APENAS com JSON:
{{
  "is_transferable": true/false,
  "confidence": 0.0-1.0,
  "mapped_causal_structure": "A estrutura traduzida para os termos e a física do novo domínio",
  "mapped_conditions": "As condições adaptadas"
}}"""

    res = llm.complete(prompt, strategy='cheap', json_mode=True)
    if not res:
        return None
        
    try:
        cleaned = res.strip()
        f_idx = cleaned.find('{')
        l_idx = cleaned.rfind('}')
        if f_idx != -1 and l_idx != -1:
            data = json.loads(cleaned[f_idx:l_idx+1])
            
            mapping = {
                'ts': _now(),
                'abstraction_id': abs_id,
                'source_domain': source_abs.get('domain'),
                'target_domain': target_domain,
                'is_transferable': data.get('is_transferable', False),
                'confidence': float(data.get('confidence', 0.0)),
                'mapped_causal_structure': data.get('mapped_causal_structure', ''),
                'mapped_conditions': data.get('mapped_conditions', ''),
            }
            
            _ensure_parent(DATA_PATH)
            with DATA_PATH.open('a', encoding='utf-8') as f:
                f.write(json.dumps(mapping, ensure_ascii=False) + '\n')
                
            return mapping
    except Exception:
        pass
        
    return None


def cross_domain_compilation_sweep():
    """Varre abstrações fortes em 'causal_abstractions_v2' e cria Skills universais se aplicarem a mais de 1 domínio."""
    lib = episodic_compiler._load_abstractions()
    skills_db = load_cross_skills()
    
    # Pega abstrações empirically proven (usadas múltiplas vezes com sucesso elevado)
    strong_abstractions = [a for a in lib.get('abstractions', []) if a.get('version', 1.0) >= 1.2 or (a.get('success_count', 0) >= 3)]
    
    # Domínios conhecidos para tentar transferência
    from ultronpro import causal_preflight
    all_domains = causal_preflight.VERIFIABLE_DOMAINS
    
    for a in strong_abstractions:
        abs_id = a.get('id')
        source_domain = a.get('domain')
        
        # Pula se já virou skill cross-domain
        if any(abs_id in sk.get('source_abstractions', []) for sk in skills_db['skills']):
            continue
            
        transfer_successes = []
        for d in all_domains:
            if d == source_domain:
                continue
            res = evaluate_cross_domain_transfer(abs_id, target_domain=d)
            if res and res.get('is_transferable') and res.get('confidence', 0) > 0.7:
                transfer_successes.append(res)
                
        # Se transcendeu para múltiplos domínios, compila como SKILL!
        if len(transfer_successes) >= 1: # Ao menos 1 domínio alvo adicional
            skill = {
                'id': f"skill_{_now()}_{uuid.uuid4().hex[:4]}",
                'name': f"Universal: {a.get('name')}",
                'core_causal_invariant': a.get('causal_structure'),
                'valid_domains': [source_domain] + [t['target_domain'] for t in transfer_successes],
                'source_abstractions': [abs_id],
                'created_at': _now()
            }
            skills_db['skills'].append(skill)
            
            # Publish to workspace
            store.publish_workspace(
                module='structural_mapper',
                channel='cognitive.skill_compiled',
                payload_json=json.dumps(skill, ensure_ascii=False),
                salience=0.9,
                ttl_sec=7200
            )

    save_cross_skills(skills_db)
    return skills_db

