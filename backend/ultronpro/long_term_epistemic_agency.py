import time
import uuid
import json
from pathlib import Path
from collections import deque
from enum import Enum
from typing import Any, List, Dict

from ultronpro import store, local_world_models, learning_agenda

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
EPISTEMIC_PROJECTS_PATH = DATA_DIR / 'epistemic_projects.json'


class MilestoneType(Enum):
    DATA_HARVESTING = "data_harvesting"           # Ex: Juntar 50 episódios do domínio
    REDUCE_SURPRISE = "reduce_surprise"           # Ex: Acurácia causal > 80%
    CAUSAL_DISCOVERY = "causal_discovery"         # Ex: Descobrir ao menos 1 abstração matemática
    KOLMOGOROV_DISTILLATION = "kolmogorov"        # Ex: Comprimir as regras
    HUMAN_VALIDATION = "human_validation"         # Ex: Humano aceitar sem disputas

class EpistemicProjectManager:
    """
    Agência Epistêmica de Longo Prazo (Fase B Avançada).
    Formulação e Orquestração de projetos cognitivos cross-meses.
    O sistema projeta a aquisição de uma arquitetura causal, decompõe em marcos formais 
    (milestones) e amarra isso ao seu Sense of Identity (mission).
    """
    def __init__(self):
        self._load()

    def _load(self):
        if EPISTEMIC_PROJECTS_PATH.exists():
            try:
                self.data = json.loads(EPISTEMIC_PROJECTS_PATH.read_text(encoding='utf-8'))
            except Exception:
                self.data = {'projects': []}
        else:
            self.data = {'projects': []}

    def _save(self):
        EPISTEMIC_PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        EPISTEMIC_PROJECTS_PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')

    def propose_project(self, title: str, description: str, domain_target: str, ttl_days: int = 180) -> str:
        """Instancia a intenção autônoma macro de compreender uma faceta do mundo."""
        prj_id = f"epistemic_prj_{uuid.uuid4().hex[:8]}"
        project = {
            'id': prj_id,
            'title': title,
            'description': description,
            'target_domain': domain_target,
            'status': 'active', # active, replanning, achieved, aborted
            'created_at': int(time.time()),
            'deadline': int(time.time()) + (ttl_days * 86400),
            'milestones': [
                {
                    'id': 'm1_harvest',
                    'type': MilestoneType.DATA_HARVESTING.value,
                    'target_episodes': 100,
                    'status': 'pending'
                },
                {
                    'id': 'm2_predictability',
                    'type': MilestoneType.REDUCE_SURPRISE.value,
                    'target_surprise_below': 0.2,
                    'status': 'pending',
                    'depends_on': ['m1_harvest']
                },
                {
                    'id': 'm3_discovery',
                    'type': MilestoneType.CAUSAL_DISCOVERY.value,
                    'target_abstractions': 3,
                    'status': 'pending',
                    'depends_on': ['m2_predictability']
                },
                {
                    'id': 'm4_kolmogorov',
                    'type': MilestoneType.KOLMOGOROV_DISTILLATION.value,
                    'status': 'pending',
                    'depends_on': ['m3_discovery']
                }
            ],
            'causal_assumptions': [] # Crenças iniciais que podem quebrar e disparar replanning
        }
        
        self.data['projects'].append(project)
        self._save()
        
        # Amarração com a Identidade e Learning Agenda
        self._sync_with_identity(project)
        self._sync_with_agenda(project)
        
        return prj_id

    def _sync_with_identity(self, project: dict):
        """O grande projeto epistemico afeta quem o sistema é temporalmente."""
        try:
            from ultronpro import self_governance
            self_governance.add_persistent_goal(
                text=f"[DRIVE EPISTÊMICO LONGO PRAZO] {project['title']}: {project['description'][:100]}",
                priority=0.9,
                kind='epistemic_macro'
            )
        except Exception:
            pass

    def _sync_with_agenda(self, project: dict):
        """Injeta a semente para que o Autofeeder (curiosidade de curto prazo) estude este domínio."""
        try:
            domain = project['target_domain']
            current_agenda = learning_agenda.status()
            domains = current_agenda.get('domains', [])
            
            # Se não está, insere para ele ler Wikipedia e afins organicamente
            if not any(d.get('name') == domain for d in domains):
                domains.append({'name': domain, 'target_depth': 150, 'weight': 1.0})
                learning_agenda.config_patch({'domains': domains})
        except Exception:
            pass

    def tick_projects(self) -> dict:
        """
        Gatilho do relógio interno. Verifica milestones de todos projetos ativos.
        Lê a matriz causal (World Model).
        """
        report = {'completed_milestones': 0, 'replanned_projects': 0, 'new_abstractions': 0}
        
        from ultronpro.local_world_models import get_manager
        manager = get_manager()
        
        for prj in self.data['projects']:
            if prj['status'] != 'active': continue
            
            domain = prj['target_domain']
            model = manager.models.get(domain)
            if not model: continue
            
            # Avalia Milestones
            for m in prj['milestones']:
                if m['status'] == 'achieved': continue
                
                # Check Dependencies
                deps_ok = all(
                    any(p['id'] == dep and p['status'] == 'achieved' for p in prj['milestones'])
                    for dep in m.get('depends_on', [])
                )
                if not deps_ok: continue
                
                # Evaluation
                achieved = False
                if m['type'] == MilestoneType.DATA_HARVESTING.value:
                    if len(model.transitions) >= m.get('target_episodes', 0):
                        achieved = True
                        
                elif m['type'] == MilestoneType.REDUCE_SURPRISE.value:
                    from ultronpro.causal_maturity import evaluate_maturity
                    mat = evaluate_maturity(domain)
                    if mat and mat.get('is_mature') and mat.get('mean_surprise', 1.0) <= m.get('target_surprise_below', 0.2):
                         achieved = True
                         
                elif m['type'] == MilestoneType.CAUSAL_DISCOVERY.value:
                     from ultronpro.episodic_compiler import _load_abstractions
                     lib = _load_abstractions()
                     compiled = [a for a in lib.get('abstractions', []) if a.get('domain') == domain and a.get('status') == 'compiled_skill']
                     if len(compiled) >= m.get('target_abstractions', 1):
                         achieved = True
                         
                elif m['type'] == MilestoneType.KOLMOGOROV_DISTILLATION.value:
                      from ultronpro.episodic_compiler import _load_abstractions
                      lib = _load_abstractions()
                      distilled = [a for a in lib.get('abstractions', []) if a.get('domain') == domain and a.get('origin') == 'kolmogorov_compressor']
                      if len(distilled) > 0:
                          achieved = True

                if achieved:
                    m['status'] = 'achieved'
                    m['achieved_at'] = int(time.time())
                    report['completed_milestones'] += 1
                    store.db.add_event('macro_epistemic', f"🚀 Milestone atingido no projeto '{prj['title']}': {m['type']}")
                    
            # Detecção de Quebra de Causal Assumptions (Replanning Epistêmico)
            # Se a maturidade causal for atingida mas depois explodir massivamente por 3 dias, a fundação está errada.
            if any(m['status'] == 'achieved' and m['type'] == MilestoneType.REDUCE_SURPRISE.value for m in prj['milestones']):
                 recent_errors = sum(1 for t in list(model.transitions)[-20:] if t.get('surprise', 0) > 0.6)
                 if recent_errors >= 10:
                     prj['status'] = 'replanning'
                     prj['notes'] = "Falha paradigmática estrutural. O que achávamos ser o Invariante quebrou sob nova jurisdição dos dados. Necessário expandir features base."
                     report['replanned_projects'] += 1
                     store.db.add_event('macro_epistemic', f"⚠️ REPLANNING ATIVO no projeto '{prj['title']}': Quebra de predição em maturidade profunda.")
                     
            if all(m['status'] == 'achieved' for m in prj['milestones']):
                prj['status'] = 'achieved'
                store.db.add_event('macro_epistemic', f"🏁 PROJETO EPISTÊMICO CONCLUÍDO: '{prj['title']}'. O framework causal da AGI para o domínio {prj['target_domain']} foi finalizado.")

        if report['completed_milestones'] > 0 or report['replanned_projects'] > 0:
            self._save()
            store.publish_workspace(
                module='long_term_epistemic_agency',
                channel='epistemic.macro_progress',
                payload_json=json.dumps(report, ensure_ascii=False),
                salience=0.85,
                ttl_sec=7200
            )

        return report

engine = EpistemicProjectManager()
