# ROADMAP_AGI_FRONTS.md

_Status geral do roadmap: 63%_

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

### Regra de verdade

Só vale como concluído quando houver:

- código implementado
- integração funcionando
- persistência durável quando aplicável
- observabilidade mínima
- benchmark ou validação compatível com o item

---

## Visão macro

### Atualização operacional — 2026-03-19

- [FEITO] Migração do provider principal de metacog para **Gemini 3 Flash Preview** com provider nativo no router do UltronPro
- [FEITO] Fluxo principal de `/api/metacognition/ask` desacoplado de U1/Qwen, `ollama_local`, `ultron_infer`, OpenRouter e DeepSeek no caminho primário
- [FEITO] Higienização de rate-limit/quarentena para Gemini com cooldown curto e sem quarentena persistente por `429`
- [FEITO] Reativação de `judge` e `reflexion` em serviços separados com ticks conservadores
- [EM ANDAMENTO 75%] Reativação de autonomia/autoalimentação com cadência segura e correção de falha de autoria (`_classify_action_origin`)
- [EM ANDAMENTO 60%] Consolidação final dos workers autônomos em torno do provider Gemini e observação longitudinal pós-migração

## Front 1 — Plasticidade estrutural real
_Status do front: 90%_

Meta 10/10:

- detectar lacuna real
- propor mudança estrutural
- validar em shadow/A-B
- promover com gate
- persistir ganho
- fazer rollback se piorar

**Leitura atual:** front já está funcional e ativo. Falta principalmente robustez longitudinal, mais evidência orgânica recorrente e validação mais dura por benchmark externo/interno contínuo.

## Front 2 — Modelo de mundo causal
_Status do front: 68%_

Meta 10/10:

- agir em ambiente com consequência
- prever efeitos antes da ação
- medir surpresa
- revisar relações causais
- usar causalidade para escolher planos melhores

**Leitura atual:** já existe `ultronbody`, episódios persistidos, grafo causal com edges funcionando, predição/benchmark/contrafactual em embrião operacional. Falta benchmark causal on/off forte e uso mais decisivo no planner.

## Front 3 — Generalização entre domínios
_Status do front: 81%_

Meta 10/10:

- extrair abstrações explícitas
- aplicar em domínio diferente
- medir ganho vs baseline
- consolidar abstrações multi-domínio

**Leitura atual:** já existe biblioteca de abstrações com versionamento/fragilidade, extrator estrutural em lote a partir de episódios, mapper estrutural entre domínios, benchmark de transferência com consolidação automática e histórico multi-domínio. A comparabilidade externa também subiu: agora há famílias/splits reproduzíveis, baseline congelado comparável, auditoria do suite e delta por benchmark/família/split. Ainda falta elevar a separação entre padrão superficial vs estrutural e ampliar validade pública/licenciada dos benchmarks externos.

## Front 4 — Automanutenção e individuação
_Status do front: 62%_

Meta 10/10:

- distinguir self de ambiente
- proteger integridade interna
- operar com orçamento real
- detectar degradação
- reparar ou contornar dano
- preservar continuidade
- manter identidade operacional
- priorizar capacidade futura de agir

**Leitura atual:** a fase deixou de ser só peças soltas. Agora existe uma camada unificada de `self_governance` conectando `self_model`, `homeostasis`, `economic` e `identity_daily`, com self-contract operacional, fronteira self/ambiente, invariantes, reserva de continuidade, custo operacional, respostas homeostáticas, detecção/containção/reparo e ledger biográfico/incidentes. Ainda faltam spawn descendente, mutação controlada, reconstruções mais profundas e arbitragem mais sofisticada entre objetivos externos e integridade interna.

## Front 5 — Consciência operacional integrada
_Status do front: 46%_

Meta 10/10:

- integrar informação relevante em um espaço global
- selecionar foco por atenção competitiva
- manter sentido de agência e autoria
- usar marcadores afetivos artificiais
- modelar outros agentes
- observar o próprio processamento
- manter um eu narrativo contínuo
- medir integração interna por proxies úteis, sem confundir isso com prova de consciência forte

**Leitura atual:** não está zerado, mas ainda é o front mais imaturo. Já existem embriões em `cognitive_state`, `reflexion_agent`, `internal_critic`, `tom` e `identity_daily`, mas ainda não existe um verdadeiro global workspace integrado.

---

# Fase 1 — Plasticidade estrutural real
_Status da fase: 98%_

## 1.1 Registro durável de patches cognitivos
_Status: [FEITO]_

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
_Status: [FEITO]_

- [FEITO] Detector de padrões de falha recorrente
- [FEITO] Agregação por domínio/tipo de tarefa
- [FEITO] Geração automática de proposta de patch
- [FEITO] Priorização por impacto x frequência
- [FEITO] Consolidação/deduplicação por cluster canônico de falha

## 1.3 Shadow evaluation / A-B / canário para patches
_Status: [FEITO]_

- [FEITO] Runner baseline vs candidato
- [FEITO] Comparador de métricas
- [FEITO] Modo shadow
- [FEITO] Modo canário
- [FEITO] Registro de regressão por domínio

## 1.4 Promotion gate unificado
_Status: [FEITO]_

- [FEITO] Regras mínimas de promoção
- [FEITO] Regras de bloqueio por regressão
- [FEITO] Aprovação automática com thresholds explícitos
- [FEITO] Registro de decisão de promoção

## 1.5 Rollback automático e last-known-good
_Status: [EM ANDAMENTO 90%]_

- [FEITO] Snapshot da configuração cognitiva ativa
- [FEITO] Referência de última versão boa
- [FEITO] Rollback automático por regressão
- [FEITO] Ledger de rollback
- [PENDENTE] endurecer rollback em janela temporal maior com mais evidência longitudinal

## 1.6 Benchmark suite por domínio
_Status: [EM ANDAMENTO 85%]_

- [FEITO] Suite para factual, debugging, planning, tool use, memory/continuity, safety
- [FEITO] Baseline congelado
- [FEITO] Execução reprodutível
- [FEITO] Relatório por domínio
- [PENDENTE] aumentar correlação entre benchmark de patch e benchmark externo comparável

---

# Fase 2 — Modelo de mundo causal
_Status da fase: 82%_

## 2.1 Corpo mínimo / ambiente de interação
_Status: [FEITO 100%]_

- [FEITO] Escolher ambiente inicial
- [FEITO] Serviço/conector `ultronbody`
- [FEITO] API mínima com `observe()`, `act(action)`, `reset()`, `reward`, `done`, `state_summary`
- [FEITO] Persistência de episódios
- [FEITO] ampliar diversidade de ambiente/consequência além do corpo mínimo atual

## 2.2 Schema causal de episódio
_Status: [FEITO 100%]_

- [FEITO] Campos estruturais principais de episódio causal
- [FEITO] Persistência durável
- [FEITO] Replay causal
- [FEITO] padronizar completamente `expected_effect` vs `observed_effect` em todos os fluxos

## 2.3 Atualização causal por evidência
_Status: [EM ANDAMENTO 85%]_

- [FEITO] Reforço de edges confirmadas
- [FEITO] Enfraquecimento de edges falhas
- [EM ANDAMENTO 85%] Controle de confiança por suporte e conflito
- [EM ANDAMENTO 85%] Escopo contextual

## 2.4 Predição causal pré-ação
_Status: [EM ANDAMENTO 80%]_

- [FEITO] Previsão de efeito por passo/plano em forma inicial
- [EM ANDAMENTO 80%] Score de risco/benefício
- [EM ANDAMENTO 80%] Dependências e efeitos colaterais previstos
- [EM ANDAMENTO 75%] Integração no planner

## 2.5 Contrafactual e análise de surpresa
_Status: [EM ANDAMENTO 60%]_

- [FEITO] Cálculo de surpresa em embrião operacional
- [EM ANDAMENTO 60%] Pergunta contrafactual por episódio
- [EM ANDAMENTO 55%] Identificação de causa provável da falha
- [EM ANDAMENTO 55%] Revisão automática do modelo causal

## 2.6 Benchmark causal on/off
_Status: [EM ANDAMENTO 20%]_

- [EM ANDAMENTO 20%] Suite com causal ligado/desligado ainda parcial
- [PENDENTE] Métricas comparativas robustas
- [PENDENTE] Medida de redução de risco e aumento de sucesso claramente demonstrada

---

# Fase 3 — Generalização entre domínios
_Status da fase: 81%_

## 3.1 Biblioteca de abstrações explícitas
_Status: [FEITO 100%]_

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
_Status: [EM ANDAMENTO 78%]_

- [FEITO] Agrupamento de episódios similares em forma inicial
- [EM ANDAMENTO 78%] Extração de princípio compartilhado
- [EM ANDAMENTO 72%] Separação entre padrão superficial e estrutural
- [EM ANDAMENTO 80%] Geração de template procedural transferível

## 3.3 Mapper de alinhamento estrutural A→B
_Status: [EM ANDAMENTO 78%]_

- [FEITO] Similaridade estrutural entre tarefas
- [FEITO] Mapeamento de papéis/entidades/fases em forma inicial
- [EM ANDAMENTO 78%] Aplicação assistida ao domínio-alvo

## 3.4 Benchmark de transferência
_Status: [EM ANDAMENTO 85%]_

- [FEITO] Escolher famílias de tarefas isomórficas
- [FEITO] Protocolo aprender em A, aplicar em B, comparar com baseline
- [FEITO] Medir zero-shot / few-shot transfer
- [FEITO] Relatório por abstração

## 3.5 Consolidação multi-domínio
_Status: [EM ANDAMENTO 82%]_

- [FEITO] Histórico de transferência por abstração
- [EM ANDAMENTO 85%] Reforço de abstrações multi-domínio
- [EM ANDAMENTO 80%] Rebaixamento de abstrações frágeis
- [EM ANDAMENTO 82%] Score de generalidade

## 3.6 Benchmarks externos comparáveis
_Status: [EM ANDAMENTO 72%]_

- [FEITO] Harness externo inicial implementado
- [FEITO] Baseline congelável
- [FEITO] Histórico persistido de runs
- [EM ANDAMENTO 78%] subset comparável inspirado em ARC/HellaSwag/MMLU agora com famílias, splits, lineage, tier de comparabilidade e seleção reproduzível
- [EM ANDAMENTO 70%] comparação pareada contra baseline congelado por benchmark/família/split
- [EM ANDAMENTO 72%] auditoria estrutural do suite + selftest oracle
- [PENDENTE] rodar ciclo comparável mais fiel/licenciado e ampliar validade pública

---

# Fase 4 — Automanutenção, individuação e continuidade
_Status da fase: 89%_

_Atualização 2026-03-19: deploy da Fase 4 estabilizado no serviço principal via stack spec. Rotas `/api/self-governance/*`, storage dedicado, camada de linhagem/descendência, bridge de runtime preparado e autoavaliação/promoção mínima estão ativas em produção._

## 4.1 Schema de self-model operacional
_Status: [FEITO 100%]_

- [FEITO] Schema de self-model
- [FEITO] Persistência durável
- [FEITO] Campos equivalentes para identidade, continuidade, capacidade, risco e memória crítica
- [FEITO] fechar cobertura explícita de `last_known_good`, `self_trust_score` e perfil de recursos como contrato formal único

## 4.2 Delimitação self vs ambiente
_Status: [FEITO 100%]_

- [FEITO] Classificação parcial entre self, memória, tooling e ambiente via módulos dispersos
- [FEITO] Regras de fronteira operacional unificadas
- [FEITO] Registro de dependências críticas
- [FEITO] Detecção de violação de fronteira

## 4.3 Invariantes de identidade
_Status: [FEITO 100%]_

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
_Status: [EM ANDAMENTO 68%]_

- [FEITO] Serviço de monitoramento
- [EM ANDAMENTO 55%] Alertas por desvio
- [EM ANDAMENTO 50%] Classificação `normal/atenção/degradação/crítico`
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
_Status: [EM ANDAMENTO 84%]_

- [FEITO] detector por módulo existe de forma fragmentada
- [FEITO] Score de severidade
- [FEITO] Histórico de falhas consolidado
- [EM ANDAMENTO 72%] Relação sintoma → módulo provável mais forte

## 4.11 Estratégias de contenção
_Status: [EM ANDAMENTO 76%]_

- [FEITO] quarentena/isolamento parcial via gate/rollback/guardrails
- [EM ANDAMENTO 55%] Isolamento de módulo suspeito
- [EM ANDAMENTO 55%] Quarentena explícita de patch recém-promovido
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
_Status: [FEITO 100%]_

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
_Status: [EM ANDAMENTO 65%]_

- [FEITO] Classificação formal raiz/crítica/operacional/temporária/descartável
- [FEITO] Política de proteção
- [EM ANDAMENTO 35%] Backup e restauração
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

---

# Fase 5 — Consciência operacional integrada
_Status da fase: 65%_

_Atualização 2026-03-19: já existia base operacional de workspace global no código (`global_workspace` no store, publicações de `self_model`, `tom`, `judge`, `metacognition` e loop Roadmap V5). Agora também há `meta_observer` explícito com endpoint próprio e publicação periódica no workspace; status, broadcast, consumo e autoria do workspace estão validados em produção. Nesta rodada, entrou também uma camada explícita de marcadores afetivos artificiais com snapshot composto, endpoint próprio e publicação periódica em `affect.state`/`policy.risk`, conectando narrativa, incerteza, competição e promessas pendentes ao workspace global. Além disso, foi adicionada uma autobiografia operacional contínua com resumo narrativo explícito, `first_person_report`, postura de continuidade, riscos de continuidade e publicação periódica em `self.narrative`. Agora também existe um proxy explícito de integração interna, combinando workspace, meta-observer, afetos e narrativa em um score operacional observável e publicável em `integration.proxy`. Por fim, foi criado um benchmark operacional inicial persistido, com baseline congelável, runs comparáveis e score integrado para foco, autoria, ignorados, surpresa interna, autobiografia e modelagem do outro. Também foi constatado que o frontend estava conceitualmente defasado em relação ao Front 5; a UI foi limpa de blocos legados de sprint/fase antiga, ganhou aba própria de Front 5 com lazy-load e deixou de pré-carregar na home os endpoints mais pesados de autobiografia/integração/benchmark._

Observação conceitual: esta fase é inspirada por ideias de acesso global, integração, metacognição e autorrelato, mas não deve ser tratada como prova de consciência fenomenal. Global workspace e metacognição são boas inspirações arquiteturais; métricas tipo phi entram apenas como proxies exploratórios.

## 5.1 Espaço de trabalho global
_Status: [EM ANDAMENTO 62%]_

### Objetivo
Criar um núcleo compartilhado de foco atual, acessível por todos os módulos relevantes.

### Entregas
- [FEITO] Estrutura operacional persistida via tabela `global_workspace`
- [EM ANDAMENTO 60%] Campos mínimos de foco global
- [FEITO] API de publicação e consumo compartilhada
- [FEITO] Persistência temporal curta com snapshots

### Critério de pronto
- [EM ANDAMENTO 55%] planner/reflexion/judge/self-model/TOM/metacognition já escrevem ou observam o mesmo espaço operacional; ainda falta fechar causal engine e cobertura total de consumidores

## 5.2 Atenção competitiva e broadcast global
_Status: [EM ANDAMENTO 56%]_

- [FEITO] Score de saliência por item
- [EM ANDAMENTO 46%] Fatores de saliência agora podem receber viés de atenção vindo de `affect.state`/`policy.risk`
- [EM ANDAMENTO 42%] Mecanismo de seleção top-k via `top_salience`/`competition_index`
- [FEITO] Broadcast para módulos consumidores
- [EM ANDAMENTO 48%] Registro do que ganhou e do que foi ignorado

## 5.3 Sentido de agência e autoria
_Status: [EM ANDAMENTO 63%]_

- [EM ANDAMENTO 62%] rastros de decisão/execução agora existem de forma mais explícita via `action_enqueue_decision`, `arbiter_block` e `authorship_trace`
- [FEITO] Marca de autoria por ação no workspace global
- [EM ANDAMENTO 58%] Ligação formal entre intenção, decisão e execução com classificação de origem (`self_generated`, `externally_triggered`, `mixed`, `unknown`)
- [FEITO] Campo/visão inicial de `authorship_trace` via endpoints `/api/authorship/trace` e `/api/authorship/status`
- [EM ANDAMENTO 45%] Integração inicial na memória episódica via `authorship_origin` e `arbiter_votes` em `append_episode`

## 5.4 Modelo preditivo do self
_Status: [EM ANDAMENTO 10%]_

- [EM ANDAMENTO 10%] há embriões em `self_model` e `homeostasis`
- [PENDENTE] Previsão de mudança no self-state
- [PENDENTE] Comparação predicted vs observed self-change
- [PENDENTE] Score de surpresa interna
- [PENDENTE] Ajuste do self-model por divergência interna

## 5.5 Marcadores afetivos artificiais
_Status: [EM ANDAMENTO 48%]_

- [EM ANDAMENTO 42%] Vetor afetivo operacional via `valence/arousal/confidence/frustration/curiosity/threat`
- [FEITO] Geração baseada em sucesso/fracasso/custo/surpresa/ameaça em forma proxy por narrativa, incerteza, competição e promessas pendentes
- [PENDENTE] Integração com recuperação de memória
- [EM ANDAMENTO 55%] Integração com atenção e política de risco via publicações `affect.state` e `policy.risk`

## 5.6 Modelagem de outros agentes
_Status: [EM ANDAMENTO 32%]_

- [EM ANDAMENTO 32%] módulo `tom` já faz inferência inicial de intenção/estado do outro e publica no workspace global
- [PENDENTE] `other_agent_model` com schema rico
- [PENDENTE] Simulação mental pré-ação
- [EM ANDAMENTO 20%] Integração com planner e causal engine

## 5.7 Observador de segunda ordem
_Status: [EM ANDAMENTO 68%]_

- [EM ANDAMENTO 68%] `reflexion_agent`, `internal_critic` e metacognição parcial já existem
- [FEITO] Módulo `meta_observer` explícito
- [FEITO] Relatório periódico do foco/competição/autoria/incerteza/conflitos disponível por endpoint dedicado
- [EM ANDAMENTO 48%] Encaminhamento sistemático para reflexion via publicação de `reflexion.trigger`

## 5.8 Eu narrativo contínuo
_Status: [EM ANDAMENTO 62%]_

- [EM ANDAMENTO 55%] `identity_daily` e registros parciais já dão embrião autobiográfico
- [FEITO] `autobiographical_summary`
- [EM ANDAMENTO 60%] atualização após promoções, crises, reparos e transferências
- [EM ANDAMENTO 45%] uso em decisões importantes via publicação contínua em `self.narrative`

## 5.9 Proxy de integração interna
_Status: [EM ANDAMENTO 74%]_

- [EM ANDAMENTO 72%] há observabilidade composta entre workspace, meta-observer, afeto e narrativa
- [FEITO] Proxies mínimos de integração interna
- [EM ANDAMENTO 58%] Painel longitudinal via endpoint e workspace `integration.proxy`
- [EM ANDAMENTO 62%] Thresholds experimentais e alertas operacionais

## 5.10 Benchmark de consciência operacional
_Status: [EM ANDAMENTO 68%]_

- [FEITO] Casos de teste proxy para foco, autoria, ignorados, surpresa interna, autobiografia e modelagem do outro
- [FEITO] Métricas de qualidade integrada
- [EM ANDAMENTO 52%] comparação contra baseline via freeze/run com delta

---

# Fase 6 — Instrumentação executiva e gestão do roadmap
_Status da fase: 52%_

## 6.1 Painel de progresso do roadmap
_Status: [EM ANDAMENTO 88%]_

- [FEITO] Expor status macro por fase/front
- [FEITO] Expor itens FEITO / EM ANDAMENTO / PENDENTE
- [FEITO] Expor percentuais reais
- [EM ANDAMENTO 65%] Tornar a leitura do roadmap robusta em runtime com fallback embarcado no backend, sem depender apenas do path do workspace do host
- Validação: `backend/ultronpro/roadmap_status.py` + endpoints:
  - `GET /api/roadmap/status`
  - `GET /api/roadmap/items`
  - `GET /api/roadmap/scorecard`

## 6.2 Ritual de atualização do roadmap
_Status: [EM ANDAMENTO 70%]_

- [FEITO] Toda implementação relevante atualiza este arquivo
- [FEITO] Toda validação relevante ajusta status
- [FEITO] Toda entrega parcial recebe percentual honesto
- [PENDENTE] Formalizar rotina automática de auditoria/CI

## 6.3 Critério formal para nota de maturidade
_Status: [EM ANDAMENTO 35%]_

- [FEITO] Definir score por front
- [EM ANDAMENTO 30%] Vincular score a benchmarks
- [EM ANDAMENTO 40%] Atualizar score conforme evidência real

---

## Auditoria rápida de implementação x ativação em produção (2026-03-19)

- **Fase 1 — Plasticidade estrutural real:** implementação forte e ativação operacional em produção; faltam robustez longitudinal e correlação mais dura com benchmark externo.
- **Fase 2 — Modelo causal:** implementação boa e ativa em produção, mas a prova comparativa causal on/off ainda está incompleta.
- **Fase 3 — Generalização entre domínios:** implementação boa e ativa em produção para abstrações/mapper/benchmarks; validade pública dos benchmarks ainda é parcial.
- **Fase 4 — Automanutenção/individuação:** implementação ampla e ativa em produção; spawn lógico, arbitragem e linhagem estão rodando, mas ainda sem runtime descendente plenamente acoplado.
- **Fase 5 — Consciência operacional integrada:** implementação parcial porém real e ativa em produção para workspace, meta-observer, autobiografia, TOM, proxy de integração e benchmark inicial; ainda falta fechar agência/autoria forte, self-model preditivo e integração causal/planner.
- **Fase 6 — Instrumentação do roadmap:** implementação parcial; endpoints existem, mas a robustez em runtime ainda estava incompleta porque o backend tentava ler o roadmap só no path do host. Esta rodada adiciona fallback embarcado no backend para fechar essa lacuna.

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

---

## Próximo passo imediato

### Próxima implementação alvo recomendada: 5.3 Sentido de agência e autoria

**Motivo:**
- agora já existe `authorship_trace` inicial, então o próximo passo útil é separar melhor ação auto-gerada vs disparo externo e persistir isso em memória episódica
- isso fecha melhor o elo entre intenção, decisão, execução e continuidade autobiográfica
- também fortalece benchmark operacional, auditoria de produção e integração com planner/reflexion

Minha leitura final continua esta: as ideias de Front 4 e Front 5 não são perfumaria filosófica. Elas melhoram a arquitetura de verdade. O cuidado precisa ser semântico e metodológico: chamar isso de **consciência operacional integrada** e exigir evidência operacional, não vender como prova de consciência fenomenal.
