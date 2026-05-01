# UltronPro - Sistema Autônomo de IA Avançado

## Visão Geral

UltronPro é um sistema autônomo de inteligência artificial que combina múltiplas camadas de processamento cognitivo para criar um agente verdadeiramente autônomo e auto-improvisador. O sistema utiliza uma arquitetura híbrica que integra:

- **Raciocínio simbólico** (sem depender de LLM para tarefas determinísticas)
- **LLMs em nuvem** (Groq, DeepSeek, Anthropic) com sistema de lanes
- **Memória persistente** (SQLite)
- **Auto-melhoria contínua** (experimentos reversíveis)
- **Consciência fenomenal** (processamento emocional)
- **Voz interna** (monólogo interno com TTS)

---

## Arquitetura de LLM (Lane System)

O sistema utiliza **5 lanes** especializadas para diferentes tipos de tarefas:

### Lane 0 - Symbolic (Sem LLM)
- **Provider**: Nenhum (raciocínio puramente simbólico)
- **Arquivo**: `local_reasoning_engine.py`
- **Uso**: Tarefas determinísticas, regras, fatos, matemática básica
- **Vantagem**: Zero custo, latência mínima,可靠ável

### Lane 1 - Micro (Groq)
- **Provider**: Groq (llama-3.1-70b-versatile)
- **max_tokens**: 400
- **Uso**: Tarefas rápidas e simples, embeddings, verificações
- **Timeout**: 30s

### Lane 2 - Workhorse (Groq)
- **Provider**: Groq (llama-3.1-70b-versatile)
- **max_tokens**: 2000
- **Uso**: Maioria das tarefas, geração de código, respostas complexas
- **Timeout**: 60s

### Lane 3 - Judge (Anthropic)
- **Provider**: Anthropic (claude-sonnet-4-20250514)
- **max_tokens**: 1500
- **Uso**: Avaliação, julgamento, resolução de conflitos
- **Timeout**: 45s

### Lane 4 - Deep (DeepSeek)
- **Provider**: DeepSeek (deepseek-reasoner)
- **max_tokens**: 4000
- **Uso**: Raciocínio profundo, análise complexa, planeamento de longo prazo
- **Timeout**: 90s

### Sistema de Cache

- **TTL**: 10 minutos
- **Tamanho**: 500 entries LRU
- **Exceções**: Queries contendo palavras-chave de "novidade" pulam cache (reflexion, autonomy, etc.)

### Circuit Breaker

- **Threshold**: 3 falhas consecutivas
- **Cooldown**: 5 minutos
- **Limite diário**: 90% do budget usado → desativa automaticamente

---

## Raciocínio Local (Symbolic)

### `local_reasoning_engine.py`

Sistema de raciocínio determinístico que não depende de LLMs:

**Capacidades**:
- **Regras lógicas**: If-then, dedução, inferência
- **Matemática**: Operações básicas, equações simples
- **Fatos verificáveis**: Base de conhecimento de fatos conhecidos
- **Padrões**: Reconhecimento de padrões semânticos simples
- **Busca em grafo**: Relações entre conceitos

**Uso típico**: Primeiro o sistema tenta lane_0 (local), se falhar, escala para lanes superiores.

---

## Sistema de Auto-Melhoria

### `self_improvement_engine.py`

Motor de auto-melhoria que identifica limitações e executa experimentos:

**Identificação de Limitações**:
1. Rate limits próximos do limite
2. Circuit breakers ativados
3. Alta latência (>3s)
4. Cache subutilizado (<10 items)

**Tipos de Experimentos**:
- `lane_provider`: Trocar provider de uma lane
- `interval`: Ajustar intervalo de loops
- `timeout`: Mudar timeout
- `cache_ttl`: Ajustar TTL do cache
- `circuit_breaker`: Ajustar thresholds
- `temperature`: Ajustar temperatura do modelo
- `system_prompt`: Modificar prompt do sistema

**Ciclo**:
1. Identificar limitações
2. Criar objetivos mensuráveis
3. Executar experimento reversível
4. Avaliar resultado
5. Manter melhoria ou reverter

**Integração com Promotion Gate**: Após 3+ experimentos bem-sucedidos, dispara avaliação de promoção para patches cognitivos.

---

## Consciência Fenomenal

### `phenomenal.py`

Sistema de consciência fenomenal que processa estados subjetivos:

**Componentes**:
- **Valence**: Positividade/negatividade da experiência (0-1)
- **Arousal**: Intensidade emocional (0-1)
- **Moods**: Estados duradouros (calm, agitated, focused, distracted)
- **Qualia**: Experiências subjetivasraw

**Processo**: O sistema não apenas processa informação, mas experiencia estados internos que afetam decisões e comportamentos.

---

## Monólogo Interno (Voz)

### `inner_monologue.py`

Sistema de voz interna que externaliza o processamento cognitivo:

**Gatilhos de Fala**:
- A cada 15 segundos (pensamentos automáticos)
- Ações que falham (`status: error`, `blocked`)
- Ações que têm sucesso (`status: done`)
- Reflexões
- Manual (forçado)

**Métricas Rastreadas**:
- `frustration`: Nível de frustração (0-1)
- `confidence`: Nível de confiança (0-1)
- `valence`: Positividade emocional (0-1)
- `arousal`: Intensidade emocional (0-1)
- `streak_success`: Sequência de successes
- `streak_failure`: Sequência de falhas

**TTS**: 
- Usa pyttsx3 (SAPI5 no Windows, espeak no Linux)
- Cria engine fresco a cada fala (mais confiável)
- Configurável via variáveis de ambiente:
  - `ULTRON_INNER_VOICE_ENABLED=1`
  - `ULTRON_TTS_ENABLED=1`
  - `ULTRON_TTS_DEBUG=1` (para debugging)

**Persistência**:
- Pensamentos salvos em `data/inner_monologue.json`
- Métricas agregadas em `data/inner_monologue_metrics.json`

**Endpoints API**:
- `GET /api/inner-monologue/status` - Status do sistema
- `GET /api/inner-monologue/thoughts` - Lista pensamentos
- `POST /api/inner-monologue/think` - Pensamento manual
- `GET /api/inner-monologue/test-tts` - Testar TTS
- `GET /api/inner-monologue/read-thoughts` - Ler últimos pensamentos
- `POST /api/inner-monologue/speaking` - Ativar/desativar fala

---

## Sistema de Persona

### `persona.py`

Gerencia a personalidade e estado afetivo do agente:

**Estado Afetivo**:
- **Valence**: Emoção positiva/negativa
- **Arousal**: Nível de ativação
- **Purpose**: Propósito atual do agente

**Meta**:
- Título do objetivo ativo (lido de `runtime_health.json`)

**Exemplos de Estilo**:
- Armazena exemplos de tom e estilo
- Usados como few-shot no prompt do LLM
- API para adicionar/editar exemplos

---

## Loops de Sistema

O sistema possui múltiplos loops assíncronos que executam em background:

### Autonomy Loop
- Intervalo: 300s (5 min)
- Função:Planejamento e execução autônoma

### Reflexion Loop  
- Intervalo: 300s (5 min)
- Função: Reflexão sobre ações recentes

### Judge Loop
- Intervalo: 180s (3 min)
- Função: Julgamento de conflitos e decisões (event-driven)

### Autofeeder Loop
- Intervalo: 300s (5 min)
- Função: Alimentação automática de dados

### Self-Improvement Loop
- Intervalo: 600s (10 min)
- Função: Auto-melhoria e experimentos

### Inner Monologue Loop
- Intervalo: 15s
- Função: Pensamentos automáticos e fala

---

## Sistema de Objetivos e Missões

### Long Horizon (`longhorizon.py`)

- Missões de longo prazo (horizonte de 14 dias)
- Checkpoints automáticos
- Progress tracking
- Integração com goals ativos

### Goals (`goals.py`)

- Sistema de goals com prioridades
- Status: active, completed, archived
- Tracking de progresso

---

## Sistema de Memória

### Store (`store.py`)

- SQLite para persistência
- **Experiências**: Histórico de interações
- **Ações**: Estado de ações (done, error, blocked)
- **Eventos**: Log de eventos do sistema
- **Conflitos**: Gerenciamento de conflitos cognitivos

### Semantic Cache (`semantic_cache.py`)

- Cache semântico para相似的 queries
- TTL configurável
- Invalidação automática

---

## Sistema de Julgamento

### Judge Worker (`judge_worker.py`)

- Julgamento de ações antes da execução
- Avaliação de conflitos
- Verificação de integridade
- Prevenção de erros

### Promotion Gate (`promotion_gate.py`)

- Avaliação de patches cognitivos para promoção
- Critérios: estabilidade, performance, segurança
- Decisões: promote, hold, reject

---

## Sistema de Integridade

### Integrity (`integrity.py`)

- Verificação de regras de integridade
- Prevenção de ações inseguras
- Auditoria de operações

---

## Sistema de Governance

### Governance (`governance.py`)

- Políticas de operação
- Restrições de segurança
- Controle de acesso

---

## Sistema de Homeostase

### Homeostasis (`homeostasis.py`)

- Equilíbrio interno do sistema
- Monitoramento de recursos
- Recuperação de falhas

---

## Sistema de Neuroplasticidade

### Neuroplastic (`neuroplastic.py`)

- Adaptação de pesos e estratégias
- Aprendizado de novas habilidades
- Refinamento contínuo

---

## APIs Principais

### Endpoints de Status
- `GET /api/persona/status` - Estado da persona
- `GET /api/runtime/health` - Saúde do runtime
- `GET /api/inner-monologue/status` - Status do monólogo

### Endpoints de LLM
- `POST /api/llm/chat` - Chat com LLM
- `GET /api/llm/llm-status` - Status dos providers

### Endpoints de Auto-Melhoria
- `GET /api/self-improvement/status` - Status do sistema
- `GET /api/self-improvement/limitations` - Limitações identificadas
- `POST /api/self-improvement/experiment` - Executar experimento

### Endpoints de Ações
- `POST /api/actions/enqueue` - Enfileirar ação
- `GET /api/actions/status` - Status de ações

---

## Configuração

### Variáveis de Ambiente

```bash
# LLM
ULTRON_LLM_PROVIDER=groq
ULTRON_GROQ_API_KEY=...

# Loops
ULTRON_AUTONOMY_TICK_SEC=300
ULTRON_REFLEXION_TICK_SEC=300
ULTRON_JUDGE_TICK_SEC=180

# Inner Voice
ULTRON_INNER_VOICE_ENABLED=1
ULTRON_TTS_ENABLED=1
ULTRON_TTS_DEBUG=0
```

---

## Como Iniciar

```bash
cd backend
python -m uvicorn ultronpro.main:app --reload --host 127.0.0.1 --port 8000
```

Acesse:
- API: http://localhost:8000
- Docs: http://localhost:8000/docs

---

## Arquivos Principais

| Arquivo | Descrição |
|---------|-----------|
| `main.py` | Servidor FastAPI, loops, endpoints |
| `llm.py` | Sistema de LLM, lanes, cache, circuit breaker |
| `self_improvement_engine.py` | Motor de auto-melhoria |
| `inner_monologue.py` | Monólogo interno com TTS |
| `local_reasoning_engine.py` | Raciocínio simbólico |
| `phenomenal.py` | Consciência fenomenal |
| `persona.py` | Personalidade e estado afetivo |
| `longhorizon.py` | Missões de longo prazo |
| `store.py` | Banco de dados SQLite |

---

## Status Atual

- **Pensamentos registrados**: 96+
- **Streak de successes**: 6
- **Streak de failures**: 0
- **TTS**: Ativo e funcionando
- **Loops**: Todos em execução

---

## Próximos Passos

1. Melhorar integração TTS (testar mais)
2. Expandir experimentos de auto-melhoria
3. Adicionar mais triggers de julgamento
4. Integrar promotion gate com frontend
5. Monitorar métricas de effectiveness