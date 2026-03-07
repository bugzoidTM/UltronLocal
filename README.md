# UltronPro

UltronPro é uma plataforma de agente cognitivo/autônomo para operação técnica contínua (observabilidade, decisão, aprendizagem, execução e segurança), com foco em:

- **ciclos rápidos de melhoria** (feedback → treino → avaliação → promoção),
- **segurança operacional** (guardrails, integridade, gates de promoção),
- **memória e recuperação de contexto** (LightRAG + memória local),
- **execução prática** em infraestrutura real (Docker Swarm, APIs, jobs, replay).

---

## 1) Arquitetura técnica (estado atual)

### 1.1 Backend principal
- **Framework:** FastAPI
- **Módulo principal:** `backend/ultronpro/main.py`
- **Responsável por:** roteamento de API, loop metacognitivo, pipeline de treino/eval, observabilidade, governança.

### 1.2 Sub-sistemas cognitivos e operacionais
- **Metacognition ask endpoint:** `/api/metacognition/ask`
- **Learning agenda + mission control + sleep cycle** para contexto operacional.
- **Replay traces** para auditoria de decisões e reprocessamento de histórico.
- **PRM-lite (observação):** scoring heurístico de qualidade de processo por resposta.

### 1.3 LLM Router (multi-provider)
- Roteamento com fallback entre providers e estratégias.
- Providers integrados:
  - OpenRouter
  - DeepSeek
  - Groq
  - OpenAI (quando configurado)
  - Anthropic (quando configurado)
  - ultron_infer (local)
- Telemetria de uso por provider e healthchecks.

### 1.4 RAG + Search
- Integração com LightRAG (`knowledge_bridge.py`).
- Fluxo RAG-first para perguntas de domínio/operacionais.
- Threshold de confiança para uso de contexto recuperado.
- Endpoint de busca semântica híbrida com rerank:
  - `/api/search/semantic`

### 1.5 Cache semântico
- Módulo: `backend/ultronpro/semantic_cache.py`
- Duas camadas:
  1. **Exact hit** (hash MD5 da query normalizada)
  2. **Semantic hit** (cosine similarity em embedding local)
- Configuração atual:
  - threshold semantic: `0.92`
  - TTL exact: `24h`
  - TTL semantic: `12h`
  - índice semantic: até `500` entradas (evict por antiguidade)
- Integrado no `/api/metacognition/ask` com metadados:
  - `cache_hit: exact|semantic|null`
  - `from_cache: true|false`

### 1.6 Embeddings locais (zero custo API)
- Módulo: `backend/ultronpro/embeddings.py`
- Stack: `sentence-transformers`
- Modelo padrão: `all-MiniLM-L6-v2`
- Configurável por env:
  - `ULTRON_EMBED_MODEL`

### 1.7 Pipeline de treino LoRA
- Controle de jobs em `finetune_lora.py`
- Execução remota via `trainer_api.py`
- Script de treino: `train_lora.py`
- Recursos já implementados:
  - dispatch com dataset de treino/val separados,
  - early stopping,
  - timeout explícito em etapas pós-treino,
  - logs por fase (PASSO 0..5),
  - notificação explícita de conclusão ao control plane,
  - reconciliação automática de status + auto-register de adapter.

### 1.8 Presets de treino
- `run_preset` por job:
  - `fast_diagnostic`
  - `production`
- `fast_diagnostic` (atual):
  - epochs=3
  - max_steps=300
  - val split ativo
- Dispatch inclui flag explícita:
  - `--run-preset 'fast_diagnostic'`

### 1.9 Promoção de adapters (governança)
- Promoção bloqueada para jobs não-production.
- Regra atual:
  - só promove adapter de `run_preset=production`.
- Gates principais em uso operacional:
  - bateria A/B/C
  - sanity de regressão
  - integridade do ciclo de treino

### 1.10 Professor OpenClaw → UltronPro
- Endpoint dedicado:
  - `POST /api/openclaw/teacher/feedback`
- Permite ingestão de feedback rotulado por “professor” (OpenClaw), com metadados de origem.
- Suporta hardening por token:
  - `ULTRON_OPENCLAW_TEACHER_TOKEN`

---

## 2) Observabilidade e auditoria

### 2.1 PRM-lite (modo observação)
- Módulo: `backend/ultronpro/prm_lite.py`
- Endpoints:
  - `GET /api/prm/status`
  - `GET /api/prm/recent?limit=N`
- Em cada resposta do `metacognition/ask`, retorna:
  - `prm_score`
  - `prm_risk`
  - `prm_reasons`
  - `prm_mode=observation`

> Importante: atualmente o PRM **não bloqueia** fallback, promoção ou execução. É telemetria para calibração.

### 2.2 Decision traces
- Histórico em `/app/data/decision_traces/*.jsonl`
- Scripts utilitários para replay e povoamento de PRM:
  - `tools/replay_decision_traces_to_prm.py`
  - `tools/teacher_tasktype_coverage_prm.py`

### 2.3 Health e status
- endpoints de status do runtime e providers
- eventos persistidos no store local
- logs de treino por job no trainer

---

## 3) Infraestrutura

### 3.1 Orquestração
- **Docker Swarm**
- Serviços principais:
  - control plane UltronPro
  - trainer service
  - LightRAG
  - Redis

### 3.2 Dados persistentes
- `/app/data/*`
  - jobs, adapters, traces, estado PRM, caches, datasets, logs

### 3.3 Dependências críticas
- FastAPI / Uvicorn
- sentence-transformers
- scikit-learn / numpy
- httpx
- provedores LLM compatíveis

---

## 4) Endpoints-chave (resumo)

### Metacognition / PRM
- `POST /api/metacognition/ask`
- `GET /api/prm/status`
- `GET /api/prm/recent`

### LLM / Config
- `GET /api/llm/health`
- `GET /api/llm/usage`
- `GET /api/settings`
- `POST /api/settings`

### RAG / Busca
- `POST /api/search/semantic`
- LightRAG bridge via `knowledge_bridge.py`

### Finetune
- `POST /api/plasticity/finetune/jobs`
- `POST /api/plasticity/finetune/jobs/{id}/start`
- `GET /api/plasticity/finetune/jobs/{id}/progress`
- `POST /api/plasticity/finetune/notify-complete`

### Professor
- `POST /api/openclaw/teacher/feedback`

---

## 5) Fluxo recomendado de melhoria de modelo

1. Mudou dataset ou hiperparâmetro? → rodar `fast_diagnostic`
2. Passou no diagnóstico + sem regressão? → rodar `production`
3. Só promover adapter de job production
4. Registrar A/B/C + PRM + decisão de promoção

---

## 6) Estado atual de maturidade

- ✅ Multi-provider LLM routing funcional
- ✅ OpenRouter integrado na UI e no router
- ✅ RAG-first no metacognition ask
- ✅ Cache semântico operacional
- ✅ Embedding local sem custo API
- ✅ Pipeline de treino com reconciliação robusta
- ✅ PRM-lite em observação com dados reais
- ⚠️ PRM ainda sem gate decisório (intencional, aguardando calibração)

---

## 7) Roadmap futuro (priorizado)

## Curto prazo (1–2 semanas)
1. **Calibração do PRM-lite** com 300–1000 exemplos reais
   - correlacionar `prm_score` com outcomes reais (A/B/C, retrabalho, incidentes)
2. **Dashboard de qualidade unificado**
   - cache hitrate (exact/semantic)
   - RAG hitrate + score distribution
   - PRM distribution por task_type
3. **Hardening professor path**
   - enforce `teacher` namespace (`openclaw-*`)
   - validação anti-lixo no payload de feedback

## Médio prazo (2–6 semanas)
1. **Ativar PRM como gate gradual**
   - fase 1: warning only
   - fase 2: soft gate em fast_diagnostic
   - fase 3: gate parcial em production
2. **Semantic cache v2**
   - índice ANN simples (FAISS/ScaNN opcional)
   - políticas de invalidação por domínio
3. **Eval contínuo automático**
   - suíte A/B/C + regressão de latência + PRM + RAG grounding

## Longo prazo (6+ semanas)
1. **PRM supervisionado leve**
   - ajuste de pesos com labels humanas
   - possível migração para scorer treinado
2. **RAG de maior precisão**
   - grounding com citações estruturadas
   - melhor rank fusion local+remote
3. **Governança avançada de promoção**
   - rollout canário por tráfego
   - rollback automático por KPI degradado

---

## 8) Como rodar (dev)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn ultronpro.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 9) Release Notes (últimas 24h)

### ✅ Runtime, RAG e Resposta
- Integração **RAG-first** no `/api/metacognition/ask` para perguntas de domínio operacional.
- Correção de roteamento por token (evitando falso positivo por substring, ex.: `capital` vs `api`).
- Fallback seguro mantido para baixa confiança (`insufficient_confidence`).

### ✅ Cache semântico (novo)
- Novo módulo: `backend/ultronpro/semantic_cache.py`.
- Lookup em 2 camadas:
  - `exact` (MD5 da query normalizada)
  - `semantic` (cosine similarity)
- Política atual:
  - threshold semantic: `0.92`
  - TTL exact: `24h`
  - TTL semantic: `12h`
  - índice semantic: máximo `500` entradas (evict por antiguidade)
- Integração no `/api/metacognition/ask` com retorno:
  - `cache_hit: exact|semantic|null`
  - `from_cache: true|false`

### ✅ Embeddings locais sem custo API
- Ativado `sentence-transformers` no backend.
- Modelo padrão local:
  - `all-MiniLM-L6-v2`
- Configuração por env:
  - `ULTRON_EMBED_MODEL`

### ✅ LLM Router e Providers
- OpenRouter integrado no roteador e UI de settings.
- Ajustes de saúde/roteamento para DeepSeek, Groq e OpenRouter.
- Auto strategy operando com fallback consistente entre providers configurados.

### ✅ Finetune pipeline hardening
- Notificação explícita worker → control plane ao final do treino:
  - `POST /api/plasticity/finetune/notify-complete`
- Correções de travamento pós-treino e reconciliação de estado.
- Auto-register de adapter quando artefatos válidos existem.
- Presets de treino com flag explícita no dispatch:
  - `run_preset=fast_diagnostic|production`
  - comando inclui `--run-preset ...` e `--max-steps ...`
- Regra de governança:
  - promoção só para jobs `production`.

### ✅ Qualidade de dataset e operação
- Rebalanceamento do dataset para alvo ~`50/35/15` (A/B/C).
- Split train/val ativo e validado no dispatch.
- Pipeline de avaliação A/B/C executado e usado para rejeitar candidates regressivos.

### ✅ PRM-lite (modo observação)
- Novo módulo: `backend/ultronpro/prm_lite.py`.
- Endpoints:
  - `GET /api/prm/status`
  - `GET /api/prm/recent`
- `metacognition/ask` retorna:
  - `prm_score`, `prm_risk`, `prm_reasons`, `prm_mode=observation`
- **Sem bloquear** fallback/promoção nesta fase (telemetria para calibração).

### ✅ Povoamento rápido de PRM com dados reais
- Script de replay de traces:
  - `tools/replay_decision_traces_to_prm.py`
- Script de cobertura por task_type via professor OpenClaw:
  - `tools/teacher_tasktype_coverage_prm.py`

---

## 10) Nota de engenharia

UltronPro é orientado a **operação real**: melhorar continuamente sem quebrar produção.
A prioridade é **qualidade observável + segurança + iteração rápida**, não só benchmark isolado de modelo.
