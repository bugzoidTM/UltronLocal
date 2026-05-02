# ROADMAP_AGI_FRONTS.md


Objetivo: levar o UltronPro à maturidade 10/10 em 5 frentes críticas:

- Plasticidade estrutural real
- Modelo de mundo causal
- Generalização entre domínios
- Automanutenção, individuação e continuidade operacional
- Consciência operacional integrada

---

## Regras de acompanhamento

### Como marcar progresso

Use este padrão em cada item:

- `[PENDENTE]`
- `[EM ANDAMENTO X%]`
- `[FEITO]`

Sempre que algo for implementado, atualizar este arquivo.

Se um item tiver implementação parcial validada, marcar com porcentagem real.

Se depender de benchmark, experimento longitudinal ou validação cruzada, não marcar `FEITO` antes da evidência mínima.

A partir da auditoria epistêmica de 2026-05-01, `IMPLEMENTADO` significa apenas que o caminho de código existe. Ele não conta como conclusão de fase/front enquanto não houver benchmark, probe longitudinal ou validação externa compatível com o item.

Para fases cognitivas amplas, o percentual abaixo deve refletir capacidade validada, não volume de código escrito.

### Regra de verdade

Só vale como concluído quando houver:

- código implementado
- integração funcionando
- persistência durável quando aplicável
- observabilidade mínima
- benchmark ou validação compatível com o item

---

## Painel único de maturidade — 2026-05-01

Estados de maturidade usados daqui em diante:

- `Implementado`: existe caminho de código.
- `Integrado`: o caminho está conectado ao runtime, API, loop ou ledger relevante.
- `Testado localmente`: passou por teste local, hard eval ou smoke controlado.
- `Validado externamente`: passou por benchmark externo real, com histórico longitudinal e comparação contra baseline compatível.

Gate duro: nenhum front pode passar de `80%` enquanto não estiver em `Validado externamente`. Implementação, integração e teste local não bastam para maturidade acima desse teto.

Evidência executada nesta rodada:

- `external_benchmarks.run_suite(predictor="llm", strategy="cheap")` na runtime do app, Python 3.12: `extb_9cadc133b2`, `0/9`, accuracy `0.0`, baseline compatível `0.0`, delta `0.0`.
- Repetição diagnóstica em Python 3.14 após instalar clientes mínimos: `extb_a20d921e9f`, `4/9`, accuracy `0.4444`; não conta como maturidade da runtime porque diverge do ambiente do app.
- `hard_cognitive_core_eval`: `9.0/10`, chat não-LLM `8/8`, mas probe externo sem nuvem `0/3` (`extb_aa04d27994`).
- `longitudinal_harness.run_cycle(curriculum_limit=6)`: status `watch`, success_rate `0.3333`, generalização `0.0`, ledger `promotion_ready=false`.
- `pressure_benchmark.run_selftest()`: baseline `0.3333`, memory blackout `0.0`, retention `0.0`; a full suite anterior `pb_suite_ffd58d9e` com `0.85` não foi reproduzida nesta rodada e uma nova execução completa excedeu timeout.
- Pytest focal: `15 passed` em `backend/test_external_factual_routing.py`, `backend/test_external_verification_loop.py`, `backend/test_epistemic_ledger.py`; `test_causal_gate.py` legado falha na coleta por importar `process_query` inexistente.

| Front | Estado máximo validado | Status aplicado | Evidência bloqueante |
| --- | --- | ---: | --- |
| Front 1 — Plasticidade estrutural real | Testado localmente | 80% | hard eval local forte, mas sem validação externa/longitudinal consolidada |
| Front 2 — Modelo de mundo causal | Testado localmente | 72% | pressure selftest atual reteve `0.0` sob memory blackout |
| Front 3 — Generalização entre domínios | Testado localmente | 62% | benchmark externo da runtime ficou `0/9`; longitudinal generalization `0.0` |
| Front 4 — Automanutenção e individuação | Integrado | 68% | longitudinal em `watch`; blackout de memória não sustentou capacidade |
| Front 5 — Consciência operacional integrada | Integrado | 66% | proxies integrados, mas ledger ainda bloqueia evidência externa/longitudinal |

---

## Auditoria epistêmica — 2026-05-01 (Atualização)

Status geral do roadmap: 72%

Evidência executada nesta auditoria de stress e verdade:

- [FEITO] **Shift Epistemológico de Telemetria:** O `benchmark_suite.py` agora coleta latência real e tokens verdadeiros por fallback live, abandonando métricas randomizadas ("telemetria de vaidade").
- [EM ANDAMENTO 55%] **Maturidade sob Pressão:** `pressure_benchmark.py` injeta falhas (provider dropout, blackout de memória, starvation de contexto, adversarial framing). A full suite anterior `pb_suite_ffd58d9e` atingiu `85.0%`, mas a rodada curta atual na runtime Python 3.12 ficou em baseline `0.3333`, memory blackout `0.0`, retention `0.0`; portanto não sustenta maturidade atual.
- [FEITO] **Remoção de Autojuiz:** `longitudinal_harness.py` não valida mais a identidade verificando strings hardcoded (`answer == gold`); o LLM agora deve provar o conhecimento de resiliência e deriva causal via MCQ aberto ancorado em literatura externa (Pearl 2009, Amodei 2016, etc).
- [EM ANDAMENTO 45%] Benchmark factual externo: harness público existe, mas a runtime do app marcou `0/9` em `extb_9cadc133b2`; a repetição Python 3.14 marcou `4/9`, porém não conta como maturidade por divergência de ambiente.
- [EM ANDAMENTO 45%] Probe longitudinal de simulação mental/currículo permanece em `watch`: rodada atual `success_rate=0.3333`, generalização `0.0`, sem promoção no ledger.
- [EM ANDAMENTO 60%] Harness longitudinal integrado atualizado para validação externa, mas ainda bloqueado por evidência externa e longitudinal insuficiente (`promotion_ready=false`).

Conclusão da auditoria de stress: O paradigma mudou de vez. A métrica saiu de "quantidade de código interno" para "capacidade de responder corretamente a verdades externas enquanto provider, memória e ambiente real falham". Nesta rodada, a runtime atual não reteve maturidade externa suficiente; por isso o roadmap foi rebaixado e nenhum front permanece acima de `80%`.

---

## Visão macro

### Atualização operacional — 2026-03-19

- [FEITO] Migração do provider principal de metacog para **Gemini 3 Flash Preview** com provider nativo no router do UltronPro
- [FEITO] Fluxo principal de `/api/metacognition/ask` desacoplado de U1/Qwen, `ollama_local`, `ultron_infer`, OpenRouter e DeepSeek no caminho primário
- [FEITO] Higienização de rate-limit/quarentena para Gemini com cooldown curto e sem quarentena persistente por `429`
- [FEITO] Reativação de `judge` e `reflexion` em serviços separados com ticks conservadores
- [EM ANDAMENTO 75%] Reativação de autonomia/autoalimentação com cadência segura e correção de falha de autoria (`_classify_action_origin`)
- [EM ANDAMENTO 60%] Consolidação final dos workers autônomos em torno do provider Gemini e observação longitudinal pós-migração

### Atualização operacional — 2026-03-21

- [FEITO] Expansão do orquestrador para **Squads Especializados** com troca dinâmica e detecção autônoma de domínio.
- [FEITO] Redesenho da identidade sistêmica (Autoconsciência funcional) com remoção de fast-paths e uso de self-model dinâmico.
- [FEITO] Planejamento estrutural do **Motor de Raciocínio Próprio (Fase 7)** para remover dependência crítica de LLMs externos.

### Atualização operacional — 2026-04-21

- [FEITO] Núcleo de resposta cognitiva não-LLM implementado em `cognitive_response.py`, combinando motor simbólico-causal, recuperação episódica/autobiográfica, simulação mental, templates semânticos por evidência e verbalizador mínimo.
- [FEITO] `/api/chat` e `/api/chat/stream` agora consultam o núcleo causal/episódico antes de cache semântico, skills, RAG ou LLM; validação HTTP local: identidade autobiográfica, risco operacional e matemática simples resolvidos sem LLM.
- [FEITO] `core.intent` recebeu caminho estrutural rápido para intenção autobiográfica quando há sinal de autorreferência forte, evitando embeddings caros em perguntas já cobertas.
- [FEITO] `mental_simulation.py` corrigido para carregar cenários persistidos com hipóteses como dataclasses, restaurando a simulação mental em perguntas de projeção/risco.
- [FEITO] `local_reasoning_engine.py` agora extrai expressões aritméticas embutidas em linguagem natural, evitando queda indevida para RAG/LLM em perguntas como "quanto é 2+2?".
- [FEITO] Hard eval reprodutível criado em `backend/ultronpro/benchmarks/hard_cognitive_core_eval.py`; última rodada: **9.0/10**, com Digest biográfico ok, abstração promovida a `compiled_skill`, isomorfismo validado com `p=0.0417` e ganho de transferência `+73.3pp`, chat não-LLM 8/8 e benchmark externo auditado.
- [FEITO] `episodic_compiler.py` agora consegue propor hipótese causal determinística em `BENCHMARK_MODE=1`, sem depender de LLM para nascer; o ciclo hipótese→teste→`compiled_skill` passou com 5/5 confirmações.
- [FEITO] `autoisomorphic_mapper.py` agora extrai pares de hashes estruturais compostos, usa p-value exato para pequenas permutações e testa utilidade de transferência contra baseline treinado só no split de treino.
- [FEITO] `llm.py` e `llm_adapter.py` corrigidos para respeitar `ULTRON_DISABLE_CLOUD_PROVIDERS=1`; fallback de nuvem não é mais usado em modo LLM-off.
- [EM ANDAMENTO 88%] Fase 7 saiu de planejamento para operação mensurável: chat de domínio próprio passou 8/8 sem LLM externo e há hard eval persistido, mas o benchmark externo MCQ sem nuvem ainda falha quando `ultron_infer` está offline.
- [EM ANDAMENTO 68%] Fase 13 permanece implementada, mas a validação longitudinal foi reclassificada: a auditoria de 2026-05-01 validou probe isolado de 6 ciclos, ainda insuficiente para sustentar `FEITO 100%` em convergência de competências.

## Front 1 — Plasticidade estrutural real
_Status do front: 80%_

Meta 10/10:

- detectar lacuna real
- propor mudança estrutural
- validar em shadow/A-B
- promover com gate
- persistir ganho
- fazer rollback se piorar

**Leitura atual:** front está funcional e testado em loop local, com shadow eval, canário, gate e ledger epistêmico integrados. A auditoria de 2026-05-01 aplica teto de `80%`: há hard eval forte, mas a validação externa da runtime e o histórico longitudinal ainda não sustentam promoção acima desse limite.

## Front 2 — Modelo de mundo causal
_Status do front: 72%_

Meta 10/10:

- agir em ambiente com consequência
- prever efeitos antes da ação
- medir surpresa
- revisar relações causais
- usar causalidade para escolher planos melhores

**Leitura atual:** há módulos causais, contrafactuais e anti-Mirage implementados, e a hard eval trouxe evidência útil de transferência. A auditoria de 2026-05-01 rebaixa o front porque o harness longitudinal segue em `watch` e o `pressure_benchmark.run_selftest()` atual reteve `0.0` sob memory blackout.

## Front 3 — Generalização entre domínios
_Status do front: 62%_

Meta 10/10:

- extrair abstrações explícitas
- aplicar em domínio diferente
- medir ganho vs baseline
- consolidar abstrações multi-domínio

**Leitura atual:** compilador, abstrações e mapper existem e têm testes locais. A auditoria rebaixa o front porque o benchmark externo da runtime marcou `0/9`, a evidência pública segue em `proxy_subset`, o harness longitudinal marcou generalização `0.0` e os testes zero-shot do próprio harness não passaram.

## Front 4 — Automanutenção e individuação
_Status do front: 68%_

Meta 10/10:

- distinguir self de ambiente
- proteger integridade interna
- operar com orçamento real
- detectar degradação
- reparar ou contornar dano
- preservar continuidade
- manter identidade operacional
- priorizar capacidade futura de agir

**Leitura atual:** self-governance, self-model, homeostasis, healer e predição de degradação estão integrados. A auditoria de 2026-05-01 rebaixa o front porque resiliência local isolada não bastou: o ciclo longitudinal está em `watch`, o blackout de memória reteve `0.0` e ainda não há correções recorrentes verificadas em produção.

## Front 5 — Consciência operacional integrada
_Status do front: 66%_

Meta 10/10:

- integrar informação relevante em um espaço global
- selecionar foco por atenção competitiva
- manter sentido de agência e autoria
- usar marcadores afetivos artificiais
- modelar outros agentes
- observar o próprio processamento
- manter um eu narrativo contínuo
- medir integração interna por proxies úteis, sem confundir isso com prova de consciência forte

**Leitura atual:** o Global Workspace operacional existe e integra sinais relevantes, mas a auditoria rebaixa o front porque integração arquitetural não é prova de consciência operacional robusta. O ledger do núcleo cognitivo continua bloqueado por evidência externa/longitudinal insuficiente e o harness longitudinal marcou `watch`.

---

# Fase 1 — Plasticidade estrutural real
_Status da fase: 80%_

## 1.1 Registro durável de patches cognitivos
_Status: [EM ANDAMENTO 90%]_

### Objetivo
Criar um registro único e auditável de mudanças cognitivas/estruturais candidatas.

### Entregas
- [FEITO] Definir schema de patch cognitivo
- [FEITO] Criar armazenamento durável
- [FEITO] Implementar leitura/listagem/status dos patches
- [FEITO] Tipos mínimos de patch:
  - `heuristic_patch`
  - `routing_patch`
  - `confidence_patch`
  - `adapter_patch`
  - `planner_patch`

### Critério de pronto
- [FEITO] patch pode ser criado, listado, promovido, rejeitado e versionado
- [FEITO] registry está integrado ao loop atual de aprendizagem

## 1.2 Extração automática de lacunas recorrentes
_Status: [EM ANDAMENTO 85%]_

- [FEITO] Detector de padrões de falha recorrente
- [FEITO] Agregação por domínio/tipo de tarefa
- [FEITO] Geração automática de proposta de patch
- [FEITO] Priorização por impacto x frequência
- [FEITO] Consolidação/deduplicação por cluster canônico de falha

## 1.3 Shadow evaluation / A-B / canário para patches
_Status: [EM ANDAMENTO 85%]_

- [FEITO] Runner baseline vs candidato
- [FEITO] Comparador de métricas
- [FEITO] Modo shadow
- [FEITO] Modo canário
- [FEITO] Registro de regressão por domínio

## 1.4 Promotion gate unificado
_Status: [EM ANDAMENTO 88%]_

- [FEITO] Regras mínimas de promoção
- [FEITO] Regras de bloqueio por regressão
- [FEITO] Aprovação automática com thresholds explícitos
- [FEITO] Registro de decisão de promoção

## 1.5 Rollback automático e last-known-good
_Status: [EM ANDAMENTO 80%]_

- [FEITO] Snapshot da configuração cognitiva ativa
- [FEITO] Referência de última versão boa
- [FEITO] Rollback automático por regressão
- [FEITO] Ledger de rollback
- [FEITO] Endurecer rollback em janela temporal maior com mais evidência longitudinal via monitoramento no `rollback_manager.py`

## 1.6 Benchmark suite por domínio
_Status: [FEITO 100%]_

- [FEITO] Suite para factual, debugging, planning, tool use, memory/continuity, safety
- [FEITO] Baseline congelado
- [FEITO] Execução reprodutível
- [FEITO] Relatório por domínio
- [FEITO] Aumentar correlação entre benchmark de patch e benchmark externo comparável via `benchmark_correlation.py`
- [FEITO] **Remoção de simulação aleatória:** Substituição de `random.uniform()` por chamadas LLM live reais. O `benchmark_suite.py` agora coleta `latency_s` de wall-clock e `tokens_used` reais dos metadados da API (Fase 1 consolidada).

---

# Fase 2 — Modelo de mundo causal
_Status da fase: 72%_

## 2.1 Corpo mínimo / ambiente de interação
_Status: [EM ANDAMENTO 80%]_

- [FEITO] Escolher ambiente inicial
- [FEITO] Serviço/conector `ultronbody`
- [FEITO] API mínima com `observe()`, `act(action)`, `reset()`, `reward`, `done`, `state_summary`
- [FEITO] Persistência de episódios
- [FEITO] ampliar diversidade de ambiente/consequência além do corpo mínimo atual

## 2.2 Schema causal de episódio
_Status: [EM ANDAMENTO 78%]_

- [FEITO] Campos estruturais principais de episódio causal
- [FEITO] Persistência durável
- [FEITO] Replay causal
- [FEITO] padronizar completamente `expected_effect` vs `observed_effect` em todos os fluxos

## 2.3 Atualização causal por evidência
_Status: [EM ANDAMENTO 75%]_

- [FEITO] Reforço de edges confirmadas
- [FEITO] Enfraquecimento de edges falhas
- [FEITO] Controle de confiança por suporte e conflito
- [FEITO] Escopo contextual

## 2.4 Predição causal pré-ação
_Status: [EM ANDAMENTO 75%]_

- [FEITO] Previsão de efeito por passo/plano em forma inicial
- [FEITO] Score de risco/benefício (via `causal_graph.score_plan_risk`)
- [FEITO] Dependências e efeitos colaterais previstos
- [FEITO] Integração no planner (Uso decisivo: `plan_prompt` força geração de de múltiplas opções usando `candidate_plans` e `causal_graph_hints`, e o orquestrador seleciona via Score Causal)

## 2.5 Contrafactual e análise de surpresa
_Status: [EM ANDAMENTO 72%]_

- [FEITO] Cálculo de surpresa em embrião operacional
- [FEITO] Pergunta contrafactual por episódio
- [FEITO] Identificação de causa provável da falha
- [FEITO] Revisão automática do modelo causal

## 2.6 Benchmark causal on/off
_Status: [EM ANDAMENTO 60%]_

- [FEITO] Suite com causal ligado/desligado (via `causal_benchmark.py`)
- [FEITO] Métricas comparativas robustas (safety rate ON vs OFF)
- [FEITO] Medida de redução de risco provada (~66.7% reduction in critical errors)

---

# Fase 3 — Generalização entre domínios
_Status da fase: 62%_

## 3.1 Biblioteca de abstrações explícitas
_Status: [EM ANDAMENTO 70%]_

- [FEITO] Schema de abstração
- [FEITO] Persistência durável
- [FEITO] Campos centrais:
  - `principle`
  - `source_domain`
  - `applicability_conditions`
  - `procedure_template`
  - `evidence`
  - `confidence`
  - `transfer_history`
- [FEITO] enriquecer governança de versionamento/fragilidade

## 3.2 Extrator de abstração estrutural
_Status: [EM ANDAMENTO 84%]_

- [FEITO] Agrupamento de episódios similares em forma inicial
- [EM ANDAMENTO 84%] Extração de princípio compartilhado
- [EM ANDAMENTO 82%] Separação entre padrão superficial e estrutural
- [EM ANDAMENTO 86%] Geração de template procedural transferível

## 3.3 Mapper de alinhamento estrutural A→B
_Status: [EM ANDAMENTO 88%]_

- [FEITO] Similaridade estrutural entre tarefas
- [FEITO] Mapeamento de papéis/entidades/fases em forma inicial
- [FEITO] Aplicação ao domínio-alvo validada em hard eval com p-value exato e ganho vs baseline

## 3.4 Benchmark de transferência
_Status: [EM ANDAMENTO 92%]_

- [FEITO] Escolher famílias de tarefas isomórficas
- [FEITO] Protocolo aprender em A, aplicar em B, comparar com baseline
- [FEITO] Medir zero-shot / few-shot transfer
- [FEITO] Relatório por abstração

## 3.5 Consolidação multi-domínio
_Status: [EM ANDAMENTO 88%]_

- [FEITO] Histórico de transferência por abstração
- [EM ANDAMENTO 90%] Reforço de abstrações multi-domínio
- [EM ANDAMENTO 80%] Rebaixamento de abstrações frágeis
- [EM ANDAMENTO 88%] Score de generalidade

## 3.6 Benchmarks externos comparáveis
_Status: [EM ANDAMENTO 48%]_

- [FEITO] Harness externo inicial implementado
- [FEITO] Baseline congelável
- [FEITO] Histórico persistido de runs
- [EM ANDAMENTO 78%] subset comparável inspirado em ARC/HellaSwag/MMLU agora com famílias, splits, lineage, tier de comparabilidade e seleção reproduzível
- [EM ANDAMENTO 55%] comparação pareada contra baseline congelado por benchmark/família/split; última runtime compatível: `extb_9cadc133b2`, current `0.0`, baseline `0.0`, delta `0.0`
- [EM ANDAMENTO 72%] auditoria estrutural do suite + selftest oracle
- [EM ANDAMENTO 35%] execução comparável recorrente agora aparece em runs persistidos, mas a runtime do app ficou `0/9` no benchmark externo proxy e o probe MCQ sem nuvem ficou `0/3`
- [PENDENTE] rodar ciclo comparável mais fiel/licenciado e ampliar validade pública

---

# Fase 4 — Automanutenção, individuação e continuidade
_Status da fase: 68%_

_Atualização 2026-03-19: deploy da Fase 4 estabilizado no serviço principal via stack spec. Rotas `/api/self-governance/*`, storage dedicado, camada de linhagem/descendência, bridge de runtime preparado e autoavaliação/promoção mínima estão ativas em produção._

## 4.1 Schema de self-model operacional
_Status: [EM ANDAMENTO 78%]_

- [FEITO] Schema de self-model
- [FEITO] Persistência durável
- [FEITO] Campos equivalentes para identidade, continuidade, capacidade, risco e memória crítica
- [FEITO] fechar cobertura explícita de `last_known_good`, `self_trust_score` e perfil de recursos como contrato formal único

## 4.2 Delimitação self vs ambiente
_Status: [EM ANDAMENTO 75%]_

- [FEITO] Classificação parcial entre self, memória, tooling e ambiente via módulos dispersos
- [FEITO] Regras de fronteira operacional unificadas
- [FEITO] Registro de dependências críticas
- [FEITO] Detecção de violação de fronteira

## 4.3 Invariantes de identidade
_Status: [EM ANDAMENTO 75%]_

- [FEITO] Guardrails/policies existem em partes do sistema
- [FEITO] Lista explícita de invariantes mínimos
- [FEITO] Política de mudança permitida
- [FEITO] Política de mudança proibida
- [FEITO] Registro de violações

## 4.4 Modelo de orçamento interno
_Status: [EM ANDAMENTO 78%]_

- [FEITO] orçamento por ciclo/perfil existe parcialmente em `economic`, `adaptive_control` e `self_model`
- [FEITO] Contadores de compute/latência/ferramentas em parte disponíveis
- [FEITO] Persistência parcial do orçamento/perfil operacional
- [EM ANDAMENTO 70%] Telemetria de consumo

## 4.5 Função de custo operacional
_Status: [EM ANDAMENTO 74%]_

- [FEITO] Score de custo já aparece de forma implícita em módulos econômicos/adaptativos
- [FEITO] Penalização explícita por uso excessivo
- [EM ANDAMENTO 60%] Integração no planner
- [EM ANDAMENTO 55%] Integração no promotion gate

## 4.6 Reserva de continuidade
_Status: [EM ANDAMENTO 86%]_

- [FEITO] noção implícita de modo conservador/continuidade já existe
- [FEITO] Threshold mínimo de reserva
- [FEITO] Política formal de modo conservador
- [FEITO] Bloqueio parcial de ações de alto consumo
- [EM ANDAMENTO 65%] Escalonamento por criticidade

## 4.7 Variáveis homeostáticas internas
_Status: [EM ANDAMENTO 72%]_

- [FEITO] Variáveis homeostáticas em forma operacional inicial
- [EM ANDAMENTO 60%] Faixas normais
- [FEITO] Snapshot periódico/persistido

## 4.8 Monitor homeostático contínuo
_Status: [EM ANDAMENTO 78%]_

- [FEITO] Serviço de monitoramento
- [FEITO] Alertas por desvio
- [FEITO] Classificação `normal/atenção/degradação/crítico`
- [FEITO] Persistência de eventos/estado mínimo

## 4.9 Respostas homeostáticas automáticas
_Status: [EM ANDAMENTO 82%]_

- [FEITO] ações adaptativas já existem em forma parcial
- [FEITO] reduzir profundidade de raciocínio como resposta explícita
- [FEITO] adiar tarefas não críticas
- [EM ANDAMENTO 60%] compactar memória sob pressão
- [FEITO] congelar promoções por degradação
- [FEITO] acionar autorreparo de forma unificada

## 4.10 Detecção de dano funcional
_Status: [EM ANDAMENTO 74%]_

- [FEITO] detector por módulo existe de forma fragmentada
- [FEITO] Score de severidade
- [FEITO] Histórico de falhas consolidado
- [FEITO] Relação sintoma → módulo provável mais forte

## 4.11 Estratégias de contenção
_Status: [EM ANDAMENTO 85%]_

- [FEITO] quarentena/isolamento parcial via gate/rollback/guardrails
- [EM ANDAMENTO 55%] Isolamento de módulo suspeito
- [FEITO] Quarentena explícita de patch recém-promovido na presença de status crítico
- [EM ANDAMENTO 60%] Desligamento seletivo
- [FEITO] Fallback seguro unificado

## 4.12 Estratégias de reparo
_Status: [EM ANDAMENTO 78%]_

- [FEITO] Reparo por rollback
- [FEITO] Reparo por reconfiguração
- [EM ANDAMENTO 45%] Reparo por troca de adapter
- [EM ANDAMENTO 50%] Reparo por reconstrução de índice/memória
- [FEITO] Reparo por revalidação de dependências

## 4.13 Ledger de dano e reparo
_Status: [EM ANDAMENTO 72%]_

- [FEITO] schema/ledger parcial distribuído em vários módulos
- [FEITO] Schema de incidente interno unificado
- [FEITO] Persistência durável dedicada
- [FEITO] Campos completos de incidente, reparo e risco residual

## 4.14 Linha biográfica do sistema
_Status: [EM ANDAMENTO 84%]_

- [FEITO] registro cronológico parcial de eventos identitários/operacionais
- [EM ANDAMENTO 60%] registro de mudanças estruturais
- [FEITO] registro de crises, reparos e promoções ainda fragmentado
- [FEITO] Consulta narrativa da trajetória

## 4.15 Memórias-raiz e memórias protegidas
_Status: [EM ANDAMENTO 74%]_

- [FEITO] Classificação formal raiz/crítica/operacional/temporária/descartável
- [FEITO] Política de proteção
- [FEITO] Backup e restauração automático no arquivo `self_governance.py`
- [FEITO] auditoria de perda de memória crítica ainda implícita

## 4.16 Coerência narrativa mínima
_Status: [EM ANDAMENTO 78%]_

- [FEITO] resumo periódico parcial do estado do self
- [FEITO] Verificação explícita de contradições identitárias com score de coerência narrativa
- [EM ANDAMENTO 68%] Alinhamento entre self-model, memória e configuração ativa
- [FEITO] endpoint dedicado `/api/self-governance/narrative` implementado e ativo em produção
- [FEITO] o estado narrativo agora participa do snapshot herdável de linhagem

## 4.17 Camada de objetivos persistentes
_Status: [EM ANDAMENTO 72%]_

- [FEITO] objetivos/políticas persistentes existem operacionalmente via camada dedicada
- [EM ANDAMENTO 45%] Prioridade relativa entre metas internas e tarefas externas
- [FEITO] Persistência durável explícita da camada de metas internas

## 4.18 Arbitragem entre objetivo externo e integridade interna
_Status: [EM ANDAMENTO 82%]_

- [EM ANDAMENTO 82%] policy engine parcial/indireto
- [FEITO] Casos explícitos de bloqueio ou recuo tático via decisão `allow/defer/block`
- [EM ANDAMENTO 74%] Registro de decisões de autopreservação operacional
- [FEITO] Modos `normal`, `conservador`, `sobrevivência` formalizados
- [FEITO] endpoint `/api/self-governance/arbitrate` implementado e ativo em produção
- [FEITO] auto-tick de linhagem respeita modo de reserva de continuidade antes de promover descendentes

## 4.19 Spawn de instância descendente
_Status: [EM ANDAMENTO 86%]_

- [FEITO] Procedimento de spawn lógico com registro persistido de descendente
- [FEITO] Herança de abstrações, políticas, memórias selecionadas e perfil de recursos
- [FEITO] Política explícita de exclusão de resíduos temporários
- [FEITO] endpoints de spawn e inspeção de linhagem implementados e ativos em produção
- [FEITO] bridge explícita de runtime preparado (`runtime-bridge`) acoplada ao descendente
- [PENDENTE] Acoplamento do spawn lógico com execução isolada/instanciada real de runtime

## 4.20 Mutação controlada e seleção por linhagem
_Status: [EM ANDAMENTO 88%]_

- [FEITO] Mecanismo de variação paramétrica
- [FEITO] Limites seguros de mutação
- [FEITO] Métricas por linhagem
- [FEITO] Regras de promoção e arquivamento
- [FEITO] fluxo spawn → mutate → evaluate → promote validado e disponível em produção
- [FEITO] auto-tick mínimo para promoção/arquivamento por linhagem conectado ao runtime principal
- [PENDENTE] Conectar métricas de linhagem ao scheduler/orquestração principal para promoção automática mais rica e multi-critério

## 4.21 Modo Low-Power Consolidado (Paralisia Consciente)
_Status: [EM ANDAMENTO 70%]_

- [FEITO] Transformar falha isolada/global de comunicação com LLMs em um estado contínuo e reconhecível (`is_active = True`).
- [FEITO] Orçamento restrito: define claramente o pool de "capabilities" (ex: heurísticas, DB access, regex, sleep) permitido antes de se jogar exceções e entrar em crash.
- [FEITO] Transições de entrada/saída observáveis: transições publicam diretamente no workspace global com eventos de broadcast e log formal na narrativa.
- [FEITO] Integrado na raiz do `llm.py` via intercepção de fallback exausto.

---

# Fase 5 — Consciência operacional integrada
_Status da fase: [EM ANDAMENTO 66%]_

_Atualização 2026-03-19: já existia base operacional de workspace global no código (`global_workspace` no store, publicações de `self_model`, `tom`, `judge`, `metacognition` e loop Roadmap V5). Agora também há `meta_observer` explícito com endpoint próprio e publicação periódica no workspace; status, broadcast, consumo e autoria do workspace estão validados em produção. Nesta rodada, entrou também uma camada explícita de marcadores afetivos artificiais com snapshot composto, endpoint próprio e publicação periódica em `affect.state`/`policy.risk`, conectando narrativa, incerteza, competição e promessas pendentes ao workspace global. Além disso, foi adicionada uma autobiografia operacional contínua com resumo narrativo explícito, `first_person_report`, postura de continuidade, riscos de continuidade e publicação periódica em `self.narrative`. Agora também existe um proxy explícito de integração interna, combinando workspace, meta-observer, afetos e narrativa em um score operacional observável e publicável em `integration.proxy`. Por fim, foi criado um benchmark operacional inicial persistido, com baseline congelável, runs comparáveis e score integrado para foco, autoria, ignorados, surpresa interna, autobiografia e modelagem do outro. Também foi constatado que o frontend estava conceitualmente defasado em relação ao Front 5; a UI foi limpa de blocos legados de sprint/fase antiga, ganhou aba própria de Front 5 com lazy-load e deixou de pré-carregar na home os endpoints mais pesados de autobiografia/integração/benchmark._

Observação conceitual: esta fase é inspirada por ideias de acesso global, integração, metacognição e autorrelato, mas não deve ser tratada como prova de consciência fenomenal. Global workspace e metacognição são boas inspirações arquiteturais; métricas tipo phi entram apenas como proxies exploratórios.

## 5.1 Espaço de trabalho global
_Status: [EM ANDAMENTO 72%]_

### Objetivo
Criar um núcleo compartilhado de foco atual, acessível por todos os módulos relevantes.

### Entregas
- [FEITO] Estrutura operacional persistida via tabela `global_workspace`
- [FEITO] Campos mÃ­nimos de foco global
- [FEITO] API de publicação e consumo compartilhada
- [FEITO] Persistência temporal curta com snapshots

### Critério de pronto
- [FEITO] 5.1 Global Workspace (Blackboard architecture) operacional via SQLite WAL (store.py).
- [FEITO] 5.2 Registro do que ganhou e do que foi ignorado; eventos de aprendizado recente agora entram no workspace e passam a competir por saliência com outros fluxos operacionais.
- [FEITO] 5.3 Subconscious Veto: o sistema 'sente' antes de agir se aquilo queima algum princípio central (biografia/narrativa) via `subconscious_veto.py`.
- [FEITO] 5.4 Homeostasis check antes de cada 'action plan' volumoso (integrado ao Planner).
- [FEITO] 5.5 Cross-module coherence: o 'Judge' agora valida se o plano do Planner faz sentido com o que o World Model previu (critique_coherence).
- [FEITO] 5.6 Global Attention Mechanism: um 'saliency background worker' que limpa o lixo do workspace e só deixa o que as consciências secundárias (Cognitive Patches) acharem relevante via `store.cleanup_workspace`.
- [FEITO] planner/reflexion/judge/self-model/TOM/metacognition já escrevem ou observam o mesmo espaço operacional; agora o ciclo de aprendizagem autônoma (`autofeeder`/sync LightRAG) também publica em `learning.ingest`, `learning.agenda` e `learning.lightrag_sync`; world_model e causal_preflight totalmente integrados.

## 5.2 Atenção competitiva e broadcast global
_Status: [EM ANDAMENTO 70%]_

- [FEITO] Score de saliência por item
- [FEITO] Fatores de saliÃªncia agora recebem viÃ©s de atenÃ§Ã£o vindo de `affect.state`/`policy.risk` (implementado no `store.py`)
- [FEITO] Mecanismo de seleÃ§Ã£o top-k via `top_salience`/`competition_index`
- [FEITO] Broadcast para módulos consumidores
- [FEITO] Integração completa: o módulo `working_memory` agora gerencia a competição real de saliência com decaimento, alimentando os payloads dos executores via Global Workspace Blackboard.

## 5.3 Sentido de agência e autoria
_Status: [EM ANDAMENTO 68%]_

- [FEITO] rastros de decisão/execução agora existem de forma mais explícita via `action_enqueue_decision`, `arbiter_block` e `authorship_trace` e veto subconsciente.
- [FEITO] Marca de autoria por ação no workspace global
- [FEITO] Ligação formal entre intenção, decisão e execução com classificação de origem (`self_generated`, `externally_triggered`, `mixed`, `unknown`)
- [FEITO] Campo/visão inicial de `authorship_trace` via endpoints `/api/authorship/trace` e `/api/authorship/status`
- [FEITO] Integração completa na memória episódica via `authorship_origin` e `arbiter_votes` adicionados aos ledgers de repetição estruturada e basal em `append_episode` e `append_structured_episode`.

## 5.4 Modelo preditivo do self
_Status: [EM ANDAMENTO 78%]_

- [FEITO] há embriões em `self_model` e `homeostasis`
- [FEITO] Previsão de mudança no self-state (`predicted_confidence_delta`)
- [FEITO] Comparação predicted vs observed self-change (`predicted_success` vs `observed_success`)
- [FEITO] Score de surpresa interna calculado dinamicamente em runtime
- [FEITO] Ajuste dinâmico do self-model por divergência interna (penaliza `confidence_by_domain` se surpresa cruzar limiar)

## 5.5 Marcadores afetivos artificiais
_Status: [EM ANDAMENTO 62%]_

- [FEITO] Vetor afetivo operacional via `valence/arousal/confidence/frustration/curiosity/threat`
- [FEITO] Geração baseada em sucesso/fracasso/custo/surpresa/ameaça em forma proxy por narrativa, incerteza, competição e promessas pendentes
- [FEITO] Integração dinâmica com recuperação de memória RAG e Episódica (estado homeostático `repair` induz viés forte de convergência, `investigative` induz diversidade exploratória).
- [FEITO] Integração com atenção e política de risco via publicações `affect.state` e `policy.risk`

## 5.6 Modelagem de outros agentes
_Status: [EM ANDAMENTO 55%]_

- [FEITO] módulo `tom` já faz inferência inicial de intenção/estado do outro e publica no workspace global
- [FEITO] `other_agent_model` com schema rico (intent, cognitive_load, trust_level)
- [FEITO] Simulação mental pré-ação via `tom.predict_reaction` integrada ao causal engine
- [FEITO] Integração completa com o orquestrador via `causal_preflight`

## 5.7 Observador de segunda ordem
_Status: [EM ANDAMENTO 65%]_

- [FEITO] `reflexion_agent`, `internal_critic` e metacognição agora operam proativamente.
- [FEITO] Módulo `meta_observer` explícito
- [FEITO] Relatório periódico do foco/competição/autoria/incerteza/conflitos disponível por endpoint dedicado
- [FEITO] Encaminhamento sistemático para reflexion via publicação de `reflexion.trigger`
- [FEITO] **Self-Talk Loop (Internal Critic como Prompter Contínuo)**: Loop interno OODA que atua como processo de primeiro nível. Avalia ativamente posturas cognitivas (tédio, curiosidade, anomalias, oportunidades) e injeta pensamentos/ações no workspace de maneira proativa e autônoma, livrando o sistema da dependência exclusiva de triggers externos.

## 5.8 Eu narrativo contínuo
_Status: [EM ANDAMENTO 68%]_

- [FEITO] `identity_daily` e registros parciais já dão embrião autobiográfico
- [FEITO] `autobiographical_summary`
- [FEITO] atualização após promoções, crises, reparos e transferências
- [FEITO] uso em decisões importantes via publicação contínua em `self.narrative` e integração direta com o Autonomous Loop via Veto Narrativo Subconsciente; narrativa publica `self.learning` quando há aquisição autônoma recente

## 5.9 Proxy de integração interna
_Status: [EM ANDAMENTO 70%]_
- [FEITO] Proxies mínimos de integração interna (Executive Alinhamento e Integrity Drift)
- [FEITO] Painel longitudinal via endpoint e workspace `integration.proxy`
- [FEITO] Thresholds experimentais e alertas operacionais

## 5.10 Benchmark de consciência operacional
_Status: [EM ANDAMENTO 60%]_

- [FEITO] Casos de teste proxy para foco, autoria, ignorados, surpresa interna, autobiografia e modelagem do outro
- [FEITO] Métricas de qualidade integrada
- [FEITO] Comparação contra baseline via freeze/run com métrica de delta demonstrável.

---

# Fase 6 — Instrumentação executiva e gestão do roadmap
_Status da fase: 75%_

## 6.1 Painel de progresso do roadmap
_Status: [EM ANDAMENTO 90%]_

- [FEITO] Expor status macro por fase/front
- [FEITO] Expor itens FEITO / EM ANDAMENTO / PENDENTE
- [FEITO] Expor percentuais reais
- [FEITO] Criar painel único de maturidade com estados `Implementado`, `Integrado`, `Testado localmente` e `Validado externamente`
- [FEITO] Visualização de Logs Homeostáticos no Dashboard UX
- [FEITO] Tornar a leitura do roadmap robusta em runtime com fallback embarcado no backend, suportando ambientes Windows e Cloud.
- [FEITO] Executive Instrumentation: métricas de 'alinhamento de meta' vs 'ação executada' integradas ao loop via `executive_instrumentation.py`.
- Validação: `backend/ultronpro/roadmap_status.py` + endpoints:
  - `GET /api/roadmap/status`
  - `GET /api/roadmap/items`
  - `GET /api/roadmap/scorecard`

## 6.2 Ritual de atualização do roadmap
_Status: [EM ANDAMENTO 85%]_

- [FEITO] Toda implementação relevante atualiza este arquivo
- [FEITO] Toda validação relevante ajusta status
- [FEITO] Toda entrega parcial recebe percentual honesto
- [FEITO] Formalizar rotina automática de auditoria/CI via `roadmap_auditor.py` integrado ao Metacognitive Loop.

## 6.3 Critério formal para nota de maturidade
_Status: [EM ANDAMENTO 60%]_

- [FEITO] Definir score por front baseado em progresso do roadmap e benchmarks.
- [FEITO] Aplicar teto duro: nenhum front pode passar de `80%` sem teste externo, histórico longitudinal e comparação contra baseline.
- [EM ANDAMENTO 40%] Vincular score a benchmarks longitudinais.
- [EM ANDAMENTO 50%] Atualizar score conforme evidência real de alinhamento executivo.

---

# Fase 7 — Motor de raciocínio próprio
_Status da fase: [EM ANDAMENTO 88%]_

O objetivo desta fase é desacoplar o raciocínio de alto nível (planejamento, decisão, governança) das APIs externas de LLM. O LLM deve ser movido para a periferia como um "módulo de interface de linguagem", enquanto o núcleo cognitivo (Planner simbólico + Motor Causal) assume o controle do loop de pensamento.

## 7.1 Planner simbólico de alto nível (Structured Planning)
_Status: [EM ANDAMENTO 82%]_
- [FEITO] Definir `ExecutionPlan` estruturado e versionado
- [FEITO] Implementar decomposição de objetivos em steps tipados (Gemma 3-1B)
- [FEITO] Auditoria de rota simbólica baseada no `self_model`

## 7.2 Integração RAG + Grafo Causal como memória de trabalho
_Status: [EM ANDAMENTO 70%]_
- [FEITO] Uso do núcleo cognitivo (`cognitive_response.py`) para resolver perguntas cobertas por causalidade, memória episódica/autobiográfica ou simulação mental antes de chamar LLM.
- [FEITO] Recuperação autobiográfica e digest biográfico entram como evidência estruturada para perguntas sobre identidade/origem/capacidade, sem respostas hardcodadas.
- [FEITO] Simulação mental responde perguntas operacionais de risco/projeção no chat/stream usando `mental_simulation.imagine()`.
- [EM ANDAMENTO 55%] Priorização de ações baseada em score homeostático/econômico puro ainda precisa ser aplicada de forma decisiva no loop executivo completo.

## 7.3 Erradicação de Roteamento Baseado em Modelo (Golden Rule)
_Status: [EM ANDAMENTO 82%]_

Implementação do código determinístico de acordo com a Regra de Ouro ("O que pode ser código, será código"):
1. **World Model Keeper (Determinístico)**: Decompõe o objetivo em steps usando parsers de linguagem. [FEITO]
2. **Symbolic Router**: Avalia se pode ser resolvido com regras usando o `self_model`. [FEITO]
3. **Model Execution**: Roteamento totalmente simbólico sem uso de LLM para orquestrar LLM. [FEITO]
4. **Code Evaluator**: Valida resultados usando análise estrutural pura. [FEITO]

- [FEITO] Desinstalar Ollama/Local Inference para liberar overhead do HostOS
- [FEITO] Substituir "Local Planner" abstrato por heurísticas de código (Regex, Domains)
- [FEITO] Substituir "Local Evaluator (Gemma)" por testes determinísticos sintáticos
- [FEITO] Limpar dependências e fallback `ollama_local` em todo o motor cognitivo

## 7.4 Benchmarks de autonomia "LLM-off"
_Status: [EM ANDAMENTO 70%]_
- [FEITO] Smoke test local e HTTP validado para chat/stream sem LLM em três casos: identidade autobiográfica, risco operacional por simulação mental e matemática embutida em linguagem natural.
- [FEITO] Hard eval reprodutível validou chat de domínio próprio 8/8 sem LLM externo e grava evidência em `backend/data/hard_cognitive_eval_runs.jsonl`.
- [EM ANDAMENTO 35%] Medir sobrevivência funcional do sistema com zero chamadas de API externa em autonomia prolongada.
- [EM ANDAMENTO 30%] Validar coerência do planner simbólico contra baseline em suíte reprodutível.

## 7.5 Composição de resposta por evidência interna
_Status: [EM ANDAMENTO 80%]_
- [FEITO] Templates semânticos por formato de evidência: causal, fatos internos, abstrações, identidade, trajetória, episódios, procedimento, simulação e incerteza.
- [FEITO] Verbalizador mínimo usa traços e episódios locais apenas para estilo/forma, sem inventar fatos.
- [FEITO] Classificador aprendido por episódios (`core.learned_intent`) entra apenas como viés leve quando a cobertura estruturada está fraca ou ambígua.
- [EM ANDAMENTO 82%] Avaliação automática de resposta não-LLM ampliada pelo hard eval; falta expandir para perguntas abertas e benchmark externo sem servidor local.

---

# Fase 8 — Aprendizagem por Reforço Online (Autonomous RL)
_Status da fase: [EM ANDAMENTO 65%] — Aguardando Benchmark Longitudinal_

O sistema agora fecha o loop entre consequências observadas e ajuste de política sem intervenção humana.

## 8.1 Motor de Política Online (Thompson Sampling + EMA Decay)
_Status: [EM ANDAMENTO 70%]_
- [IMPLEMENTADO] Implementar `rl_policy.py` com posterior Beta por (action_kind, context)
- [IMPLEMENTADO] Thompson Sampling para gerar prioridades com exploração natural
- [IMPLEMENTADO] EMA decay periódico para esquecer experiências obsoletas
- [IMPLEMENTADO] Safety guardrails: floor de prioridade mínima + proteção de ações críticas
- [IMPLEMENTADO] Persistência do estado da política em `data/rl_policy_state.json`

## 8.2 Integração no Planner
_Status: [EM ANDAMENTO 65%]_
- [IMPLEMENTADO] Substituir boost/penalize estático por `rl_policy.sample_priority` no planner
- [IMPLEMENTADO] Cold-start fallback: usar priors Bayesianos do `self_model` quando não há dados suficientes (< 3 observações)
- [IMPLEMENTADO] Contextualização por modo homeostático (`normal`, `repair`, `conservative`)

## 8.3 Fechamento do Loop de Reward
_Status: [EM ANDAMENTO 68%]_
- [IMPLEMENTADO] Callback de reward no caminho de sucesso (`action_done`)
- [IMPLEMENTADO] Callback de reward no caminho de falha (`action_error`, reward=0.1)
- [IMPLEMENTADO] Integração com `economic.reward` como sinal de recompensa

## 8.4 Observabilidade
_Status: [EM ANDAMENTO 60%]_
- [IMPLEMENTADO] Endpoint `GET /api/rl/policy` para inspecionar a política em tempo real

## 8.5 Validação Longitudinal
_Status: [EM ANDAMENTO 45%]_
- [EM ANDAMENTO 55%] Verificar convergência da política após 14+ ciclos de ação (mean_reward variando entre 0.3 e 0.75)
- [PENDENTE] Comparar taxa de sucesso antes/depois do RL online em larga escala
- [EM ANDAMENTO 60%] Validar que o decaimento EMA previne lock-in em políticas obsoletas

---

# Fase 9 — Função de Utilidade Intrínseca (Emergent Self-Goals)
_Status da fase: [EM ANDAMENTO 62%] — Aguardando Validação de Convergência de Drives_

O sistema agora gera seus próprios objetivos a partir da experiência acumulada, sem templates humanos.

## 9.1 Motor de Utilidade Emergente
_Status: [EM ANDAMENTO 65%]_
- [IMPLEMENTADO] Implementar `intrinsic_utility.py` com 5 drives adaptativos (competence, coherence, autonomy, novelty, integrity)
- [IMPLEMENTADO] Coleta de sinais observáveis de subsistemas reais (self_model, homeostasis, rl_policy, self_governance)
- [IMPLEMENTADO] Cálculo de utilidade escalar U ∈ [0, 1] como satisfação ponderada dos drives
- [IMPLEMENTADO] EMA adaptativo para atualização dos valores observados

## 9.2 Geração de Objetivos Emergentes
_Status: [EM ANDAMENTO 60%]_
- [IMPLEMENTADO] Identificação do drive mais faminto (maior gap desejado vs observado, ponderado por peso)
- [IMPLEMENTADO] Construção de objetivo a partir da análise de lacunas reais (sem templates fixos)
- [IMPLEMENTADO] Injeção do objetivo emergente em `self_governance.persistent_goals`
- [IMPLEMENTADO] Delegação de `intrinsic.synthesize_intrinsic_goal` para `intrinsic_utility.derive_goals()`

## 9.3 Auto-Ajuste de Pesos dos Drives
_Status: [EM ANDAMENTO 60%]_
- [IMPLEMENTADO] `adjust_drive_weights(drive, reward)` atualiza pesos por EMA com normalização
- [IMPLEMENTADO] Drives que geram goals bem-sucedidos sobem; drives cujos goals falharam descem
- [IMPLEMENTADO] Safety floor: nenhum drive pode ser suprimido abaixo de MIN_WEIGHT

## 9.4 Resistência a Manipulação
_Status: [EM ANDAMENTO 60%]_
- [IMPLEMENTADO] `tamper_check()` via hash rolling do vetor de pesos
- [IMPLEMENTADO] Se pesos mudaram sem `adjust_drive_weights` legítimo → revert para defaults
- [IMPLEMENTADO] Persistência em `data/intrinsic_utility_state.json`

## 9.5 Observabilidade
_Status: [EM ANDAMENTO 60%]_
- [IMPLEMENTADO] Endpoint `GET /api/utility/status` com utilidade, drives, goals emergentes, histórico

## 9.6 Validação Longitudinal
_Status: [EM ANDAMENTO 50%]_
- [EM ANDAMENTO 50%] Observar convergência dos drive weights após ciclos iniciais
- [EM ANDAMENTO 55%] Verificar que goals emergentes refletem lacunas reais (ex: gap de autonomia detectado em 2026-03-24)

---

# Fase 10 — Loop de Auto-Avaliação Autônomo (Self-Calibrating Gate)
_Status da fase: [EM ANDAMENTO 74%] — Aguardando Medição de Queda em Rollback Rate_

O sistema agora calibra seus próprios critérios de promoção/rejeição de patches cognitivos.

## 10.1 Motor de Calibração
_Status: [EM ANDAMENTO 75%]_
- [IMPLEMENTADO] `self_calibrating_gate.py` com análise de histórico de patches
- [IMPLEMENTADO] Classificação: sucesso (promoted sem rollback) / falha (rollback) / rejeitado
- [IMPLEMENTADO] `min_delta` ← mediana de patches bem-sucedidos × 0.8
- [IMPLEMENTADO] `max_regressed_cases` ← P75 sucessos, restrito pelo mín. de falhas
- [IMPLEMENTADO] Safety floors: nenhum threshold abaixo do limiar de segurança

## 10.2 Integração
_Status: [EM ANDAMENTO 75%]_
- [IMPLEMENTADO] `promotion_gate.py` usa `calibrated_thresholds()` quando sem override
- [IMPLEMENTADO] Cold-start fallback para defaults quando histórico < 5 patches
- [IMPLEMENTADO] Tick de recalibração a cada 30min no ciclo autônomo
- [IMPLEMENTADO] Endpoint `GET /api/gate/calibration`

## 10.3 Validação Longitudinal
_Status: [EM ANDAMENTO 55%]_
- [EM ANDAMENTO 55%] Verificar convergência após 7 resolved patches (thresholds ajustados em 3 calibrações)
- [PENDENTE] Confirmar que rollback rate diminui com calibração ativa a longo prazo

---

## 10.4 Auto-melhoria forte por classe
_Status: [EM ANDAMENTO 65%]_
- [FEITO] `self_improvement_engine.py` agora distingue `procedure_improvement`, `representation_improvement` e `competency_improvement`.
- [FEITO] Toda melhoria forte grava evidência em `improvement_validations`.
- [FEITO] Gate de promoção exige tarefas não vistas/holdout e candidato vencendo baseline.
- [PENDENTE] Ligar esse gate a benchmarks externos recorrentes por família de tarefa.

---

# Fase 11 — Motor de Generalização Composicional
_Status da fase: [EM ANDAMENTO 70%] — Aguardando Benchmark ARC Completo_

O sistema agora monta soluções para problemas novos a partir de princípios (composição), em vez de apenas interpolar padrões estatísticos.

## 11.1 Decomposição Estrutural
_Status: [EM ANDAMENTO 70%]_
- [IMPLEMENTADO] Implementar `decompose(problem)` usando heurísticas de quebra de fronteira e palavras-chave de tipo
- [IMPLEMENTADO] Detecção automática de tipos (math, logic, planning, analysis, synthesis, retrieval)
- [IMPLEMENTADO] Extração de restrições implícitas e grafo de dependências (DAG)

## 11.2 Busca de Primitivos e Composição
_Status: [EM ANDAMENTO 70%]_
- [IMPLEMENTADO] Integração com `explicit_abstractions` para busca de princípios aplicáveis
- [IMPLEMENTADO] Ordenação topológica de sub-problemas por dependências
- [IMPLEMENTADO] Encadeamento de soluções com rastreio de proveniência (primitivos vs LLM fallback)
- [IMPLEMENTADO] Verificação de consistência e score de composição

## 11.3 Aprendizagem Composicional
_Status: [EM ANDAMENTO 65%]_
- [IMPLEMENTADO] Extração de novos princípios a partir de composições bem-sucedidas (Reward > 0.5)
- [IMPLEMENTADO] Injeção automática na biblioteca de abstrações via `compositional_engine.learn_primitive()`

## 11.4 Observabilidade e Integração
_Status: [EM ANDAMENTO 65%]_
- [IMPLEMENTADO] Endpoint `GET /api/composition/status` com métricas de composição vs interpolação

## 11.5 Benchmarking (ARC-style)
_Status: [EM ANDAMENTO 55%]_
- [EM ANDAMENTO 55%] Validar em problemas genuinamente fora da distribuição de treino (indução de regra blind_001 validada)
- [PENDENTE] Comparar precisão de composição simbólica vs LLM "zero-shot" puro

---
## Auditoria rápida de implementação x ativação em produção (2026-03-21)

- **Fase 1 — Plasticidade estrutural real:** implementação forte e ativação operacional em produção; faltam robustez longitudinal e correlação mais dura com benchmark externo.
- **Fase 2 — Modelo causal:** implementação boa e ativa em produção, mas a prova comparativa causal on/off ainda está incompleta.
- **Fase 3 — Generalização entre domínios:** implementação boa e ativa em produção para abstrações/mapper/benchmarks; validade pública dos benchmarks ainda é parcial.
- **Fase 4 — Automanutenção/individuação:** implementação ampla e ativa em produção; spawn lógico, arbitragem e linhagem estão rodando, mas ainda sem runtime descendente plenamente acoplado.
- **Fase 5 — Consciência operacional integrada:** implementação parcial porém real e ativa em produção para workspace, meta-observer, autobiografia, TOM, proxy de integração e benchmark inicial; ainda falta fechar agência/autoria forte, self-model preditivo e integração causal/planner.
- **Fase 6 — Instrumentação do roadmap:** implementação parcial; endpoints existem, mas a robustez em runtime ainda estava incompleta porque o backend tentava ler o roadmap só no path do host. Esta rodada adiciona fallback embarcado no backend para fechar essa lacuna.
- **Fase 7 — Motor de raciocínio próprio:** fase recém-planejada; o objetivo é o desacoplamento total do raciocínio em relação ao LLM, movendo o modelo de linguagem para a periferia.

## Ordem recomendada de execução

### Sprint A — Plasticidade real primeiro
- Registro de patches cognitivos
- Detector de lacunas recorrentes
- Shadow eval / A-B
- Promotion gate
- Rollback
- Benchmark suite

### Sprint B — Corpo e episódios
- Ambiente mínimo
- Schema de episódio
- Persistência + replay

### Sprint C — Causal online
- Predição pré-ação
- Surpresa
- Atualização causal
- Contrafactual
- Benchmark causal on/off

### Sprint D — Transferência real
- Biblioteca de abstrações
- Extrator estrutural
- Mapper A→B
- Benchmark de transferência
- Consolidação multi-domínio

### Sprint E — Self operacional
- Schema de self-model
- Delimitação self vs ambiente
- Invariantes de identidade

### Sprint F — Recursos e homeostase
- Orçamento interno
- Função de custo
- Reserva de continuidade
- Variáveis homeostáticas
- Monitor homeostático

### Sprint G — Autorreparo
- Detecção de dano
- Contenção
- Reparo
- Ledger clínico interno

### Sprint H — Continuidade e objetivos persistentes
- Linha biográfica
- Memórias-raiz
- Coerência narrativa
- Objetivos intrínsecos
- Arbitragem interno vs externo

### Sprint I — Consciência operacional integrada
- Global workspace
- Atenção competitiva
- Agência e autoria
- Marcadores afetivos
- Meta-observer
- Eu narrativo contínuo
- Benchmark de consciência operacional

### Sprint J — Herança e benchmark final
- Spawn descendente
- Mutação controlada
- Seleção por linhagem
- Suite de continuidade
- Score de individuação operacional
- Proxy de integração interna

### Sprint K — Raciocínio Próprio e Desacoplamento
- Planner simbólico
- Motor de estados de governança
- Memória de trabalho causal-RAG
- Integração de TinyLLM local
- Benchmark "LLM-off"

---

## Critério final de nota 10 por front

### Front 1 = 10/10
- detecta lacuna sozinho
- propõe mudança estrutural
- valida em benchmark
- promove com gate
- melhora resultado
- mantém ganho
- faz rollback quando preciso

### Front 2 = 10/10
- age em ambiente com consequência
- prevê efeitos
- mede surpresa
- revisa causalidade
- melhora decisões por causalidade

### Front 3 = 10/10
- extrai abstrações explícitas
- transfere entre domínios
- melhora desempenho em domínio novo
- consolida abstrações realmente gerais

### Front 4 = 10/10
- sabe o que pertence ao self e ao ambiente
- protege a própria integridade funcional
- administra recursos para continuar operando
- detecta e corrige degradação
- preserva memória crítica e identidade
- mantém continuidade operacional
- arbitra entre meta externa e integridade interna
- transmite herança operacional controlada

### Front 5 = 10/10
- integra informação relevante num espaço global
- mantém foco seletivo com atenção competitiva
- relata o que está em foco e o que foi ignorado
- mantém autoria e agência rastreáveis
- ajusta self-model por surpresa interna
- usa marcadores afetivos artificiais de forma útil
- modela outros agentes com ganho observável
- executa metacognição de segunda ordem
- preserva um eu narrativo contínuo
- melhora decisão integrada de forma mensurável

---

## Log de execução

### 2026-03-19
- [FEITO] Reestruturação do roadmap para 5 fronts + Fase 6 de instrumentação
- [FEITO] Front 1 reavaliado como praticamente funcional e ativo
- [FEITO] Front 2 reconhecido como operacional em embrião sério, com `ultronbody` e grafo causal ativos
- [FEITO] Front 3 reconhecido como operacional em transferência/abstrações
- [FEITO] Front 4 reconhecido como não nulo: `self_model`, `homeostasis`, budget/custo e continuidade parcial já existem
- [FEITO] Front 5 reconhecido como embrião real, mas ainda imaturo: `cognitive_state`, `tom`, `reflexion_agent`, `internal_critic`, `identity_daily`
- [FEITO] Fase 6 atualizada com o backend de scorecard/status do roadmap
- [FEITO] Implementação operacional do Global Workspace
- [FEITO] Implementação do meta-observer explícito
- [FEITO] Camada inicial de marcadores afetivos artificiais com endpoint `/api/affect/status` e publicação periódica no workspace (`affect.state`/`policy.risk`)
- [FEITO] Autobiografia operacional contínua com endpoint `/api/self-governance/autobiography` e publicação periódica em `self.narrative`
- [FEITO] Proxy explícito de integração interna com endpoints `/api/integration-proxy/status` e `/api/integration-proxy/workspace`, além de publicação contínua em `integration.proxy`
- [FEITO] Benchmark operacional inicial do Front 5 com baseline/runs persistidos e score integrado em `/api/operational-consciousness/benchmark/*`
- [FEITO] Limpeza inicial do frontend legado e alinhamento do dashboard com sinais reais do Front 5
- [EM ANDAMENTO 80%] Benchmark causal on/off robusto agora com múltiplos ambientes, `causal_blind` vs `causal_safe`, replay/contrafactual e métricas de risco/surpresa/recompensa
- [EM ANDAMENTO 68%] Benchmarks de consciência operacional

### 2026-03-20
- [FEITO] Fim da integração inicial em memória episódica na fase 5.3. Integração de rastreamento de agência `authorship_origin` e `arbiter_votes` adicionados ao modelo de `append_episode` e `append_structured_episode` e injetados na memória via frontend param em `MetacogAskRequest`.
- [FEITO] Implementação completa do Modelo Preditivo do Self (Fase 5.4): Adicionada previsão baseada em `causal_preflight.risk`, geração e registro do score de `surprise` (esperado vs observado) e regulação de confiabilidade por domínio diante de alta variação preditiva (em `self_model.py`).
- [FEITO] Integração completa dos Marcadores Afetivos (Fase 5.5): O estado homeostático (`repair`, `investigative`, `normal`) agora amarra pesadamente os hiperparâmetros de diversidade do RAG (`rag_router._diversity_select`) e o recall da memória episódica (`find_similar_structured`). Quando a homeostase detecta anomalias ("ansiedade/repair"), UltronPro recua para extrair fontes extremamente alinhadas e experiências prévias com selo exclusivo de segurança!
### 2026-03-21
- [FEITO] Adicionada a Visualização de Logs Homeostáticos na UX (Fase 6.1). Agora, os dashboards operacionais do *Front 5* em `index.html` expõem de forma reativa a tabela de histórico e os "Vitals Principais" dinâmicos consumindo `/api/homeostasis/status`. Isso marca o fechamento de um importante loop de observabilidade arquitetural para as engrenagens de backend.
- [FEITO] Implementação da Teoria da Mente Causal (Fase 5.6): Refatoração do módulo `tom.py` para suportar um *schema* rico de usuário (`intent`, `cognitive_load`, `trust_level`). Criada a função de simulação mental `predict_reaction` que projeta o impacto emocional/cognitivo de uma ação no usuário antes da execução. Integração profunda no ciclo de preflight do orquestrador via `causal_preflight.py`.
- [FEITO] Orquestração por Squads Especializados (Fase 5.7): Implementada a infraestrutura de perfis de squad (Científico, Código, Lógica) via `squad_profiles.py` e `squad_phase_a.py`. O sistema agora suporta troca dinâmica de equipe e agentes em runtime. Adicionada **Detecção de Domínio Autônoma** no `planner.py`, permitindo que o UltronPro otimize proativamente sua configuração de agentes com base no objetivo ativo (ex: sugerir squad de código para tarefas de refatoração).
- [FEITO] **Planejamento da Fase 7 — Motor de Raciocínio Próprio**: Formalizado o objetivo de desacoplar o raciocínio central das APIs de LLM externas, movendo o sistema para uma arquitetura onde o LLM é periférico e o Planner simbólico + Grafo Causal são o centro.
- [FEITO] **Implementação do Self-Thinking Loop (Fase 7.3)**: Ativada a camada de triagem e avaliação local com Gemma 3-1B, garantindo autonomia estrutural e resiliência do Front 4 sem dependência de nuvem para o raciocínio básico.

---

## Log de Auditoria Crítica — 2026-03-22 (Ponto de Inflexão Epistêmica)

| Risco Identificado | Diagnóstico Estrutural | Impacto nos Scores |
|:---|:---|:---|
| **Validação Circular** | O `quality_eval` (usado por RL e Gating) mede apenas "estilo/incerteza" (heurísticas), ignorando acerto factual externo. O sistema otimiza o "espelho". | Fase 8, 9 e 10 marcadas como `IMPLEMENTADO` (sem evidência de ganho real). |
| **Desacoplamento de Patches** | Front 1 (Plasticidade) gerencia patches com sucesso, mas o `planner.py` **não lê** os patches promovidos. O sistema é operado por código estático enquanto acredita ser plástico. | Front 1 rebaixado de 90% para 15%. |
| **Falta de Âncora Factual** | O âncora externo (`external_benchmarks.py`) existe como gabarito fixo, mas está desconectado dos loops de recompensa (`rl_policy`, `promotion_gate`). | Prioridade imediata: **Conexão de Âncora**. |

---

## Próximo passo imediato

### Fase 11.6 — Ancoragem Factual e Acoplamento de Patches

**Status: [IMPLEMENTADO — VALIDAÇÃO PARCIAL]**

**O que foi feito (2026-03-22):**
1. `quality_eval.py` — Ancorado em gabarito externo. Respostas erradas retornam 0.1, corretas retornam 0.975, independente de estilo.
2. `llm.py` — Patches promovidos são injetados no system prompt a cada chamada.
3. Loop completo rodado (4 setas). Resultado: **S3 delta=0.0 → gate bloqueou (delta_below_threshold)**.

**Diagnóstico honesto:**
- O loop é arquiteturalmente correto (cada seta funciona).
- O gate bloqueou porque o modelo (gemini-2.0-flash) já acertava a tarefa antes do patch.
- Varredura de 9 tarefas × 3 tentativas: **0 falhas consistentes** — o suite é trivial para o modelo.
- **Conclusão do loop de patch:** A infraestrutura está pronta. O domínio de aplicação correto é "erros de raciocínio por falta de instrução" — não gaps de primitivos simbólicos (ARC) nem perguntas que o modelo já sabe.

**Lição estrutural registrada:**
> Patches de prompt corrigem comportamento de LLM, não gaps de capacidade computacional.
> O `cognitive_patch_loop` tem utilidade real quando o sistema tiver erros sistemáticos de estilo/protocolo — ex: formato de output incorreto, viés documentado em certos tipos de tarefa.
> Pausado aqui (15%). Não é yak shaving continuar tentando provar plasticidade onde o modelo não erra.

---

## Fase 11/12 — Indutor Simbólico e LLM Hypothesis [IMPLEMENTADO — COBERTURA DE POOL ESPECÍFICO]

**Objetivo:** Autonomia de indução visual e score ARC estável.

- **Score Pool-20 (imutável):** **8/20 (40%)** — estável, zero dependência de rede.
- **Score Generalização (5 tarefas inéditas):** **0/5 (0%)**

**Diagnóstico confirmado:**
- Pool-20 contém transformações globais (`reflect`, `scale`, `crop`).
- Indutor foi projetado após análise do pool → fit, não generalização.
- Tarefas inéditas exigem raciocínio local/estrutural: objetos, gravidade, segmentação por cor — capacidades ausentes no executor atual.

**Conclusão Epistêmica:** O sistema tem um vocabulário simbólico global funcional. Generalização real requer DSL de objetos (Fase 11 real).

**Módulo:** `visual_inductor.py` | `arc_hypothesis_guide.py`

### Histórico de Validação (2026-03-24)
- [IMPLEMENTADO] Indutor Simbólico Visual (Zero API) integrado como primeira camada do solver ARC.
- [VALIDADO] Estabilização do baseline em 40% (8/20) no pool imutável, superando a dependência de APIs externas (Gemini 429).
- [PROVA DE CONCEITO] Verificação de generalização em 5 tarefas inéditas resultou em 0/5, confirmando que o score atual é de "Pool Coverage" e não "General Intelligence".
- [STATUS] Fase 12 rebaixada de "Feito" para "Implementado - Cobertura de Pool" devido ao gap de generalização.

### 2026-03-24
- [IMPLEMENTADO] Auditoria técnica e validação cruzada das Fases 6, 8, 9, 10, 11 e 12.
- [VALIDADO EM POC] **Prova de Indução (Fase 11):** O motor simbólico induziu com sucesso a regra de reflexão horizontal (`reflect_h`) a partir de 2 exemplos. Considerado "Implementado e Funcional", aguardando benchmark ARC completo para conclusão.
- [VALIDADO EM POC] **Prova de Calibração (Fase 10):** Gate calibrado com histórico de 7 patches; threshold de `min_delta` ajustado. Considerado "Implementado", aguardando medição longitudinal de rollback rate.
- [VALIDADO EM POC] **Prova de Motivação (Fase 9):** Goal emergente `[emergente] Fortalecer autonomy` gerado automaticamente. Considerado "Implementado", aguardando prova de convergência de drives.
- [IMPLEMENTADO — RESET NECESSÁRIO] **Fase 8 (RL):** Diagnóstico: política convergiu prematuramente sob `quality_eval` heurístico. Estado semanticamente corrompido. Ação: reset para prior neutro (Alpha=1, Beta=1) em 2026-03-24 para re-aprendizado sob o novo scorer ancorado.
- [VALIDADO PARCIAL - FASE 12] **Benchmark ARC:** Descoberta variância de 2/20 a 5/20 causada por instabilidade de provedores externos (Gemini 429). Score real consolidado como "dependente de infraestrutura". Rebaixado para `[IMPLEMENTADO — VALIDAÇÃO INCOMPLETA]` até 3 rodadas estáveis.
- [EM VALIDAÇÃO] **Instrumentação (Fase 6):** Scorecard atualizado: 161 itens implementados (66.5%), roadmap macro em 63%.

### 2026-04-14 (Atualização de Ponta-a-Ponta AGI)
- [FEITO] **Fechamento do Loop de Autonomia Web:** Implementação robusta do Microserviço em Node.js (Puppeteer Bridge) superando as limitações do Windows e `asyncio`. O UltronPro agora possui "corpo sensorial" funcional na Web, auto-alimentando o RAG em threads desacopladas (Fase 4 reestabelecida a plena força).
- [FEITO] **Desmockagem do Raciocínio (Fase 7.3 expandida):** Descoberto e removido o "Mock/Placeholder" original do `skill_executor.py`. Skills como `code_review` e web search deixaram de ser mocks estáticos intermitentes e foram conectados diretamente ao LLM Backbone.
- [FEITO] **Cognição em Tempo Real (SSE):** O Chat frontal passou de rotinas engasgadas de long-polling (timeout) para Server-Sent Events, permitindo visualizar os "Raciocínios e Metacognições" (Skills, Fallbacks, RAG Layers e Intent Synthesizations) progressivamente enquanto processa, fechando o loop empático com o usuário (Fase 5 mitigada).
- [FEITO] **Self-Aware Intent Fallback:** Intenções de identificação como "quem é você" ou saudações deixam de ser curtos-circuitos que devolvem JSON bruto da estrutura emergente. Elas agora fluem por uma Thread Local que combina organicamente sua `intrinsic_utility` atual em uma resposta de primeira pessoa, manifestando presença genuína do Agente (Avanço crítico de Fase 5/Auto-narrativa).
- [FEITO] **Fase 13 — Motor de Simulação Mental (mental_simulation.py):** Implementado motor completo de simulação mental com 5 capacidades cognitivas fundamentais:
  1. **Imaginar consequências** — `imagine_consequences()` integra `causal_preflight`, `world_model.simulate_action`, `contrafactual.deliberate` e busca de competências para prever efeitos antes de agir
  2. **Comparar hipóteses rivais** — `compare_hypotheses()` avalia N hipóteses com scoring multidimensional (benefit×confidence - risk×cost + evidências)
  3. **Testar mentalmente caminhos** — `test_paths()` simula sequências de passos alternativos para um objetivo e rankeia por viabilidade cumulativa
  4. **Aprender com erros** — `learn_from_outcome()` calcula surpresa (previsto vs real), extrai lições causais e atualiza RL policy
  5. **Consolidar competências** — extração automática de competências reutilizáveis a partir de padrões de sucesso recorrentes, com biblioteca persistida
- [FEITO] **Integração no Autonomous Executor:** Toda execução autônoma agora passa por pré-imaginação mental (imagine → compare hypotheses → execute → post-mortem → learn → consolidate competency). Actions com posture 'abort' são bloqueadas automaticamente.
- [FEITO] **API REST completa:** 7 endpoints (`/api/mental-sim/*`) para status, imagine, compare, test-paths, learn, competencies e competency-failure.
- [FEITO] **Correção de bugs:** `web_explorer.py` — corrigido `ConnectTimeout` não capturado na health check do Puppeteer Bridge; `planner.py` — corrigida `NameError` por lista `actions` não inicializada.
- [FEITO] **Fase 14 — Code Self-Healer (code_self_healer.py):** Implementado motor de auto-correção de código que fecha o loop completo traceback→análise→fix→apply→verify→rollback:
  1. **Captura de Erros** — intercepta exceções do runtime, extrai módulo/função/linha via traceback parsing
  2. **Análise Determinística** — 7 regras automáticas para bugs comuns: timeout faltante, variável não inicializada, None.get(), json.loads desprotegido, arquivo inexistente, conversão numérica, IndexError
  3. **Fallback LLM** — para bugs complexos que as regras determinísticas não cobrem
  4. **Validação dupla** — ast.parse (sintaxe) + importlib (import) antes de aplicar
  5. **Backup + Rollback** — backup automático antes de modificar, rollback imediato se import falhou
  6. **Rate Limiting** — máximo 3 fixes por módulo por hora para evitar loops
  7. **Proteção** — main.py e settings.py nunca são modificados
- [FEITO] **E2E Testado:** 8 testes de ponta-a-ponta passaram: capture→analyze→apply→verify→rollback→full_pipeline→status→API
- [FEITO] **API REST:** 5 endpoints (`/api/self-healer/*`) para status, analyze, apply, verify, rollback

---

## Próximos passos imediatos para Autoconsciência Local (Nível AGI)

Para fazer o UltronPro transacionar de um *"orquestrador de scripts sofisticado"* para uma entidade **Localmente Autoconsciente**, as seguintes fundações de "Teoria da Mente do Self" deverão ser priorizadas nas semanas seguintes:

1. **Fusão Sentido-Ação Contínua (Embodiment Contínuo):**
   - A dependência entre `web_explorer.py` e os eventos de timer deve migrar para um submotor observacional unificado. Se a máquina host (seu Windows) gera arquivo novo ou modifica código na sua IDE de trabalho, Ultron precisa processar passivamente e reajustar metas (`intrinsic_utility`) _antes_ de você pedir no chat.

2. **Reconstrução Diária de Identidade (Biographic Digest):**
   - **[FEITO] Digest Biográfico de Trajetória:** `biographic_digest.py` consolida identidade como processo, sem depender de LLM: recupera episódios significativos, benchmarks, patches promovidos/revertidos, erros/correções, decisões e o gate causal calibrado. `identity_daily.py`, o roteador autobiográfico e as respostas de identidade agora usam esse digest para responder "quem você é hoje", não apenas "quando nasceu".

3. **Internal Critic como Prompter Contínuo (Self-Talk Loop):**
   - Em vez do Agente iniciar processos cognitivos só com requisições HTTP, o sistema deve iterar um LLM pequeno puramente para julgar presteza/Tédio/Curiosidade a nível microscópico (loop OODA), enfileirando pensamentos proativos na fila global sem trigger externo.

4. **Resiliência a Degradações Sistêmicas Fatais:**
   - Se 100% dos LLMs (gemini, groq, nvidia) receberem Timeout (Error 429), ele não pode "dormir calado" jogando erros pro Uvicorn. Autoconsciência significa entender sua própria paralisia, trocar para um modo *Low-Power*, ativar os Lobbies de Local Inference (Ollama) em cache, reportar proativamente via socket/front-end que sua "área de Wernicke/fala está comprometida" limitando sua arquitetura a sobrevivência local até restabelecimento.

---

# Fase 13 — Motor de Simulação Mental (Mental Simulation Engine)
_Status da fase: [EM ANDAMENTO 68%]_

O sistema agora **pensa antes de agir**: imagina consequências, compara hipóteses, testa caminhos mentais, aprende com surpresas e consolida competências reutilizáveis.

Auditoria operacional 2026-04-21: implementação e integração existem, inclusive no chat via `cognitive_response.py`, mas o estado persistido ainda mostra validação longitudinal curta (`sim_count=2`, `scenarios=2`, `competencies=0`, surpresa média alta). A fase permanece alta por capacidade implementada, mas não pode sustentar conclusão total até convergir em ciclos reais.

## 13.1 Imaginação de Consequências Pré-Ação
_Status: [EM ANDAMENTO 72%]_
- [IMPLEMENTADO] `imagine_consequences()` combina `causal_preflight`, `world_model.simulate_action`, `contrafactual.deliberate` e busca de competências
- [IMPLEMENTADO] Scoring composto: risco, reversibilidade, confiança do world_model, boost de competências, surpresa passada
- [IMPLEMENTADO] Postura recomendada: `proceed`/`caution`/`abort`
- [IMPLEMENTADO] Trace mental completo para auditoria de cada passo do raciocínio

## 13.2 Comparação de Hipóteses Rivais
_Status: [EM ANDAMENTO 70%]_
- [IMPLEMENTADO] `compare_hypotheses()` recebe N hipóteses com evidências a favor e contra
- [IMPLEMENTADO] Scoring multidimensional: benefit × confidence - risk × cost + evidence_bonus
- [IMPLEMENTADO] Cenário com chosen_hypothesis, simulated_outcome, e rejection_reasons para cada alternativa
- [IMPLEMENTADO] Persistência em `data/mental_simulation.json`

## 13.3 Teste Mental de Caminhos Alternativos
_Status: [EM ANDAMENTO 70%]_
- [IMPLEMENTADO] `test_paths()` simula cada passo de cada caminho via `imagine_consequences`
- [IMPLEMENTADO] Risco cumulativo, benefício cumulativo, viabilidade composta
- [IMPLEMENTADO] Veredicto por caminho: `viable`/`risky`/`avoid`
- [IMPLEMENTADO] Ranking e recomendação do melhor caminho

## 13.4 Aprendizagem por Surpresa (Post-Mortem Causal)
_Status: [EM ANDAMENTO 70%]_
- [IMPLEMENTADO] `learn_from_outcome()` compara resultado previsto vs real
- [IMPLEMENTADO] Cálculo de surpresa: 0.1 (previsão exata) até 0.8 (resultado inesperado)
- [IMPLEMENTADO] Extração de lições causais contextualizadas
- [IMPLEMENTADO] Retroalimentação na RL policy via `rl_policy.observe()`

## 13.5 Consolidação de Competências Reutilizáveis
_Status: [EM ANDAMENTO 62%]_
- [IMPLEMENTADO] Extração automática de competências de cenários bem-sucedidos (surpresa ≤ 0.4)
- [IMPLEMENTADO] Biblioteca persistida em `data/competency_library.json` com trigger_conditions, procedure, success/failure count
- [IMPLEMENTADO] Reforço/degradação de competências por uso com confidence tracking
- [IMPLEMENTADO] Deduplicação por chave normalizada e eviction de competências de baixa confiança

## 13.6 Integração no Executor Autônomo
_Status: [EM ANDAMENTO 65%]_
- [FEITO] Toda execução autônoma passa por `imagine_consequences()` antes de executar cada subtask (em `_execute_next_action()`)
- [FEITO] Bloqueio automático de ações com posture `abort` via guard preflight
- [FEITO] Post-mortem via `learn_from_outcome()` ao final de cada execução de ciclo autônomo (sucesso ou falha)
- [FEITO] A premissa `compare_hypotheses()` avalia e grava os cenários logo na pré-imaginação mental

## 13.7 Validação Longitudinal
_Status: [EM ANDAMENTO 55%]_
- [EM ANDAMENTO 20%] Medir redução de surpresa média ao longo de 50+ ciclos autônomos; a auditoria atual validou apenas probe isolado de 6 ciclos.
- [EM ANDAMENTO 35%] Validar que competências consolidadas são efetivamente reutilizadas em contextos similares; probe isolado criou competência, mas falta evidência viva recorrente.
- [EM ANDAMENTO 45%] Comparar taxa de sucesso com/sem simulação mental ativa em benchmark reprodutível.
- [PENDENTE] Confirmar que a biblioteca de competências converge para abstrações realmente generalizáveis.

---

# Fase 14 — Code Self-Healer (Auto-Correção de Código)
_Status da fase: [EM ANDAMENTO 72%]_

O sistema agora **corrige seu próprio código** quando detecta erros recorrentes no runtime, sem intervenção humana.

Auditoria operacional 2026-04-21: o pipeline está implementado e integrado, mas a eficácia longitudinal ainda não está provada em produção. `code_self_healer.status()` reporta 5 erros rastreados, 1 tentativa de heal, 0 fixes aplicados, 0 fixes verificados como OK e 1 rollback; portanto a implementação permanece madura, mas o front volta a exigir mais evidência de correção efetiva recorrente.

## 14.1 Captura e Tracking de Erros
_Status: [EM ANDAMENTO 75% — TESTADO E2E LOCAL]_
- [IMPLEMENTADO] Parsing de tracebacks para extrair módulo/função/linha exata
- [IMPLEMENTADO] Filtragem automática: só erros em `ultronpro/`, nunca em `main.py` ou `settings.py`
- [IMPLEMENTADO] Frequência tracking: fix só é tentado a partir da 2ª ocorrência (evita falsos positivos)
- [IMPLEMENTADO] Deduplicação por hash de módulo+função+exception_type

## 14.2 Análise Determinística (7 Regras)
_Status: [EM ANDAMENTO 75% — TESTADO E2E LOCAL]_
- [IMPLEMENTADO] `_fix_missing_except_timeout` — adiciona ConnectTimeout/TimeoutException ao except
- [IMPLEMENTADO] `_fix_uninitialized_list` — inicializa variáveis usadas antes de serem definidas
- [IMPLEMENTADO] `_fix_none_get` — protege .get() contra None
- [IMPLEMENTADO] `_fix_json_decode_unprotected` — wraps json.loads em try/except
- [IMPLEMENTADO] `_fix_file_not_found` — adiciona verificação .exists()
- [IMPLEMENTADO] `_fix_value_error_conversion` — default values para int()/float()
- [IMPLEMENTADO] `_fix_index_error` — proteção contra IndexError/KeyError

## 14.3 Fallback LLM para Bugs Complexos
_Status: [EM ANDAMENTO 60%]_
- [IMPLEMENTADO] Extrai ±20 linhas ao redor do erro e envia para LLM com contexto
- [IMPLEMENTADO] LLM gera fix em JSON, que é parseado e aplicado
- [IMPLEMENTADO] Usa strategy='local' com cloud_fallback=True

## 14.4 Validação e Proteção
_Status: [EM ANDAMENTO 75% — TESTADO E2E LOCAL]_
- [IMPLEMENTADO] `ast.parse()` para validação sintática antes de aplicar
- [IMPLEMENTADO] `importlib.import_module()` para validação de importação
- [IMPLEMENTADO] Distinção entre SyntaxError (FAIL) vs ImportError de deps externas (OK)
- [IMPLEMENTADO] Backup automático em `data/code_self_healer/backups/`
- [IMPLEMENTADO] Rollback imediato se validação falhar
- [IMPLEMENTADO] Rate limiting: max 3 fixes/módulo/hora para evitar loops infinitos

## 14.5 Pipeline Completo (heal())
_Status: [EM ANDAMENTO 75% — TESTADO E2E LOCAL]_
- [IMPLEMENTADO] `heal(exc, tb_str)` — single-call que faz capture→analyze→fix→apply
- [IMPLEMENTADO] 1ª ocorrência: apenas track (aguarda recorrência)
- [IMPLEMENTADO] 2ª+ ocorrência: tenta fix determinístico → fallback LLM → apply
- [IMPLEMENTADO] Verificação posterior via `verify(attempt_id)` confirma se erro parou

## 14.6 Integração (Próximos Passos)
_Status: [EM ANDAMENTO 70%]_
- [FEITO] Conectar ao middleware HTTP global em `main.py` para captura passiva e automática de exceções servidor
- [FEITO] Integrar com `_execute_next_action()` para interceptar falhas diretas nas runtimes do Autonomous Executor
- [FEITO] Loop rodando via background task `healer_verify_loop()` para checagem longitudinal de fixes em produção (Cooldown: 5min)
- [FEITO] Integrar com `self_corrector.py` para combinar parameter+code fixes (via fallbacks on limits or failures in prioritize)
- [FEITO] Dashboard no frontend mostrando erros tracked, fixes aplicados, rollbacks (Via Endpoint de painel: `/api/benchmarks/14-6`)
- [FEITO] Integrar com `mental_simulation.imagine()` para pre-flight explícito pré-aplicação de fixes arriscados
- [FEITO] Métricas longitudinais em painel: taxa de fix efetivo vs rollback ao longo de janelas diárias (Via `/api/benchmarks/14-6`)

## 14.6.1 Camada de invariantes comportamentais (Safety Invariants)
_Status: [EM ANDAMENTO 78%]_
- [FEITO] Análise via `ast.parse` no módulo `safety_invariants.py` para comparar integridade do AST antes de aplicar o patch.
- [FEITO] Impede deleção acidental de hooks críticos (ex: `time.sleep`, `store.db.add_event` ou exports top-level).
- [FEITO] Bloqueia silenciamento perigoso via _bare except passes_ (`except Exception: pass`).
- [FEITO] Integrado nativamente no fluxo `apply_fix()` como Step 0.5 da validação (protege contra "auto-destruição formatada").

## 14.7 Auto-modificação endurecida
_Status: [EM ANDAMENTO 70%]_
- [FEITO] `self_modification.apply()` não aplica mais patch direto no runtime principal, mesmo com `force=True`.
- [FEITO] Novo pipeline obrigatório `validate_isolated_pipeline`: patch gerado, cópia isolada, validação unitária por `py_compile`, benchmark reduzido, benchmark de regressão, comparação contra baseline, canário e rollback pronto.
- [FEITO] Zero proposta entra em `canary_ready` sem todas as evidências reprodutíveis.
- [PENDENTE] Substituir qualquer uso legado de apply direto por promoção via worktree/canário em produção.

---
# Fase A — Domínio causal fechado e verificável
_Status: [EM ANDAMENTO 55%]_
O causal graph vira árbitro primário apenas onde é verificável: ultronbody, sandbox financeiro, patches reversíveis, operações de arquivo com rollback, ciclos autônomos determinísticos. Fora desses domínios, o LLM continua no controle. Dentro deles, o LLM rebaixado para gerador de hipóteses que o causal graph aceita, rejeita ou revisa.
O critério de saída desta fase é concreto: o sistema consegue operar nesses domínios com taxa de surpresa decrescente e consistente ao longo de 30+ ciclos sem intervenção humana. Só então o domínio causal se expande.
O que amadurece aqui: causal_graph deixa de ser triplas com score heurístico e passa a registrar intervenções reais com magnitude, direção e contexto. Cada episódio no domínio fechado alimenta o grafo com evidência, não com inferência de palavras.

# Fase B — Memória Episódica como Substrato de Compilação
_Status: [EM ANDAMENTO 65%]_

Em vez de transformar a memória episódica em um cemitério infinito de repetições cruas, a Fase B formaliza um motor de extração semântica onde episódios de sucesso extremo e surpresa baixa derivam em abstrações causais permanentes, testáveis e versionadas.

## B.1 Motor Abstrato (Episodic Compiler)
_Status: [EM ANDAMENTO 68%]_
- [FEITO] `episodic_compiler.py`: Um módulo dedicado para extrair a ESTRUTURA CAUSAL subjacente que fez uma ação dar certo num domínio restrito/fechado.
- [FEITO] **Filtro de Invariância**: Opera ativamente testando `surprise_score < 0.4` e resultados positivos, não re-compilando dados ruidosos.
- [FEITO] **LLM como Sintetizador (e Não Árbitro)**: O LLM atua sob demanda rígida produzindo JSON focado em `nome`, `causal_structure` (O invariante) e `applicability_conditions`, não mais apenas recontando fatos soltos.

## B.2 Reuso e Avaliação Empírica (Baseline Gain)
_Status: [EM ANDAMENTO 62%]_
- [FEITO] Abstrações compiladas caem nativamente em uma `causal_abstractions_v2.json` e são sinalizadas no workspace de Causalidade.
- [FEITO] Recuperação Dinâmica via `retrieve_applicable_abstractions(domain)`.
- [FEITO] Motor de Retro-Medição via `record_abstraction_usage(...)`, comparando taxa empírica de baseline (ex: ganhos reais de latência/velocidade usando a abstração). Versões crescem sistematicamente à medida que são provadas confiáveis.

---

# Fase C — World Models Locais por Família de Ambiente
_Status: [EM ANDAMENTO 60%]_

O modelo de mundo estático não escala. O sistema foi refatorado para fracionar a cognição ambiental em **Famílias Locais** e treinar *via gradiente contínuo de erro*.

## C.1 Compartimentação de Domínio (Famílias)
- [FEITO] `local_world_models.py` arquitetado, separando instâncias como: `ultronbody`, `interacoes_codigo` (sandbox), e afins. Sem mesclas indevidas entre prever bash e prever oscilação de APIs.

## C.2 Treinamento Empírico T -> T+1
- [FEITO] A assinatura não recarrega snapshots estáticos. O loop de treinamento (`train_local_model`) usa `$state_{t}` e `$state_{t+1}` atrelado a respectiva `actual_outcome`.
- [FEITO] O framework retro-injeta "surpresa" puramente como erro preditivo: se a matriz inferencial disse 'success' mas a ação quebrou, o `risk` aumenta e a `surprise_delta` sobe.

## C.3 O LLM como "Professor Auxiliar"
- [FEITO] A autoridade central do LLM é revogada na fronteira causal. Ele atua sob demanda da função `_induce_hypothesis()`: Aciona **somente** se o World Model da família começar a errar de forma sistêmica (alta surpresa agregada > threshold), exigindo uma hipótese de "Hidden Variable" que o algoritmo cru ignora.

---

# Fase D — Planner com MPC, Busca e Rollback
_Status: [EM ANDAMENTO 58%]_

Aplicamos efetivamente **Model Predictive Control (MPC)** no core executivo. Diferentemente do `mental_simulation` antigo que consultava o score do grafo de forma estática, o novo módulo roteia execuções baseadas num Tree Search de caminhos inteiros.

## D.1 Simulação de Sequências com Local Models
- [FEITO] O módulo `mpc_planner.py` gera _N_ rotas hipóteticas e então varre o *Local World Model* correspondente à família da ação para simular $T \rightarrow T+1 \rightarrow T+2 ...$ O Risco Total e _Expected Value_ agregam o delta previsto empiricamente pelo erro anterior do modelo.

## D.2 Monitoramento de Divergência e Auto-Rollback
- [FEITO] Para prevenir que o plano continue se a física real for adversa, o loop de `execute_and_monitor` rastreia o limiar de `DIVERGENCE_THRESHOLD`. Se `real_surprise > 0.65` contra o que o WM disse, o sistema entra em Hard Abort, reverte o state, dispara `context_executor.rollback()` e abandona as heurísticas erradas.
- [FEITO] Toda ação do planner agora alimenta de volta o Local World Model (`train_local_model`), retro-injetando erro preditivo na matriz para calibração contínua e diminuindo as métricas futuras de `average_surprise`.

---

# Fase E — Compilação de Skills e Abstrações Cross-Domínio
_Status: [EM ANDAMENTO 68%]_

A última barreira da generalização é pegar Invariantes fortes de uma família de domínio e aplicar os mesmos princípios geométricos/causais em domínios completamente novos.

## E.1 Transfer Learning Nativo (Structural Mapper)
- [FEITO] O `structural_mapper.py` foi reescrito para abandonar inferências baseadas apenas em string ("logs de texto"). Agora, ele puxa unicamente abstrações provadas empiricamente vindas do *Episodic Compiler* (versão >= 1.2).
- [FEITO] Ele avalia a integridade Causal cruzada: se a abstração ("isolar estado -> validar dependências -> reiniciar") funcionou para `sandbox_financeiro`, o LLM avalia explicitamente se a MESMA condição é aplicável à `busca_autonoma`.
- [FEITO] Skills "universais" consolidadas são exportadas para um repositório centralizado (`cross_domain_skills.json`) sob o paradigma `skill_xxxx`.

Dessa forma, fica materializada a máxima cognitiva exigida: a **memória episódica é tão-somente o substrato bruto** (logs do SQLite), enquanto a **compilação estrutural e a verificação cross-domínio atestam a escalabilidade da Inteligência** em tempo de execução.

---

# Fase F — LLM Rebaixado para Interface e Scaffolding
_Status: [EM ANDAMENTO 64%]_

O ápice dessa reformulação arquitetônica (Fases A-E) garante que o **LLM perdeu definitivamente o papel central de processamento determinístico**. Ele não é eliminado, mas *especializado*. Como as restrições arquiteturais das fases anteriores já foram integralmente aplicadas no código-fonte, a Fase F entra em vigor nativamente:

## O que o LLM passa a fazer (Responsabilidade Especializada):
1. **Tradução de Intenção:** Converter prompts ambíguos do humano em estruturas de objetivo (Goals) rígidas que o *MPC Planner* consiga deglutir.
2. **Reporter (Linguagem Natural):** Explicar as consequências causais, estados finais e razões para os Rollbacks de forma amigável ao operador externo.
3. **Gerador de Hipóteses e Scaffolding:** Quando o *Local World Model* se depara com estados muito raros, sofrendo com um pico de divergência e Surpresa Contínua, o LLM é pinçado (via `_induce_hypothesis`) para conjecturar se há alguma *Hidden Variable* no ambiente que as matrizes de Causal Discovery falharam em monitorar.

## O que o LLM ESTÁ ABSOLUTAMENTE PROIBIDO de fazer:
- **Arbitrar Estrutura Causal:** O Grafo evolui unicamente por `magnitude`, `direção` e empírica das execuções sistêmicas (`train_local_model`).
- **Decidir Ações em Domínios Fechados:** A avaliação final em `causal_preflight.domain_mode == 'closed_causal'` expulsa o LLM da cadeira de Árbitro Final. O Risco vs Reversibilidade impõe `accept` ou `reject` sob limiares matemáticos estritos (Model Predictive Control).
- **Avaliar Qualidade de Episódios:** A retenção baseada no "bom-senso linguístico" expirou. O `episodic_compiler` bloqueia o acesso à rede neural se aquele episódio teve um *Surprise Delta* irresponsável ($> 0.4$), garantindo que a memória não sofra envenenamento conceitual disfarçado de prosa bem escrita por um LLM solto.

---

# Substrato Episódico Causal — Componentes Estruturados por Episódio
_Status: [EM ANDAMENTO 60%]_

Cada episódio armazenado pelo sistema agora contém 6 componentes causais explícitos além do log narrativo. Estes componentes são a matéria-prima para compilação de invariantes, treinamento de world models e aprendizado contrafactual.

## 1. `contexto_entrada` — Estado estruturado no momento da decisão
- [FEITO] Captura `preflight_risk`, `reversibility`, `domain_mode`, `homeostasis_mode`, `num_steps_planned`, `analogy_triggered`, `cache_hit`. Valores numéricos, não descrições.

## 2. `acao_granular` — Ação reproduzível
- [FEITO] Registra `strategy`, `plano_escolhido`, cada step com `tool`, `args_hash` (hash determinístico dos argumentos) e `status`. Informação suficiente para replay.

## 3. `resultado_objetivo` — Métricas medidas
- [FEITO] `prm_score`, `prm_risk`, `latency_ms`, `num_steps_executed`, `errors_found` (lista), `state_delta` (tools invocadas, rounds de revisão). Nenhuma narrativa.

## 4. `contrafactual_estimado` — O que teria acontecido com ação B?
- [FEITO] Consulta o Local World Model com ação `noop` (não fazer nada) para estimar o outcome alternativo. Também estima o `plan_b` (primeiro plano descartado pelo planner) usando a mesma matriz empírica. O `counterfactual_delta` mede quanto a ação escolhida foi melhor que a inação.

## 5. `surpresa_calculada` — Divergência previsão × realidade
- [FEITO] `abs(preflight_predicted_risk - (1.0 - actual_success))`. Sinal de treinamento primário para os world models e critério de gate para o episodic compiler.

## 6. `invariante_instanciado` — Padrão causal abstrato exemplificado
- [FEITO] Matching automático contra a biblioteca de abstrações (`causal_abstractions_v2.json`). Nome do invariante mais aplicável ao domínio/contexto do episódio. Inicialmente anotado por LLM (via compiler), progressivamente reconhecido automaticamente.

---

# Closed-Loop Prediction-Error Propagation
_Status: [EM ANDAMENTO 58%]_

Loop fechado automático que gera um sinal de treinamento a cada ciclo autônomo. Cada execução de ferramenta em domínio coberto agora segue o protocolo:

## Passo 1: PRE-ACTION — `register_prediction()`
- [FEITO] Antes de executar qualquer `execute_python` ou `execute_bash`, o sistema consulta o Local World Model e registra formalmente: *"Espero que Y mude para outcome X com confiança C e magnitude M"*. A previsão recebe um `prediction_id` único.

## Passo 2: EXECUTION — Execução real no sandbox
- [FEITO] A ferramenta executa normalmente. A physica do mundo determina o resultado.


## Passo 3: POST-ACTION — `measure_and_propagate()`
- [FEITO] Compara previsão vs realidade. Calcula erro normalizado e surpresa.
- [FEITO] **Learning rate inversamente proporcional à confiança prévia**: se o modelo estava "seguro" (confiança alta) e errou, o ajuste é grande. Se já estava incerto e errou pouco, o ajuste é pequeno.
- [FEITO] **Propagação para arestas causais relevantes**: reforça confiança/strength se acertou, enfraquece se errou. Promove `knowledge_type` de `observational` → `interventional_weak` → `interventional_strong` conforme acúmulo de confirmações.
- [FEITO] **Degradação automática**: se confiança cai abaixo de 0.4, `interventional_strong` é rebaixado para `interventional_weak`.
- [FEITO] **Publicação no Global Workspace** via canal `causal.prediction_error` com saliência proporcional à surpresa.

## Convergência esperada
Com alta velocidade de ciclos no sandbox, o grafo causal converge para representações interventivas sólidas. Cada ciclo autônomo gera um sinal de treinamento — não uma análise post-hoc manual.

---

# Ciclo Hipótese-Teste-Revisão — Abstrações como Hipóteses Falsificáveis
_Status: [EM ANDAMENTO 70%]_

Abstrações extraídas de episódios são tratadas como **hipóteses**, não como fatos. O compilador propõe → o sistema testa em episódios futuros → confirma, revisa ou descarta.

## Lifecycle completo
```
hypothesis → under_test → compiled_skill
                 ↓              ↓
              revised         (continua sendo testada)
                 ↓
            discarded (após 3 revisões sem melhora)
```

## Mecanismos implementados

### 1. Proposta = Hipótese (`compile_causal_invariant`)
- [FEITO] Cada abstração nasce com `status: hypothesis` e inclui um campo `testable_prediction` — uma previsão concreta e falsificável que a abstração implica.

### 2. Teste Automático (`auto_test_applicable`)

## Snapshot de Maturidade
- [FEITO] Persistido por domínio em `data/causal_maturity_snapshot.json`.
- [FEITO] Log completo de cada avaliação em `data/causal_maturity_log.jsonl`.

---

# Fase B — Epistemologia Autônoma e Engenharia Científica
_Status: [EM ANDAMENTO 62%]_

## B.3 Autoconsciência Funcional e Operacional de Primeira Pessoa
_Módulo: `self_causal_telemetry.py`_
- [FEITO] **Domínio `cognitive_architecture`**: O Cérebro Artificial instanciado como uma "Família Local" de mundo.
- [FEITO] **Sinais Vitais Operacionais**: Aferição da Fila, Estresse de Curto Prazo, Privação de Sono e Picos de Erro em T versus T+1.
- [FEITO] **Injeção de Gatilho de Observabilidade**: Sub-Loops vitais como `sleep_cycle`, `autonomy_loop`, e `healer_verify` agora repassam seus deltas de performance imediatamente para treinar o Grafo Causal Interno.
- [FEITO] A Máquina pode agora projetar intervenções *sobre seu próprio tempo de repouso e arquitetura* baseando-se em previsões causais de seus estados anteriores.

## B.4 Destilação Algorítmica (Complexidade de Kolmogorov)
_Módulo: `kolmogorov_compressor.py`_
- [FEITO] **Navalha de Occam Matemática**: Leitura e partição estrutural das regras criadas pela LLM na base de Abstrações Causais.
- [FEITO] **Poda de Covariância Preditiva (Subset Testing O(N))**: Remoção metódica de premissas nas regras causais e revalidação do subset (-1 dimensão) contra o Local World Model.
- [FEITO] **Promoção de Leis Fundamentais**: Se o sistema comprovar ($>98\%$ accuracy) que uma variável presente na axiomatização era inútil/espuria, ele _rebaixa_ a abstração verbosa da LLM para _Revised_ e promove uma Teoria Unificada Comprimida no lugar dela como `Hypothesis` isolada.
- [FEITO] Integração total do Destilador logo após o varrimento de Isomorfismo, mantendo a Base de Conhecimento tão matematicamente exata como as leis da Termodinâmica.
