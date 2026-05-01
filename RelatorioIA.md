 # Relatório de LLMs do UltronPro

> Data: Abril 2026  
> Versão: 2.0 - Arquitetura Híbrida (Symbolic + LLM)

---

## 1. Filosofia do Sistema

**"LLM é ferramenta, não cérebro"**

O UltronPro foi desenhado para operar cognitivamente **sem dependência de LLMs externos** para o fluxo principal. O sistema prioriza:

1. **Raciocínio simbólico** (sem custo, sem API)
2. **Cache semântico** (memória aprendida)
3. **Grafo causal** (conhecimento estruturado)
4. **Fallback progressivo** (escalada quando necessário)

---

## 2. Arquitetura de Lanes

O sistema usa **5 lanes especializadas** para diferentes tipos de tarefas:

| Lane | Nome | Provider | Model | Função | Max Tokens | Timeout |
|------|------|----------|-------|--------|------------|---------|
| **Lane 0** | Symbolic | Nenhum | - | Raciocínio determinístico, regras, math, fatos | 0 | 0s |
| **Lane 1** | Micro | Groq | llama-3.3-70b-versatile | Loops, housekeeping, triagem, resumos | 400 | 10s |
| **Lane 2** | Workhorse | Groq | llama-3.3-70b-versatile | Chat, RAG normal, planning | 300 | 12s |
| **Lane 3** | Judge | Anthropic | claude-3-5-sonnet-20241022 | Avaliação, revisão, promoção | 500 | 15s |
| **Lane 4** | Deep | DeepSeek | deepseek-reasoner | Raciocínio longo, debug difícil | 1000 | 25s |

---

## 3. Lane 0 - Symbolic (Sem LLM)

**Descrição**: Raciocínio puramente determinístico, sem dependência de LLMs.

### Arquivo: `local_reasoning_engine.py`

**Capacidades**:
- **Regras lógicas**: If-then, dedução, inferência
- **Matemática**: Operações básicas, equações simples
- **Fatos verificáveis**: Base de conhecimento de fatos conhecidos
- **Padrões simples**: Reconhecimento de padrões semânticos
- **Busca em grafo**: Relações entre conceitos

**Quando é usada**:
- Primeiro no pipeline do chat (Nível 1.5)
- Quando `lane_0` é explicitamente solicitada
- Para tarefas determinísticas que não precisam de LLM

**Vantagens**:
- Zero custo
- Latência mínima (< 100ms)
- Confiabilidade total (sem API)
- Disponível offline

---

## 4. Lane 1 - Micro (Groq)

**Descrição**: Tarefas rápidas, loops, housekeeping.

### Provider: Groq
- **Model**: `llama-3.3-70b-versatile`
- **max_tokens**: 400
- **timeout**: 10s

### Quando é chamada:

| Gatilho | Estratégia (no código) |
|---------|------------------------|
| Autonomy Loop | `autonomy_loop` → lane_1_micro |
| Reflexion Loop | `reflexion_loop` → lane_1_micro |
| Intrinsic Utility | `intrinsic_utility` → lane_1_micro |
| Qualia Update | `qualia_update` → lane_1_micro |
| Phenomenal Consciousness | `phenomenal_consciousness` → lane_1_micro |
| Housekeeping | `housekeeping` → lane_1_micro |
| Triagem | `triagem` → lane_1_micro |
| Health Check | `health_check` → lane_1_micro |
| Resumir | `summarize` → lane_1_micro |
| Roteamento | `routing` → lane_1_micro |

**Intervalo de uso**:
- Autonomy Loop: 300s (5 min)
- Reflexion Loop: 300s (5 min)
- Self-Improvement: 600s (10 min)

---

## 5. Lane 2 - Workhorse (Groq)

**Descrição**: Maioria das tarefas do sistema.

### Provider: Groq
- **Model**: `llama-3.3-70b-versatile`
- **max_tokens**: 300
- **timeout**: 12s

### Quando é chamada:

| Gatilho | Estratégia (no código) |
|---------|------------------------|
| Chat normal | `chat` → lane_2_workhorse |
| RAG normal | `rag` → lane_2_workhorse |
| Planning | `planning` → lane_2_workhorse |
| Análise | `analysis` → lane_2_workhorse |
| Anomalia detectada | `anomaly_detected` → lane_2_workhorse |
| Motor de raciocínio próprio (Nível 4) | `own_reasoning` → lane_2_workhorse |

**Uso principal**:
- No pipeline do chat, Nível 4 (fallback do motor de raciocínio próprio)
- Quando lanes 0, 1, 2 (cache) falham

---

## 6. Lane 3 - Judge (Anthropic)

**Descrição**: Avaliação, julgamento, decisões de promoção.

### Provider: Anthropic
- **Model**: `claude-3-5-sonnet-20241022`
- **max_tokens**: 500
- **timeout**: 15s

### Quando é chamada:

| Gatilho | Estratégia (no código) |
|---------|------------------------|
| Conflito persistente | `conflict_persistent` → lane_3_judge |
| Regressão | `regression` → lane_3_judge |
| Julgamento | `judge` → lane_3_judge |
| Avaliação | `evaluation` → lane_3_judge |
| Decisão de promoção | Promoção de patches |

**Casos de uso**:
- Judge Loop: julgamento de conflitos e decisões
- Promotion Gate: avaliação de patches para promoção
- Revisão de código/conflictos

---

## 7. Lane 4 - Deep (DeepSeek)

**Descrição**: Raciocínio profundo, tarefas complexas.

### Provider: DeepSeek
- **Model**: `deepseek-reasoner` (especializado em reasoning)
- **max_tokens**: 1000
- **timeout**: 25s

### Quando é chamada:

| Gatilho | Estratégia (no código) |
|---------|------------------------|
| Raciocínio complexo | `reasoning_complex` → lane_4_deep |
| Matemática/Simbólico | `math_symbolic` → lane_4_deep |
| Decisão estrutural | `structural_decision` → lane_4_deep |
| Replanejamento | `replanning` → lane_4_deep |
| Debug difícil | `debug_hard` → lane_4_deep |
| Raciocínio longo | `deep` → lane_4_deep |

**Casos de uso**:
- Self-Improvement Engine (revisão de estratégia)
- Tarefas que requieren reasoning chain longo

---

## 8. Fluxo do Chat (/api/chat)

```
INPUT: Mensagem do usuário
    ↓
[NÍVEL 1] Symbolic Pure (symbolic_reasoner)
    ↓ (falhar)
[NÍVEL 1.5] Local Reasoning (local_reasoning_engine)
    ↓ (falhar)
[NÍVEL 2] Semantic Cache
    ↓ (falhar)
[NÍVEL 3] Intent + Skills
    ↓ (falhar)
[NÍVEL 4] Motor de Raciocínio Próprio
    → Pode usar lane_2_workhorse (Groq) como fallback
    ↓ (falhar)
[NÍVEL 5] Fallback determinístico
OUTPUT: Resposta (+ relatório fenomenal)
```

**LLM usado no chat**: 
- **Lane 2 (Groq)** como fallback final no nível 4
- Sistema **prioriza métodos locais** antes de usar LLM

---

## 9. Sistema de Cache

### Configuração:
- **TTL**: 10 minutos
- **Tamanho**: 500 entries LRU
- **Arquivo**: `data/semantic_cache.db`

### Exceções (não usa cache):
Queries contendo palavras-chave de "novidade":
- `reflexion`
- `autonomy`
- `analyze`
- `review`
- `think about`

---

## 10. Circuit Breaker

### Configuração:
- **Threshold**: 3 falhas consecutivas
- **Cooldown**: 5 minutos
- **Limite diário**: 90% do budget → desativa automaticamente

### Arquivo: `llm.py`

---

## 11. Resumo de Chamadas por Loop

| Loop | Intervalo | Lane Usada | Provider |
|------|-----------|------------|----------|
| Autonomy Loop | 300s | lane_1_micro | Groq |
| Reflexion Loop | 300s | lane_1_micro | Groq |
| Judge Loop | 180s (event-driven) | lane_3_judge | Anthropic |
| Self-Improvement | 600s | lane_4_deep | DeepSeek |
| Chat (Nível 4) | Sob demanda | lane_2_workhorse | Groq |
| Inner Monologue | 15s | lane_0 (sem LLM) | Nenhum |

---

## 12. Variáveis de Ambiente

```bash
# Providers
ULTRON_GROQ_API_KEY=...
ULTRON_ANTHROPIC_API_KEY=...
ULTRON_DEEPSEEK_API_KEY=...

# Loops
ULTRON_AUTONOMY_TICK_SEC=300
ULTRON_REFLEXION_TICK_SEC=300
ULTRON_JUDGE_TICK_SEC=180

# Cache
ULTRON_CACHE_TTL_SEC=600

# Circuit Breaker
ULTRON_CIRCUIT_BREAKER_THRESHOLD=3
ULTRON_CIRCUIT_BREAKER_COOLDOWN_SEC=300
```

---

## 13. Status Atual

- **Pensamentos registrados**: 96+
- **Streak de successes**: 6
- **Cache LRU**: ~500 entries
- **Circuit Breaker**: Inativo (sem falhas recentes)

---

## 14. Próximas Melhorias

1. Adicionar mais gates de julgamento
2. Expandir local_reasoning_engine com mais regras
3. Monitorar custos por lane
4. Otimizar cache com embeddings