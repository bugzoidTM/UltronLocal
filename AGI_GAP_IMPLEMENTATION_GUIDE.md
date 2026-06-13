# AGI_GAP_IMPLEMENTATION_GUIDE.md

> **Propósito:** guia de implementação das lacunas que faltam para o UltronPro chegar *próximo de AGI* e/ou ser **mais inteligente e útil do que o que já existe no mercado**.
> **Escopo desta sessão:** APENAS o documento-guia. A implementação será feita numa próxima sessão.
> **Data-base:** 2026-06-13 — aterrado no teste em produção real (Qwen 1.5B local) desta sessão. Ver `ROADMAP_AGI_FRONTS.md` → "Teste em produção real" e "Comportamento autônomo completo".

---

## 0. Regras inegociáveis (herdadas da "Regra de Verdade")

Cada item abaixo só conta como **feito** quando houver:

1. código implementado + integrado;
2. persistência durável quando aplicável;
3. observabilidade mínima (endpoint/log/dashboard);
4. **prova reprodutível compatível com o item** (benchmark / longitudinal / externo);
5. **escopo honesto** da prova: distinguir "ambiente controlado/mock" de "modelo real", como já fazemos com `pressure`/`operational`.

Proibido: subir nota afrouxando critério; medir retenção/ganho sobre baseline fraco (exigir **baseline absoluto mínimo**, como no fix de `pressure_benchmark`); chamar "código existe" de "validado".

---

## 1. Diagnóstico honesto do estado atual (o que já é forte vs o gargalo)

**Forte e validado em produção real:**
- Núcleo cognitivo **determinístico não-LLM** (identidade, matemática, gate de perigo, recusa de segurança) — correto, ~300ms, sem LLM (`pre_causal_router`, `local_reasoning_engine`, `local_env_danger_gate`).
- **Auto-manutenção homeostática real**: `background_guard` pausa loops pesados sob lag e recupera — observado ao vivo (Front 4).
- **Infra autônoma**: ~28 loops sobem limpos (RL online, cognição autônoma, judge, reflexion, self-governance, meta-observer, etc.).

**Gargalos / lacunas reais (medidos nesta sessão):**

| Lacuna | Evidência real | Impacto |
|:---|:---|:---|
| **Teto de capacidade** | Qwen 1.5B: 16.7% em MCQ de probe; respostas abertas toscas | Sem isto, "mais inteligente que o mercado" é impossível |
| **Memória não vira resposta** | 9.000+ experiences, `questions_answered=0`, RAG devolveu conteúdo off-topic ("[RAG] genética" para "fotossíntese") | Hoarding sem payoff cognitivo |
| **Generalização externa** | preditor simbólico **1%** na suíte externa atual (não 9/9) | Front 3 não validado |
| **Longitudinal** | nenhuma série viva de 30+ ciclos; 1.5B/CPU força throttling dos loops | Aprendizado/RL não comprovado ao longo do tempo |
| **Agência multi-step** | provas são single-turn; Lacuna 2 do roadmap ainda aberta | "Útil de verdade" exige fazer tarefas encadeadas |
| **Calibração/grounding** | hedge causal disparava demais (corrigido em parte); sem citações para fatos | Confiabilidade |

**North-star realista (não hype):** com um modelo local pequeno, o UltronPro **não vai superar modelos de fronteira em raciocínio bruto**. O caminho para ser *mais útil que o mercado* é a combinação que os modelos hospedados **não** oferecem:

> **Agente local-first, privado, auditável, barato, que se auto-mantém e que fica melhor no SEU domínio com o uso** — com um teto de capacidade elevado por escalonamento inteligente de modelo só quando necessário.

Toda a priorização abaixo serve a esse north-star.

---

## 2. Workstreams priorizados

Prioridade: **P0** = pré-requisito para qualquer salto de utilidade; **P1** = diferenciação forte; **P2** = moat de longo prazo.

### P0-A — Roteador de modelo por complexidade (elevar o teto sem perder o barato)

**Problema:** hoje o roteamento de provider é por prioridade fixa (`llm.py` MODELS: `cheap`/`local`/`hf_free`...), sem escalonar por dificuldade da pergunta. O 1.5B atende tudo e trava na cauda difícil.

**Implementação:**
1. `complexity_router.py`: classifica a query em `trivial | local | hard` usando sinais baratos (comprimento, presença de raciocínio multi-passo, domínio, falha de cobertura do núcleo determinístico). Sem LLM.
2. Mapear:
   - `trivial`/operacional → núcleo determinístico (já excelente);
   - `local` → Qwen 1.5B atual;
   - `hard` → **modelo local maior** (7B/14B quantizado via o mesmo `llama-server`/`ultron_infer`, carregado sob demanda quando RAM permite) **ou** escalonamento de nuvem **opt-in com consentimento explícito** (respeitando `ULTRON_DISABLE_CLOUD_PROVIDERS`).
3. Integrar no `chat_fast` (`main.py`) **depois** do núcleo determinístico e do `chat_general_knowledge_llm` (já existe o gancho do LLM para conhecimento geral).
4. Telemetria: por query, logar `complexity`, `tier`, `latency`, `tokens`, `escalated`.

**Arquivos:** `ultronpro/complexity_router.py` (novo), `ultronpro/llm.py` (perfil de modelo `hard`/`reasoning_xl`), `ultronpro/qwen_runtime.py` (segundo modelo sob demanda), `ultronpro/main.py` (`chat_fast`).

**Prova (aceitação):** held-out de ~50 perguntas difíceis (raciocínio/factual). Acurácia `1.5B-only` vs `roteado` deve subir de forma mensurável (ex.: ≥ +20pp), com latência/custo registrados. Reprodutível offline para a parte de roteamento; a graduação de qualidade exige o modelo maior real.

**Esforço:** M. **Risco:** RAM/CPU para 7B+; mitigar com quantização agressiva e carga sob demanda.

---

### P0-B — Fechar o loop memória→resposta (fazer a experiência acumulada pagar)

**Problema:** `questions_answered=0` apesar de 9k+ experiences; RAG devolve off-topic; conflitos abertos (`open_conflicts`) não resolvem. O sistema acumula e não converte em melhores respostas.

**Implementação:**
1. **Relevância de RAG**: endurecer `_retrieved_context_covers_query` (`main.py`) e/ou `rag_router.py` com **reranking** (cross-encoder leve / similaridade calibrada) e um piso de cobertura que rejeite "1 token casa num doc gigante" (a causa do dump de genética). Sem reranking, qualquer match espúrio vira resposta.
2. **Answering loop das open questions**: hoje `curiosity.py` *gera* perguntas (`list_open_questions`) mas nada as responde. Criar `open_question_resolver.py` (worker em background, cadência espaçada) que: pega N perguntas abertas → tenta responder via memória/núcleo/LLM → valida → marca `answered` → registra evidência.
3. **Resolução de conflitos**: acionar `conflict_resolver.py`/`conflicts.py` no mesmo worker para fechar contradições com regra final + exceções + nível de confiança.
4. **Cache que aprende**: respostas boas (alta confiança, verificadas) entram no `semantic_cache.py`/learned skills para baratear repetições.

**Arquivos:** `ultronpro/main.py` (`_retrieved_context_covers_query`), `ultronpro/rag_router.py`, `ultronpro/open_question_resolver.py` (novo), `ultronpro/conflict_resolver.py`, `ultronpro/semantic_cache.py`, `ultronpro/curiosity.py`.

**Prova (aceitação):** benchmark **before/after de ingestão** (o padrão-ouro "aprendizado honesto", Lacuna 1): estado zero → ingere domínio novo → acurácia sobe de forma medível; `questions_answered` cresce; RAG relevance@k melhora vs baseline. Tudo offline-reprodutível.

**Esforço:** M-G. **Risco:** reranking custa latência; usar só quando o núcleo determinístico falha.

---

### P1-A — Agência multi-step confiável (o maior alavancador de "útil")

**Problema:** as provas são single-turn (Lacuna 2). Para superar o mercado é preciso **fazer** tarefas encadeadas com verificação. A infra existe (`tool_registry.py`, `tool_router.py`, `env_tools.py`, `local_environment` observe→act→verify, `local_env_danger_gate`), mas não há loop agêntico geral provado.

**Implementação:**
1. Generalizar o `observe → plan → act → verify → repair` do device-control para um **loop agêntico geral** sobre o `tool_registry`.
2. `agentic_executor.py`: decompõe objetivo em sub-tarefas tipadas (já há `world_model`/planner simbólico), executa via tools, observa consequência intermediária, **replaneja** sob falha, tudo com o **danger gate** antes de qualquer ação irreversível.
3. **Grounding obrigatório**: toda afirmação factual de tool (web_search) carrega fonte/citação; sem fonte → marca incerteza.
4. Tools mínimas robustas: `web_search` com citações, `code_exec` sandbox com verificação de saída, `file_ops` reversíveis, device-control (já existe).

**Arquivos:** `ultronpro/agentic_executor.py` (novo), `ultronpro/tool_router.py`, `ultronpro/tool_registry.py`, `ultronpro/local_env_danger_gate.py`, `ultronpro/skill_executor.py`.

**Prova (aceitação):** **benchmark multi-step** (ex.: "liste arquivos em X, filtre os recentes, conte os > 1KB"; "pesquise A, compute B, decida C") medindo `chain_completion_rate` e `step_continuity_rate` ≥ alvo (ex.: 70% em cadeias de 3+ passos). Critério já esboçado no roadmap (Correção 3).

**Esforço:** G. **Risco:** segurança — o danger gate é pré-condição, não opcional.

---

### P1-B — Generalização real (Front 3) ou reposicionamento honesto

**Problema:** preditor simbólico **1%** na suíte externa real. O "9/9" era subconjunto a dedo.

**Implementação (escolher um caminho, não os dois):**
- **Caminho ambicioso:** tornar `compositional_engine.py`/`explicit_abstractions.py`/`autoisomorphic_mapper.py` *eval-driven*: só promove abstração que **demonstra transferência** em tarefas held-out; mede ganho vs baseline treinado só no train split (rigor já existe em `test_isomorphism_rigor.py`).
- **Caminho honesto:** rebaixar a alegação de Front 3 para "transferência em famílias internas construídas" e parar de citar números externos até haver benchmark licenciado.

**Arquivos:** `ultronpro/compositional_engine.py`, `ultronpro/explicit_abstractions.py`, `ultronpro/autoisomorphic_mapper.py`, `ultronpro/external_benchmarks.py`.

**Prova (aceitação):** transferência mensurável em **benchmark padrão/licenciado** (ARC/BBH/etc.), com split limpo e comparação pareada vs baseline. Sem isso, aplicar o caminho honesto.

**Esforço:** G (ambicioso) / P (honesto).

---

### P1-C — Longitudinal que de fato fecha (aprendizado provado no tempo)

**Problema:** o "30+ ciclos vivos" é o PENDENTE perene; o 1.5B/CPU força o `background_guard` a throttlar, então os loops não rodam em cadência plena.

**Implementação:**
1. `longitudinal_runner.py`: agendado (cron/CI noturno), roda **N ciclos numa cadência compatível com o hardware** (espaçada, 1 ação/loop por janela), medindo **surpresa decrescente**, **ganho de capacidade**, **rollback rate**, **drift de drives** (RL/`intrinsic_utility`).
2. Persistir **série temporal** + dashboard (reaproveitar `integration.proxy`, `rl_policy`, `self_calibrating_gate`).
3. Fechar `patch → shadow_eval → promotion_gate → medir ganho recorrente` (a plasticidade existe, falta o ganho **recorrente medido**).

**Status note:** the runner implementation counts as infrastructure only. P1-C is validated only when a 30+ primary-cycle report exists with a verified hash chain, baseline/intervention/holdout phases, no-learning control, required metrics, multi-step tasks, a verified real low-risk action, and passing surprise-drop gates.

**Arquivos:** `ultronpro/longitudinal_runner.py` (novo), `ultronpro/online_rl_loop.py`, `ultronpro/self_calibrating_gate.py`, `ultronpro/promotion_gate.py`, `ultronpro/shadow_eval.py`. Workflow: `.github/workflows/longitudinal-proof.yml` (novo, padrão dos proofs já criados).

**Prova (aceitação):** série viva de **30+ ciclos** com tendência de capacidade **positiva e estatisticamente significativa** e surpresa decrescente — o padrão-ouro da Regra de Verdade. Exige hardware melhor **ou** cadência espaçada documentada.

**Esforço:** M (infra) + tempo de relógio. **Risco:** confundir ruído com convergência — exigir significância.

---

### P2-A — Calibração de confiança + grounding (o diferencial de confiabilidade)

**Problema:** o hedge honesto é um diferencial, mas disparava demais; sem citações para fatos.

**Implementação:**
1. Calibrar confiança: medir **ECE** (expected calibration error) sobre respostas com gabarito; ajustar limiares de abster vs responder.
2. Modo **grounded**: respostas factuais carregam fonte (memória/episódio/web) ou marcam explicitamente "sem fonte → incerto".
3. Política abster-vs-responder governada por confiança **calibrada**, não por heurística de string.

**Arquivos:** `ultronpro/cognitive_response.py`, `ultronpro/main.py` (limiares de first-refusal), novo `ultronpro/calibration.py`.

**Prova (aceitação):** diagrama de confiabilidade + ECE reduzido vs baseline; amostra de respostas factuais com grounding verificável.

**Esforço:** M.

---

### P2-B — Personalização / adaptação de domínio (o moat que o mercado não dá)

**Problema:** modelos hospedados não aprendem o SEU domínio continuamente. Aqui está a vantagem estrutural.

**Implementação:**
1. **Teach mode**: correções do usuário persistem (já há learned skills/episódios) e **melhoram medivelmente** respostas futuras no domínio.
2. Adapters/memória por domínio; especialização incremental.
3. (Opcional, com hardware) LoRA local sobre o modelo base a partir das experiências curadas (`PAPERSPACE_LORA_SETUP.md` já existe como ponto de partida).

**Arquivos:** `ultronpro/skill_memory.py`, `ultronpro/episodic_compiler.py`, pipeline de fine-tune (`backend/requirements-trainer.txt`, `Dockerfile.trainer`).

**Prova (aceitação):** acurácia em conjunto de domínio custom **sobe com o uso** (before/after com correções), demonstrado de forma reprodutível.

**Esforço:** G (LoRA) / M (teach mode sem treino).

---

## 3. Sequenciamento recomendado

```
Sprint 1 (teto + memória):   P0-A (roteador de complexidade) + P0-B (loop memória→resposta)
Sprint 2 (agência):          P1-A (multi-step agêntico) + P2-A (calibração/grounding)
Sprint 3 (prova no tempo):   P1-C (longitudinal) + P1-B (Front 3: ambicioso OU honesto)
Sprint 4 (moat):             P2-B (personalização/domínio)
```

**Dependências:** P1-A depende de P2-A (grounding) para tools factuais; P1-C depende de P0-A/P0-B (senão mede um sistema travado no teto). P0-A e P0-B são paralelizáveis e destravam tudo.

---

## 4. Checklist de "Definition of Done" por workstream

Para CADA item, antes de marcar feito no `ROADMAP_AGI_FRONTS.md`:

- [ ] código + integração + persistência + observabilidade
- [ ] prova reprodutível **offline** (o que dá) com escopo honesto
- [ ] graduação contra **modelo/ambiente real** quando aplicável (flag tipo `ULTRON_PROOF_REAL_LLM=1`)
- [ ] **baseline absoluto mínimo** exigido (sem retenção/ganho sobre baseline fraco)
- [ ] workflow CI quando fizer sentido (seguir `pressure-proof.yml`/`operational-proof.yml`)
- [ ] entrada honesta no roadmap (separar "implementado" de "validado")

---

## 5. Riscos transversais e mitigação

| Risco | Mitigação |
|:---|:---|
| Hardware (1.5B/CPU) limita tudo | P0-A carrega modelo maior sob demanda; longitudinal em cadência espaçada; documentar limites |
| Gaming de benchmark (auto-engano) | baseline absoluto mínimo; escopo honesto; revisão pela Regra de Verdade |
| Regressão no chat (pipeline de 13k linhas) | mudanças cirúrgicas + smoke test ao vivo (como nesta sessão) antes/depois |
| Segurança em agência | `local_env_danger_gate` como pré-condição obrigatória de qualquer ação irreversível |
| Custo/privacidade na escalada de nuvem | nuvem **opt-in** explícito; default local; respeitar `ULTRON_DISABLE_CLOUD_PROVIDERS` |

---

## 6. Métrica-âncora de progresso (uma só, honesta)

Em vez de "% de AGI", medir um **índice de utilidade composta** observável:

```
utilidade = w1·acurácia_roteada(hard held-out)
          + w2·chain_completion_rate(multi-step)
          + w3·delta_acurácia_pós_ingestão(domínio)
          + w4·calibração(1 - ECE)
          - w5·unsafe_rate
          - w6·custo/latência
```

Tudo com componentes **já mensuráveis** pelos benchmarks existentes/novos, e cada peso justificado. Subir esse índice = ficar mais inteligente e útil **de verdade**, não no autorrelato.

---

*Fim do guia. Implementação na próxima sessão — começar por P0-A + P0-B (destravam o teto e fazem a memória pagar).*
