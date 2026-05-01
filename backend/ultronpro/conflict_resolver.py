"""Resolução Automática de Conflitos via LLM.

Quando há conflitos de conhecimento (mesma tripla com objetos diferentes),
a LLM analisa as evidências e decide qual variante é mais provável.

Estratégias:
1. Análise de evidências internas (experiências, fontes, trust)
2. Consulta externa (Wikipedia, busca)
3. Raciocínio lógico (coerência com outras triplas)
4. Escalada para humano se incerteza alta
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from ultronpro import llm


@dataclass
class ResolutionResult:
    """Resultado de uma tentativa de resolução."""
    resolved: bool
    chosen_object: str | None = None
    confidence: float = 0.0
    reasoning: str = ""
    strategy: str = "llm_analysis"
    needs_human: bool = False
    error: str | None = None


# Threshold de confiança para resolução automática
AUTO_RESOLVE_THRESHOLD = 0.7
# Máximo de conflitos a resolver por ciclo
MAX_CONFLICTS_PER_CYCLE = 3
# Cooldown entre tentativas no mesmo conflito (horas)
# reduzido para permitir auto-correção contínua sem esperar clique humano
RETRY_COOLDOWN_HOURS = 1.0


def _build_analysis_prompt(conflict: dict, variants: list[dict], context: str = "") -> str:
    """Constrói prompt para análise de conflito."""
    subject = conflict.get("subject", "?")
    predicate = conflict.get("predicate", "?")
    
    variants_text = "\n".join([
        f"  - \"{v.get('object', '?')}\" (confiança: {v.get('confidence', 0):.2f}, trust_fonte: {v.get('source_trust', 0.5):.2f}, visto {v.get('seen_count', 0)}x)"
        for v in variants
    ])
    
    prompt = f"""Você é um árbitro de conhecimento. Analise este conflito e decida qual variante é mais provável.

CONFLITO:
Sujeito: {subject}
Predicado: {predicate}

VARIANTES:
{variants_text}

{f"CONTEXTO ADICIONAL: {context}" if context else ""}

INSTRUÇÕES:
1. Analise cada variante com base em:
   - Coerência lógica
   - Conhecimento geral
   - Confiança e frequência de observação
2. Escolha a variante mais provável
3. Se não houver informação suficiente para decidir, diga "INCERTO"

Responda em JSON:
{{
  "chosen": "<objeto escolhido ou INCERTO>",
  "confidence": <0.0 a 1.0>,
  "reasoning": "<explicação breve do raciocínio>"
}}"""
    
    return prompt


def _build_synthesis_prompt(conflict: dict, variants: list[dict]) -> str:
    """Constrói prompt para síntese (quando ambas as variantes podem ser parcialmente corretas)."""
    subject = conflict.get("subject", "?")
    predicate = conflict.get("predicate", "?")
    
    variants_text = "\n".join([
        f"  - \"{v.get('object', '?')}\""
        for v in variants
    ])
    
    prompt = f"""Analise se estas variantes conflitantes podem ser SINTETIZADAS em uma única resposta mais completa.

CONFLITO:
"{subject}" {predicate} ...

VARIANTES:
{variants_text}

INSTRUÇÕES:
- Se as variantes são mutuamente exclusivas (apenas uma pode ser verdade), responda "EXCLUSIVE"
- Se podem ser combinadas/sintetizadas, proponha uma síntese

Responda em JSON:
{{
  "can_synthesize": true/false,
  "synthesis": "<síntese proposta ou null>",
  "reasoning": "<explicação>"
}}"""
    
    return prompt


def _parse_llm_response(response: str) -> dict:
    """Tenta extrair JSON da resposta da LLM."""
    try:
        # Limpa markdown se presente
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        
        return json.loads(text)
    except Exception:
        return {}


def analyze_conflict(
    conflict: dict,
    variants: list[dict],
    related_triples: list[dict] | None = None,
    external_context: str | None = None,
) -> ResolutionResult:
    """Analisa um conflito e tenta resolvê-lo via LLM.
    
    Args:
        conflict: Dados do conflito (subject, predicate, etc.)
        variants: Lista de variantes com object, confidence, seen_count
        related_triples: Triplas relacionadas para contexto
        external_context: Contexto externo (busca, Wikipedia, etc.)
    
    Returns:
        ResolutionResult com a decisão
    """
    if not variants or len(variants) < 2:
        return ResolutionResult(resolved=False, error="Menos de 2 variantes")
    
    # Contexto de triplas relacionadas
    context_parts = []
    if related_triples:
        related_text = "; ".join([
            f"{t.get('subject')} {t.get('predicate')} {t.get('object')}"
            for t in related_triples[:5]
        ])
        context_parts.append(f"Triplas relacionadas: {related_text}")
    
    if external_context:
        context_parts.append(f"Fonte externa: {external_context[:500]}")
    
    context = " | ".join(context_parts)
    
    # 1. Análise principal
    prompt = _build_analysis_prompt(conflict, variants, context)
    
    try:
        response = llm.complete(
            prompt,
            system="Você é um árbitro de conhecimento imparcial. Responda apenas em JSON válido.",
            json_mode=True,
            cloud_fallback=True,
        )
        
        data = _parse_llm_response(response)
        if not data:
            # FALLBACK DETERMÍNÍSTICO: usar regra de confiança de fonte
            logger.warning("LLM unavailable for conflict resolution - using deterministic fallback")
            return _resolve_deterministically(conflict, variants, related_triples)

        chosen = data.get("chosen", "").strip()
        confidence = float(data.get("confidence", 0))
        reasoning = data.get("reasoning", "")
        
        # Se incerto, escalar para humano
        if chosen.upper() == "INCERTO" or confidence < AUTO_RESOLVE_THRESHOLD:
            return ResolutionResult(
                resolved=False,
                confidence=confidence,
                reasoning=reasoning,
                needs_human=True,
                strategy="llm_analysis_uncertain",
            )
        
        # Verifica se o chosen está nas variantes
        variant_objects = [v.get("object", "").strip().lower() for v in variants]
        if chosen.lower() not in variant_objects:
            # LLM pode ter proposto uma síntese
            return ResolutionResult(
                resolved=False,
                reasoning=f"LLM sugeriu '{chosen}' que não está nas variantes",
                needs_human=True,
                strategy="llm_synthesis_suggested",
            )

        # Encontra o objeto exato (case-sensitive)
        exact_chosen = None
        chosen_variant = None
        for v in variants:
            if v.get("object", "").strip().lower() == chosen.lower():
                exact_chosen = v.get("object", "").strip()
                chosen_variant = v
                break

        # Ajuste por coerência global e trust de fonte
        consistency = 0.5
        if related_triples:
            objl = (exact_chosen or "").lower()
            hits = 0
            for t in related_triples[:12]:
                txt = f"{t.get('subject','')} {t.get('predicate','')} {t.get('object','')}".lower()
                if objl and objl in txt:
                    hits += 1
            consistency = min(1.0, 0.4 + hits * 0.12)

        source_trust = float((chosen_variant or {}).get("source_trust") or 0.5)
        combined_conf = (0.55 * confidence) + (0.25 * source_trust) + (0.20 * consistency)

        return ResolutionResult(
            resolved=combined_conf >= AUTO_RESOLVE_THRESHOLD,
            chosen_object=exact_chosen,
            confidence=combined_conf,
            reasoning=f"{reasoning} | trust_fonte={source_trust:.2f} | coerência_global={consistency:.2f}",
            strategy="llm_analysis_weighted",
            needs_human=combined_conf < AUTO_RESOLVE_THRESHOLD,
        )
        
    except Exception as e:
        return ResolutionResult(
            resolved=False,
            error=f"Erro na análise LLM: {str(e)[:200]}",
            needs_human=True,
            strategy='llm_exception',
            reasoning='Falha de análise automática; requer revisão humana ou fallback.',
        )


def try_synthesis(conflict: dict, variants: list[dict]) -> ResolutionResult:
    """Tenta sintetizar variantes conflitantes em uma única resposta."""
    if len(variants) < 2:
        return ResolutionResult(resolved=False, error="Menos de 2 variantes")
    
    prompt = _build_synthesis_prompt(conflict, variants)
    
    try:
        response = llm.complete(
            prompt,
            system="Você é um sintetizador de conhecimento. Responda apenas em JSON válido.",
            json_mode=True,
        )
        
        data = _parse_llm_response(response)
        
        can_synthesize = data.get("can_synthesize", False)
        synthesis = data.get("synthesis", "").strip()
        reasoning = data.get("reasoning", "")
        
        if can_synthesize and synthesis:
            return ResolutionResult(
                resolved=True,
                chosen_object=synthesis,
                confidence=0.75,
                reasoning=f"Síntese: {reasoning}",
                strategy="llm_synthesis",
            )
        
        return ResolutionResult(
            resolved=False,
            reasoning=f"Variantes exclusivas: {reasoning}",
            strategy="synthesis_failed",
        )
        
    except Exception as e:
        return ResolutionResult(
            resolved=False,
            error=f"Erro na síntese: {str(e)[:200]}",
        )


class ConflictResolver:
    """Gerencia resolução automática de conflitos."""
    
    def __init__(self, store):
        self.store = store
        self._last_attempt: dict[int, float] = {}  # conflict_id -> timestamp
    
    def _can_attempt(self, conflict_id: int) -> bool:
        """Verifica se pode tentar resolver este conflito (cooldown)."""
        last = self._last_attempt.get(conflict_id, 0)
        elapsed_hours = (time.time() - last) / 3600
        return elapsed_hours >= RETRY_COOLDOWN_HOURS
    
    def _record_attempt(self, conflict_id: int):
        """Registra tentativa de resolução."""
        self._last_attempt[conflict_id] = time.time()
    
    def _get_related_triples(self, subject: str, limit: int = 10) -> list[dict]:
        """Busca triplas relacionadas ao sujeito do conflito."""
        return self.store.search_triples(subject, limit=limit)
    
    def resolve_pending(self, max_conflicts: int = MAX_CONFLICTS_PER_CYCLE, force: bool = False) -> list[dict]:
        """Tenta resolver conflitos pendentes.
        
        Returns:
            Lista de resultados de resolução
        """
        results = []
        conflicts = self.store.list_conflicts(status="open", limit=max_conflicts * 2)
        
        resolved_count = 0
        for c in conflicts:
            if resolved_count >= max_conflicts:
                break
            
            cid = int(c.get("id"))
            
            # Verifica cooldown (ou força tentativa)
            if (not force) and (not self._can_attempt(cid)):
                continue
            
            # Busca detalhes completos
            full = self.store.get_conflict(cid)
            if not full:
                continue
            
            variants = full.get("variants", [])
            if len(variants) < 2:
                continue
            
            self._record_attempt(cid)
            
            # Busca triplas relacionadas para contexto
            subject = full.get("subject", "")
            related = self._get_related_triples(subject)
            
            # Tenta análise primeiro
            result = analyze_conflict(full, variants, related_triples=related)
            
            # Se incerto, tenta síntese
            if not result.resolved and not result.needs_human:
                result = try_synthesis(full, variants)
            
            # Registra resultado
            result_info = {
                "conflict_id": cid,
                "subject": subject,
                "predicate": full.get("predicate"),
                "resolved": result.resolved,
                "chosen": result.chosen_object,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
                "strategy": result.strategy,
                "needs_human": result.needs_human,
                "error": result.error,
            }
            results.append(result_info)
            
            # Se resolveu, aplica
            if result.resolved and result.chosen_object:
                try:
                    self.store.resolve_conflict(
                        cid,
                        resolution=result.reasoning,
                        chosen_object=result.chosen_object,
                        decided_by=f"auto:{result.strategy}",
                        notes=f"Confiança: {result.confidence:.2f}",
                    )
                    resolved_count += 1
                    
                    # Registra evento
                    self.store.add_event(
                        "conflict_auto_resolved",
                        f"🤖 Conflito #{cid} resolvido: {subject} → {result.chosen_object} ({result.strategy})",
                    )
                except Exception as e:
                    result_info["error"] = f"Falha ao aplicar: {str(e)[:100]}"
            
            elif result.needs_human:
                # Registra que precisa de humano
                self.store.add_event(
                    "conflict_needs_human",
                    f"👤 Conflito #{cid} precisa de revisão humana: {result.reasoning[:100]}",
                )
        
        return results


def _resolve_deterministically(conflict: dict, variants: list[dict], 
                                related_triples: list[dict] = None) -> ResolutionResult:
    """
    Fallback determinístico para resolução de conflitos.
    
    Usa apenas código - não depende de LLM cloud.
    Aplica regras de confiança de fonte e coerência.
    """
    import logging
    logger = logging.getLogger("uvicorn")
    
    if not variants:
        return ResolutionResult(
            resolved=False,
            confidence=0.0,
            reasoning='Sem variantes para analisar (fallback determinístico)',
            strategy='deterministic_fallback',
            needs_human=True,
        )
    
    # Regra 1: Escolher variante com maior source_trust
    best_variant = max(variants, key=lambda v: float(v.get('source_trust', 0.5)))
    chosen_object = best_variant.get('object', '')
    source_trust = float(best_variant.get('source_trust', 0.5))
    
    # Regra 2: Verificar coerência com triplas relacionadas
    coherence_bonus = 0.0
    if related_triples:
        obj_lower = chosen_object.lower()
        for t in related_triples[:5]:
            txt = f"{t.get('subject', '')} {t.get('predicate', '')} {t.get('object', '')}".lower()
            if obj_lower in txt:
                coherence_bonus += 0.1
    
    # Calcular confiança final
    confidence = min(0.7, source_trust + coherence_bonus)
    
    # Se confiança muito baixa, marcar para revisão humana
    if confidence < 0.4:
        return ResolutionResult(
            resolved=False,
            confidence=confidence,
            reasoning=f'Fallback determinístico: confiança baixa ({confidence:.2f}). Necessária revisão humana.',
            strategy='deterministic_low_confidence',
            needs_human=True,
        )
    
    logger.info(f"Conflict resolved deterministically: {best_variant.get('subject', '?')} -> {chosen_object} (trust={source_trust:.2f})")
    
    return ResolutionResult(
        resolved=True,
        chosen_object=chosen_object,
        confidence=confidence,
        reasoning=f'Fallback determinístico: escolhido por source_trust={source_trust:.2f}, coerência={coherence_bonus:.2f}',
        strategy='deterministic_fallback',
        needs_human=False,
    )
