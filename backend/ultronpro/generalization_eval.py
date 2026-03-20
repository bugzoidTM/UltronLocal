from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

BENCHMARK_PATH = Path('/app/data/generalization_benchmark.json')
RECENT_SOURCES_PATH = Path('/app/data/analogy_recent_sources.json')
BENCHMARK_COUNTS_PATH = Path('/app/data/analogy_benchmark_counts.json')
DECISIONS_LOG_PATH = Path('/app/data/analogy_decisions.jsonl')

CASES = [
    # Domínio: Biologia
    {"id": "bio_1", "domain": "biology", "pattern": "redundancy", "query": "Como a redundância de órgãos duplos (rins) em mamíferos se compara a uma arquitetura de alta disponibilidade em TI? Explique o mecanismo de failover biológico."},
    {"id": "bio_2", "domain": "biology", "pattern": "scalability", "query": "Como o crescimento de colônias de fungos (micélio) exemplifica escalabilidade horizontal e descoberta de nós em rede (service discovery)?"},
    {"id": "bio_3", "domain": "biology", "pattern": "garbage_collection", "query": "Compare a autofagia celular (lisossomos) com o mecanismo de Garbage Collection da JVM. Como o sistema identifica objetos/proteínas 'inalcançáveis'?"},
    {"id": "bio_4", "domain": "biology", "pattern": "distributed_consensus", "query": "Como o comportamento de enxame (swarm) em abelhas para escolher um novo local de colmeia se assemelha ao algoritmo Paxos ou Raft?"},
    {"id": "bio_5", "domain": "biology", "pattern": "circuit_breaker", "query": "Explique o choque anafilático como um 'circuit breaker' biológico que falhou ao tentar proteger o sistema (over-correction)."},

    # Domínio: História
    {"id": "hist_1", "domain": "history", "pattern": "rollback", "query": "Analise a tentativa de restauração Meiji no Japão sob a ótica de um rollback de estado sistêmico. Quais foram os 'checkpoints' falhos antes do sucesso?"},
    {"id": "hist_2", "domain": "history", "pattern": "load_balancing", "query": "Como a divisão do Império Romano (Diocleciano) atuou como uma estratégia de Load Balancing para lidar com a latência de comunicação da capital?"},
    {"id": "hist_3", "domain": "history", "pattern": "dependency_hell", "query": "As alianças pré-Primeira Guerra Mundial podem ser vistas como um 'Dependency Hell' (npm/pip) onde um erro em uma dependência pequena derrubou o cluster inteiro?"},
    {"id": "hist_4", "domain": "history", "pattern": "security_perimeter", "query": "A Muralha da China foi um firewall de borda ou um sistema de detecção de intrusão (IDS) ineficaz? Analise as brechas de segurança."},
    {"id": "hist_5", "domain": "history", "pattern": "version_control", "query": "O Renascimento pode ser visto como um 'git merge' de uma branch antiga (Antiguidade Clássica) na branch main degradada (Idade Média)?"},

    # Domínio: Economia
    {"id": "econ_1", "domain": "economy", "pattern": "root_cause", "query": "Identifique a causa raiz da hiperinflação alemã de 1923 usando uma árvore causal de debugging. Onde estava o 'memory leak' monetário?"},
    {"id": "econ_2", "domain": "economy", "pattern": "backpressure", "query": "Como as taxas de juros do Banco Central funcionam como um mecanismo de Backpressure em um pipeline de liquidez?"},
    {"id": "econ_3", "domain": "economy", "pattern": "sharding", "query": "A descentralização bancária (blockchain/DeFi) é uma forma de sharding de banco de dados transacional global?"},
    {"id": "econ_4", "domain": "economy", "pattern": "arbitrage_race_condition", "query": "O mercado de alta frequência (HFT) e arbitragem podem ser analisados como Race Conditions em um sistema distribuído sem relógio global?"},
    {"id": "econ_5", "domain": "economy", "pattern": "deadlock", "query": "Analise a Grande Depressão de 1929 como um Deadlock sistêmico onde o capital (thread) e o consumo (recurso) ficaram em espera mútua."},

    # Domínio: Psicologia
    {"id": "psyc_1", "domain": "psychology", "pattern": "homeostasis", "query": "Explique o mecanismo de defesa de projeção como um 'firewall' de ego. Como o sistema lida com o overflow de ansiedade?"},
    {"id": "psyc_2", "domain": "psychology", "pattern": "neural_weights", "query": "O Transtorno de Estresse Pós-Traumático (TEPT) é uma forma de overfitting de pesos neurais em um cenário de treino de alta variância (trauma)?"},
    {"id": "psyc_3", "domain": "psychology", "pattern": "cache_invalidation", "query": "A dissonância cognitiva é um problema de Cache Invalidation entre a realidade (DB) e a crença (local cache)?"},
    {"id": "psyc_4", "domain": "psychology", "pattern": "multitasking_overhead", "query": "O Transtorno de Déficit de Atenção (TDAH) pode ser modelado como um overhead de Context Switching excessivo no escalonador cerebral?"},
    {"id": "psyc_5", "domain": "psychology", "pattern": "latency_masking", "query": "Como o sono e os sonhos atuam como uma tarefa de manutenção em batch (reindexing/optimization) para reduzir a latência cognitiva diurna?"},

    # Domínio de Referência (Operacional - TI)
    {"id": "tech_ref_1", "domain": "operational", "pattern": "rollback", "query": "Como realizar um rollback seguro em um banco de dados PostgreSQL após uma migração de esquema falha?"},
    {"id": "tech_ref_2", "domain": "operational", "pattern": "root_cause", "query": "Quais as etapas de debugging para encontrar um memory leak em uma aplicação Python rodando em Docker?"},

    # 7.1b — anti-collapse set: casos onde 'sistemas_dinâmicos' não deveria dominar automaticamente
    {"id": "bio_static_1", "domain": "biology", "pattern": "binary_classification", "query": "Um exame marca uma célula como cancerígena ou não com base em três marcadores discretos. Qual analogia estrutural melhor explica uma decisão binária única sem iteração?"},
    {"id": "bio_static_2", "domain": "biology", "pattern": "static_taxonomy", "query": "Classifique um organismo em vertebrado ou invertebrado a partir de características morfológicas fixas. Evite analogias de fluxo contínuo; o problema é uma classificação estática."},
    {"id": "bio_static_3", "domain": "biology", "pattern": "single_gate_decision", "query": "Um receptor celular ativa ou não ativa uma resposta com base na presença de um ligante. Isso é uma decisão única tipo porta lógica, não um sistema dinâmico iterativo."},

    {"id": "hist_static_1", "domain": "history", "pattern": "single_choice", "query": "Um tratado histórico foi assinado ou rejeitado em uma única rodada de decisão. Qual analogia explica uma escolha binária sem feedback contínuo?"},
    {"id": "hist_static_2", "domain": "history", "pattern": "document_authenticity", "query": "Determine se um documento histórico é autêntico ou falso com base em evidências estáticas de caligrafia e material. Isso é classificação forense, não dinâmica."},
    {"id": "hist_static_3", "domain": "history", "pattern": "branch_selection", "query": "Entre dois sucessores possíveis ao trono, apenas um pode ser legitimado por uma regra sucessória fixa. O problema é seleção discreta por regra, não equilíbrio dinâmico."},

    {"id": "econ_static_1", "domain": "economy", "pattern": "credit_approval", "query": "Um banco aprova ou nega um empréstimo com base em score, renda e inadimplência passada. Trata-se de uma decisão binária única, não de um processo contínuo."},
    {"id": "econ_static_2", "domain": "economy", "pattern": "portfolio_label", "query": "Classifique um ativo como renda fixa ou renda variável a partir de propriedades contratuais. O problema é taxonômico e estático."},
    {"id": "econ_static_3", "domain": "economy", "pattern": "rule_based_audit", "query": "Uma transação é marcada como fraude ou não por um conjunto fixo de regras. Procure uma analogia de decisão por regras, não de dinâmica sistêmica."},

    {"id": "psyc_static_1", "domain": "psychology", "pattern": "screening", "query": "Um questionário clínico classifica o risco de depressão como alto ou baixo com base em um limiar de pontuação. É uma triagem estática, não um ciclo dinâmico."},
    {"id": "psyc_static_2", "domain": "psychology", "pattern": "diagnostic_gate", "query": "Um paciente atende ou não atende um critério DSM específico. O problema é uma verificação booleana por checklist."},
    {"id": "psyc_static_3", "domain": "psychology", "pattern": "label_assignment", "query": "Classifique uma resposta observada como comportamento de esquiva ou enfrentamento com base em uma descrição fixa. Isso é rotulagem categórica."}
]

def run_benchmark(api_url: str = "http://127.0.0.1:8000/api/analogy/transfer") -> dict[str, Any]:
    results = []
    start_ts = int(time.time())
    for p in (RECENT_SOURCES_PATH, BENCHMARK_COUNTS_PATH, DECISIONS_LOG_PATH):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    
    print(f"--- Iniciando Benchmark de Generalização ({len(CASES)} casos) ---")
    
    with httpx.Client(timeout=None) as client:
        for case in CASES:
            print(f"Running {case['id']} [{case['domain']}]...")
            t0 = time.time()
            try:
                r = client.post(api_url, json={
                    "problem_text": case["query"],
                    "target_domain": case["domain"]
                })
                dt = time.time() - t0
                
                if r.status_code == 200:
                    data = r.json()
                    status = str(data.get("status") or "")
                    transfer_quality = float(data.get("transfer_quality") or ((data.get("validation") or {}).get("confidence") or 0.0))
                    analogy_source = data.get("analogy_source") or ((data.get("candidate") or {}).get("source_domain"))
                    if status == 'no_candidate':
                        analogy_source = 'no_analogy_found'
                        transfer_quality = 0.0
                    analogy_used = bool(analogy_source) and analogy_source != 'no_analogy_found' and str(analogy_source).strip().lower() != str(case["domain"]).strip().lower()
                    analogy_useful = bool((data.get("validation") or {}).get("valid")) and transfer_quality >= 0.60
                    results.append({
                        "case_id": case["id"],
                        "domain": case["domain"],
                        "pattern": case["pattern"],
                        "ok": True,
                        "status": status or 'ok',
                        "latency_sec": round(dt, 2),
                        "prm_score": data.get("prm_score", 0.0),
                        "analogy_used": analogy_used,
                        "analogy_useful": analogy_useful,
                        "analogy_source": analogy_source,
                        "transfer_quality": transfer_quality
                    })
                else:
                    results.append({"case_id": case["id"], "ok": False, "error": f"status_{r.status_code}"})
            except Exception as e:
                results.append({"case_id": case["id"], "ok": False, "error": str(e)})

    report = {
        "ts": start_ts,
        "total": len(CASES),
        "success_rate": len([r for r in results if r.get('ok')]) / len(CASES),
        "avg_prm": sum([r.get('prm_score', 0) or 0 for r in results if r.get('ok')]) / len(CASES),
        "analogy_hit_rate": len([r for r in results if r.get('analogy_used')]) / len(CASES),
        "results": results
    }
    
    BENCHMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    BENCHMARK_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report

if __name__ == "__main__":
    # Quando rodado localmente no container
    import asyncio
    report = run_benchmark()
    print(json.dumps(report, indent=2))
