import time
import uuid
import json
from collections import defaultdict
from typing import Any

from ultronpro import episodic_compiler, local_world_models, store
from ultronpro.structural_abstractor import _flatten_dict


def _premise_feature(premise: Any) -> str:
    if isinstance(premise, dict):
        return str(premise.get('feature') or premise.get('key') or premise.get('variable') or '').strip()
    return str(premise or '').strip()


def _premise_matches(flat_state: dict[str, Any], premise: Any) -> bool:
    feature = _premise_feature(premise)
    if not feature:
        return False
    got = flat_state.get(feature)
    if not isinstance(premise, dict):
        return bool(got)

    expected_marker = object()
    expected = premise.get('equals', premise.get('value', premise.get('is', expected_marker)))
    if expected is expected_marker:
        return bool(got)

    op = str(premise.get('op') or 'eq').lower()
    if op in ('eq', '=', '=='):
        return got == expected or str(got).lower() == str(expected).lower()
    if op in ('ne', '!='):
        return got != expected and str(got).lower() != str(expected).lower()
    try:
        if op in ('gt', '>'):
            return float(got) > float(expected)
        if op in ('gte', '>='):
            return float(got) >= float(expected)
        if op in ('lt', '<'):
            return float(got) < float(expected)
        if op in ('lte', '<='):
            return float(got) <= float(expected)
    except Exception:
        return False
    return got == expected


def predictive_power_for_premises(
    transitions: list[dict[str, Any]],
    premises: list[Any],
    *,
    min_support: int = 2,
) -> dict[str, Any]:
    matched: list[str] = []
    for row in transitions:
        flat = _flatten_dict(row.get('state_t', {}) if isinstance(row, dict) else {})
        if all(_premise_matches(flat, premise) for premise in premises):
            matched.append(str(row.get('actual_outcome') or row.get('outcome') or 'unknown'))

    counts: dict[str, int] = {}
    for outcome in matched:
        counts[outcome] = counts.get(outcome, 0) + 1
    if len(matched) < max(1, int(min_support or 1)) or not counts:
        return {
            'support': len(matched),
            'score': 0.0,
            'purity': 0.0,
            'majority_outcome': None,
            'outcomes': counts,
        }
    majority, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    purity = float(n) / max(1, len(matched))
    return {
        'support': len(matched),
        'score': round(purity, 4),
        'purity': round(purity, 4),
        'majority_outcome': majority,
        'outcomes': counts,
    }


def compress_premises(
    premises: list[Any],
    transitions: list[dict[str, Any]],
    *,
    tolerance: float = 0.02,
    min_support: int = 2,
) -> dict[str, Any]:
    """Remove premises that do not change empirical predictive power."""
    original = [p for p in (premises or []) if _premise_feature(p)]
    current = list(original)
    current_metrics = predictive_power_for_premises(transitions, current, min_support=min_support)
    dropped: list[dict[str, Any]] = []

    changed = True
    while changed and len(current) > 1:
        changed = False
        best = None
        for idx, premise in enumerate(current):
            candidate = current[:idx] + current[idx + 1:]
            metrics = predictive_power_for_premises(transitions, candidate, min_support=min_support)
            retained = float(metrics.get('score') or 0.0) >= (float(current_metrics.get('score') or 0.0) - float(tolerance or 0.0))
            support_ok = int(metrics.get('support') or 0) >= int(current_metrics.get('support') or 0)
            if retained and support_ok:
                rank = (float(metrics.get('score') or 0.0), int(metrics.get('support') or 0))
                if best is None or rank > best['rank']:
                    best = {'idx': idx, 'premise': premise, 'metrics': metrics, 'rank': rank}
        if best is not None:
            dropped.append({
                'premise': best['premise'],
                'feature': _premise_feature(best['premise']),
                'power_after_drop': best['metrics'],
            })
            current = current[:best['idx']] + current[best['idx'] + 1:]
            current_metrics = best['metrics']
            changed = True

    original_metrics = predictive_power_for_premises(transitions, original, min_support=min_support)
    gain = 1.0 - (len(current) / max(1, len(original)))
    return {
        'ok': True,
        'original_premises': original,
        'retained_premises': current,
        'dropped_premises': dropped,
        'original_power': original_metrics,
        'compressed_power': current_metrics,
        'compression_gain': round(gain, 4),
        'spurious_features': [d['feature'] for d in dropped],
        'passed': bool(dropped and float(current_metrics.get('score') or 0.0) >= float(original_metrics.get('score') or 0.0) - float(tolerance or 0.0)),
    }


def compress_rule(rule: dict[str, Any], transitions: list[dict[str, Any]], *, tolerance: float = 0.02, min_support: int = 2) -> dict[str, Any]:
    premises = rule.get('premises') if isinstance(rule.get('premises'), list) else []
    out = compress_premises(premises, transitions, tolerance=tolerance, min_support=min_support)
    out['rule_id'] = rule.get('id')
    out['rule_name'] = rule.get('name')
    return out


def run_spurious_causality_benchmark() -> dict[str, Any]:
    """Synthetic benchmark: only switch_on is causal; visual features are mirages."""
    transitions: list[dict[str, Any]] = []
    for repeat in range(3):
        for switch_on in (True, False):
            for background_color in ('red', 'blue'):
                for object_shape in ('circle', 'square'):
                    transitions.append({
                        'state_t': {
                            'switch_on': switch_on,
                            'background_color': background_color,
                            'object_shape': object_shape,
                            'trial_repeat': repeat,
                        },
                        'actual_outcome': 'success' if switch_on else 'failure',
                    })

    rule = {
        'id': 'spurious_visual_rule_v1',
        'name': 'Pseudo-causal visual rule',
        'premises': [
            {'feature': 'switch_on', 'equals': True},
            {'feature': 'background_color', 'equals': 'red'},
            {'feature': 'object_shape', 'equals': 'circle'},
        ],
    }
    compressed = compress_rule(rule, transitions, tolerance=0.0, min_support=2)
    retained = {_premise_feature(p) for p in compressed.get('retained_premises') or []}
    dropped = set(compressed.get('spurious_features') or [])
    passed = retained == {'switch_on'} and {'background_color', 'object_shape'} <= dropped
    return {
        'ok': True,
        'benchmark': 'spurious_visual_pseudocausality_v1',
        'total_cases': len(transitions),
        'rule': rule,
        'compressed': compressed,
        'passed': passed,
        'expected_retained': ['switch_on'],
        'expected_spurious': ['background_color', 'object_shape'],
    }


class CausalKolmogorovCompressor:
    """
    O ápice da Abstração Científica.
    Encontra as regras empíricas que governam o modelo e aplica a Navalha de Occam Matemática.
    Se uma lei usa 4 premissas para prever X, e o compressador prova empiricamente que 2 premissas
    têm o mesmo poder preditivo sobre o histórico, ele gera uma Teoria Unificada mais geral (Kolmogorov Compression).
    """
    def __init__(self):
        self.abstractions_lib = episodic_compiler._load_abstractions()
        self.abstractions = self.abstractions_lib.get('abstractions', [])
        self.manager = local_world_models.get_manager()
        
    def _extract_clauses(self, causal_structure: str) -> dict:
        """
        Transforma a string descritiva gerada pelo LLM numa dict sintática crua.
        Para operar a compressão de Kolmogorov, nós mapeamos tokens-chave do invariante
        em cláusulas lógicas operáveis.
        (Neste MVP as deduções operam heurísticas baseadas em sub-tokens)
        """
        # Em produção madura, o compiler salva Dicionários Físicos (ex: {"temp": ">10"}).
        # Aqui fazemos um extractor reverso simplificado
        tokens = str(causal_structure).replace(':', ' ').replace('{', ' ').replace('}', ' ').replace('[', ' ').replace(']', ' ').replace(',', '').split()
        return {f"c_{i}": t for i, t in enumerate(tokens) if len(t) > 3} # Ignora as conjunções ("e", "ou", "de")

    def _simulate_predictive_power(self, model, focus_keys: list[str]) -> float:
        """
        Verifica a Força Causal Pura de um subconjunto de features no histórico.
        Retorna Relação Sinal/Ruído (1.0 = Previsão determinística, 0.0 = Acerto randômico)
        """
        if not model.transitions: return 0.0
        
        # Filtra matchings para as chaves testadas
        # Para ser fiel ao World Model, agrupamos por estado reduzido
        state_buckets = defaultdict(list)
        for t in model.transitions:
            flat_st = _flatten_dict(t.get('state_t', {}))
            
            # Recorta apenas a topologia que o compressor quer testar
            reduced_state = tuple(sorted((k, flat_st[k]) for k in flat_st.keys() if k in focus_keys))
            state_buckets[reduced_state].append(t.get('actual_outcome'))
            
        unambiguous_buckets = 0
        total_evals = 0
        
        for signature, outcomes in state_buckets.items():
            if len(outcomes) < 2: continue # Pouca amostragem
            total_evals += len(outcomes)
            # Entropia nula = predição mágica = invariante forte
            if len(set(outcomes)) == 1:
                unambiguous_buckets += len(outcomes)
                
        if total_evals == 0: return 0.0
        return unambiguous_buckets / float(total_evals)

    def scan_and_compress(self) -> list[dict]:
        """
        Varre regras compridas, subtrai pedaços e re-checa contra o World Model.
        Se predizer igual com menos complexidade, promove a nova Lei Comprimida.
        """
        compressions = []
        
        for a in self.abstractions:
            if a.get('status') not in ('compiled_skill', 'under_test'): continue
            
            domain = a.get('domain')
            model = self.manager.models.get(domain)
            if not model or len(model.transitions) < 15: continue
            
            clauses = self._extract_clauses(a.get('causal_structure', ''))
            valid_keys = [k for k in _flatten_dict(model.transitions[-1].get('state_t', {})).keys()]
            
            # Intersecção: Quais features do ambiente real essa regra aborda mentalmente?
            rule_features = [k for k in valid_keys if any(k.lower() in str(val).lower() for val in clauses.values())]
            
            if len(rule_features) < 2: 
                continue # Já é minimamente condensada (O(1))

            current_power = self._simulate_predictive_power(model, rule_features)
            if current_power < 0.6: 
                continue # Regra sequer funciona, não é hora de comprimir
                
            # Busca O(N) Subconjuntos n-1
            # (Remove 1 cláusula por vez para testar se ela era redundante/ruído)
            compression = compress_premises(
                [{"feature": feature} for feature in rule_features],
                list(model.transitions),
                tolerance=0.02,
                min_support=2,
            )
            best_reduction = [_premise_feature(p) for p in compression.get("retained_premises") or []]
            dropped_features = [str(x) for x in compression.get("spurious_features") or []]
            best_sub_power = float((compression.get("compressed_power") or {}).get("score") or 0.0)
            
                # Se o subset alcança predição empírica ESTRITAMENTE EQUIVALENTE,
                # e é menor em dimensão informacional = Otimização Causal Validada.
            if best_reduction and dropped_features and best_sub_power >= (current_power * 0.98):
                reduction_ratio = len(best_reduction) / len(rule_features)
                dropped_dimension = ", ".join(sorted(dropped_features))
                dropped_feature = dropped_dimension
                
                # Formula O Axioma Destilado
                new_causal_struct = f"{a.get('causal_structure')} [Nota do Compressor: A variável '{dropped_feature}' foi isolada e DELETADA (Navalha de Occam). Preditibilidade mantida em {best_sub_power:.1%} usando entropia inferior.]"
                
                compression_report = {
                    'original_id': a['id'],
                    'original_name': a['name'],
                    'dropped_dimension': dropped_feature,
                    'dropped_dimensions': dropped_features,
                    'retained_dimensions': best_reduction,
                    'compression_gain': 1.0 - reduction_ratio,
                    'predictive_power_retained': best_sub_power,
                    'original_predictive_power': current_power,
                    'original_power': compression.get('original_power'),
                    'compressed_power': compression.get('compressed_power'),
                    'new_causal_struct': new_causal_struct
                }
                new_id = f"abs_compressed_{int(time.time())}_{uuid.uuid4().hex[:4]}"
                try:
                    from ultronpro import epistemic_ledger
                    ledger_gate = epistemic_ledger.record_causal_rule_evidence(
                        artifact_id=new_id,
                        claim=new_causal_struct,
                        compression_report=compression_report,
                    )
                    compression_report['epistemic_ledger'] = ledger_gate
                    if not bool(ledger_gate.get('promotion_ready')):
                        continue
                except Exception as e:
                    compression_report['epistemic_ledger'] = {'ok': False, 'error': f'ledger_unavailable:{type(e).__name__}'}
                    continue
                
                # Cria a Hypothesis Nova comprimida e relega a complexa para "revised"
                new_abs = {
                    'id': new_id,
                    'domain': domain,
                    'name': f"Teoria Unificada: {a.get('name')}",
                    'causal_structure': new_causal_struct,
                    'status': 'hypothesis', # Voltará ao ciclo automático para ser provada isoladamente
                    'confirmation_rate': best_sub_power,
                    'success_count': a.get('success_count', 0),
                    'created_at': int(time.time()),
                    'origin': 'kolmogorov_compressor'
                }
                
                a['status'] = 'revised' # Demovida por verbosidade algoritmica
                self.abstractions_lib['abstractions'].append(new_abs)
                compressions.append(compression_report)
                
                # Workspace Pulse
                store.publish_workspace(
                    module='kolmogorov_compressor',
                    channel='causal.mathematical_compression',
                    payload_json=json.dumps(compression_report, ensure_ascii=False),
                    salience=0.9,
                    ttl_sec=7200
                )
                
        if compressions:
           episodic_compiler._save_abstractions(self.abstractions_lib)
           
        return compressions

if __name__ == "__main__":
    print("\n=======================================================")
    print("   CAUSAL KOLMOGOROV COMPRESSOR " )
    print("=======================================================\n")
    compressor = CausalKolmogorovCompressor()
    res = compressor.scan_and_compress()
    if not res:
         print("Nenhuma otimização de Entropia factível no momento. Princípios já estão na representação mínima.")
    else:
         for r in res:
             print(f"✅ Destilação O(N) aplicável à {r['original_name']}.")
             print(f"   ► Dimensão Causal Extirpada (Navalha de Occam aplicada): '{r['dropped_dimension']}'")
             print(f"   ► Retenção Preditiva Confirmada sobre o Histórico: {r['predictive_power_retained']:.1%}")
             print(f"   ► Informação ganhada via compressão de modelo: {r['compression_gain']:.1%}")
