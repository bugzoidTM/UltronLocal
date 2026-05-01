import sys
import io

def fix_roadmap():
    with io.open('ROADMAP_AGI_FRONTS.md', 'r', encoding='utf-8') as f:
        text = f.read()

    fix_text = """## Passo 3: POST-ACTION — `measure_and_propagate()`
- [FEITO] Compara previsão vs realidade. Calcula erro normalizado e surpresa.
- [FEITO] **Learning rate inversamente proporcional à confiança prévia**: se o modelo estava "seguro" (confiança alta) e errou, o ajuste é grande. Se já estava incerto e errou pouco, o ajuste é pequeno.
- [FEITO] **Propagação para arestas causais relevantes**: reforça confiança/strength se acertou, enfraquece se errou. Promove `knowledge_type` de `observational` → `interventional_weak` → `interventional_strong` conforme acúmulo de confirmações.
- [FEITO] **Degradação automática**: se confiança cai abaixo de 0.4, `interventional_strong` é rebaixado para `interventional_weak`.
- [FEITO] **Publicação no Global Workspace** via canal `causal.prediction_error` com saliência proporcional à surpresa.

## Convergência esperada
Com alta velocidade de ciclos no sandbox, o grafo causal converge para representações interventivas sólidas. Cada ciclo autônomo gera um sinal de treinamento — não uma análise post-hoc manual.

---

# Ciclo Hipótese-Teste-Revisão — Abstrações como Hipóteses Falsificáveis
_Status: [FEITO 100%]_

Abstrações extraídas de episódios são tratadas como **hipóteses**, não como fatos. O compilador propõe → o sistema testa em episódios futuros → confirma, revisa ou descarta."""

    search_target1 = "Abstrações extraídas de episódios são tratadas como **hipóteses**, não como fatos. O compilador propõe → o sistema testa em episódios futuros → confirma, revisa ou descarta."
    
    if search_target1 in text and "## Passo 3: POST-ACTION" not in text:
        text = text.replace(search_target1, fix_text)

    phase_c_text = """- [FEITO] **Belief Revision Profundo**: Propagação algorítmica deste apontamento: A feature espúria é apagada dos invariantes do Model e TODAS as Abstrações (Skills Causal-Pragmáticas) que dependiam desta covariância são cassadas automaticamente (`rejected_by_epistemic_dispute`), blindando o sistema contra alucinações matemáticas da mesma origem no futuro.

---

# Fase C — Agência Epistêmica de Longo Prazo
*Status: [FEITO 100%]*

O sistema transcendeu a execução reativa de tarefas e o empirismo isolado. Ele agora formula, decompõe e persegue autonomamente projetos cognitivos extensos (que duram meses), amarrando curiosidade imediata, planejamento causal aprofundado e identidade persistente.

## C.1 Epistemic Project Manager (Macro-Objetivos)
_Módulo: `long_term_epistemic_agency.py`_
- [FEITO] **Decomposição Causal**: Transforma um macro-objetivo (ex: 'Compreender o mercado cripto brasileiro') em um pipeline de milestones rígidas dependentes: Data Harvesting -> Redução de Incerteza (Surpresa < 0.2) -> Descoberta Matemática de Variáveis -> Destilação de Kolmogorov.
- [FEITO] **Sincronização de Identidade**: Injeta o macro-projeto no `self_governance.py` (`identity_anchor`). O sistema não esquece sua grande missão epistêmica mesmo se a memória de curto prazo expirar ou após centenas de sleep cycles.
- [FEITO] **Curiosidade Direcionada**: Aciona o `learning_agenda.py` furtivamente. O Autofeeder passará a caçar dados sobre o domínio do projeto epistêmico organicamente na web toda vez que tiver tempo de processamento ocioso, acelerando a fundação empírica.

## C.2 Monitoramento e Replanejamento de Quebra Paradigmática
- [FEITO] **Tick Causal Contínuo**: Acompanha a integridade do modelo associado via hook no `agi_path_loop()`. Avalia empiricamente se os marcos estão sendo alcançados (medindo erros de predição do `LocalWorldModel`).
- [FEITO] **Causal Replanning**: Se as abstrações amadurecerem, mas o ambiente se alterar brutalmente (ex: quebra estrutural do mercado e a 'surpresa' dispara nas predições da AGI), o sistema coloca o projeto em `replanning`. Ele entende que 'O Paradigma Fundamental colapsou' e recalcula a rota epistêmica, não apenas fechando tickets de erro isolados.
- [FEITO] Endpoints API (`/api/epistemic/project` e `/api/epistemic/projects`) criados para input humano da matriz primária ou auto-injeção reflexiva do próprio Planner.
"""

    search_target2 = "- [FEITO] **Belief Revision Profundo**: Propagação algorítmica deste apontamento: A feature espúria é apagada dos invariantes do Model e TODAS as Abstrações (Skills Causal-Pragmáticas) que dependiam desta covariância são cassadas automaticamente (`rejected_by_epistemic_dispute`), blindando o sistema contra alucinações matemáticas da mesma origem no futuro."
    
    if search_target2 in text and "Fase C — Agência Epistêmica" not in text:
        text = text.replace(search_target2, phase_c_text)

    with io.open('ROADMAP_AGI_FRONTS.md', 'w', encoding='utf-8') as f:
        f.write(text)

if __name__ == '__main__':
    fix_roadmap()
