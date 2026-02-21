# UltronPro Roadmap V5 — 80% rumo à AGI plena

## Objetivo
Elevar o UltronPro de ~35% para ~80% de maturidade AGI-like com foco em:
- segurança e auditabilidade,
- autonomia de longo horizonte,
- aprendizado contínuo (runtime + paramétrico),
- custo sustentável em VPS.

---

## Fase 1 — Confiabilidade Cognitiva (35% → 50%)

### Metas
1. Eval Harness contínuo por domínio (lógica, código, matemática, factualidade, planejamento).
2. Calibração forte: ECE/Brier e bloqueio para ações críticas com risco alto.
3. Observabilidade unificada: sucesso, alucinação, rollback, bloqueios, latência.
4. Higiene de memória: deduplicação, aging policy, distill com checkpoints.

### Critério de saída
- regressão < 5% por sprint,
- erro crítico < 2%,
- dashboard com KPIs semanais automáticos.

---

## Fase 2 — Aprendizado Paramétrico Direcionado (50% → 62%)

### Metas
1. LoRA/QLoRA por competência (grounding, conflitos, planejamento, coding).
2. Gate de promoção A/B automático (min_gain e baseline).
3. Adapter routing por task_type com fallback seguro.
4. Replay curriculum (hard cases → dataset prioritário).

### Critério de saída
- +15–25% nas tarefas-alvo,
- redução de token/custo para competências nucleares,
- zero promoção sem validação.

---

## Fase 3 — Agência de Longo Horizonte (62% → 72%)

### Metas
1. Mission engine robusto: dependências, replanejamento, deadlines, bloqueios.
2. World model causal com previsão de impacto e risco pré-ação.
3. Self-repair operacional (detectar degradação e executar rota de recuperação).
4. Cron + heartbeat híbrido por SLA.

### Critério de saída
- execução confiável de projetos multi-dia com baixa intervenção humana,
- taxa de tarefas concluídas com qualidade > 80%.

---

## Fase 4 — Meta-Raciocínio e Generalização (72% → 80%)

### Metas
1. Meta-controller de compute (cheap/balanced/deep/deep-think por valor esperado).
2. MCTS + antítese obrigatório para classe crítica.
3. Transfer cross-domain com validação empírica.
4. Constituição operacional de segurança (regras imutáveis + auditoria).

### Critério de saída
- desempenho estável em tarefas inéditas,
- redução de falhas em ambientes abertos,
- custo por decisão crítica otimizado.

---

## KPIs de Governança (globais)
- Critical Error Rate
- Hallucination Rate
- Calibration (ECE/Brier)
- Task Completion Quality
- Mean Time to Recovery
- Cost per Successful Outcome
- Adapter Promotion Precision

---

## Cadência sugerida
- Mês 1: Fase 1
- Mês 2: Fase 2
- Mês 3: Fase 3
- Mês 4: Fase 4 + hardening

---

## Observações
- Segurança sempre precede autonomia.
- Promoções paramétricas exigem evidência A/B.
- Deep-think e ações críticas devem manter gate de governança/calibração.
