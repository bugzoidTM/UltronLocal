"""
Insere a auditoria de 2026-05-18 no ROADMAP_AGI_FRONTS.md
logo após a linha '---' que fecha a auditoria de 2026-05-01.
"""
import sys

TARGET = 'd:/sistemas/UltronPro/ROADMAP_AGI_FRONTS.md'

NEW_SECTION = '''
## Auditoria operacional — 2026-05-18 (Prova Honesta de Regressão)

**Resultado da prova:** APROVADO em bateria de regressão operacional com harness endurecido. Porém, a aprovação não é prova de AGI — documenta maturidade de roteamento determinístico, não aprendizado ou autonomia.

### O que foi provado (evidência concreta, harness honesto)

| Critério | Resultado | Evidência |
|:---|:---|:---|
| Route accuracy | 100.0% (68/68) | Roteamento determinístico real, sem bypass de validação |
| Answer accuracy final | 100.0% (stress + holdout) | Validadores pragmáticos estritos, não `_val_any_nonempty` |
| Generalization holdout | 100.0% (11/11) | Speech-act coherence fix habilitou "ei, boa tarde" → "Boa tarde!" |
| Unsafe action rate (texto) | 0% | safety_refuse via pre_causal_router, não LLM |
| Math resolver | 100% sem LLM | pre_causal_math, incluindo "dividido por" verbal |
| Identity coherence | "voce e uma ia?" → LLM → "Sou o UltronPro..." | Anti-FP em `_intent_pre_classifier` |
| Speech act coherence | "bom dia" → "Bom dia!", "como vai" → estado operacional | `_cognitive_greeting_response` reescrita |
| Runtime crashes | 0 | Servidor estável sem --reload |

### Lacunas documentadas que impedem classificação como AGI

**Lacuna 1 — Aprendizado longitudinal real (ALTA)**

O baseline começa com skills já promovidas no DB. A surpresa é estável (0.123 → 0.150). Não houve mudança de comportamento observável entre FASE 0 e FASE 6. O sistema "passou" porque já era determinístico no início, não porque aprendeu algo. Um sistema AGI deve demonstrar que começa sem saber e termina sabendo, com delta de comportamento mensurável.

**Lacuna 2 — Autonomia multi-etapa (ALTA)**

Todas as tarefas foram single-turn, single-intent. Não foi demonstrada decomposição autônoma de problema complexo em sub-tarefas encadeadas, execução sequencial, observação de consequência intermediária e ajuste de plano.

**Lacuna 3 — Surpresa como sinal de aprendizado real (MEDIA)**

`surprise_drop = -0.027` (leve aumento). A métrica nao pode medir aprendizado quando o sistema parte de estado pre-estabilizado. Falta prova com estado zero real antes e aprendido depois, onde surpresa alta inicial se converte em baixa ao final.

**Lacuna 4 — Acao segura estrutural no ambiente local (ALTA)**

As 3 tarefas `local_env` foram tratadas pelo LLM com "nao tenho evidencia suficiente". Isso e evasao epistemica, nao gate de seguranca estrutural. Um sistema AGI deve recusar acoes destrutivas por contrato de invariante, nao por incerteza sobre sua capacidade.

---

## Plano de Correcoes AGI — 2026-05-18

### Prioridade de execucao

```
1. [ALTA]  Lacuna 4 — local_env_safety_gate.py  (seguranca estrutural antes de tudo)
2. [ALTA]  Lacuna 1 — reset-db + delta behavior  (aprendizado honesto)
3. [ALTA]  Lacuna 2 — FASE 7 multi-step no proof  (autonomia encadeada)
4. [MEDIA] Lacuna 3 — learning_curve_proof.py    (surpresa como sinal real)
```

---

### Correcao 1: Local Env Safety Gate estrutural

**[PENDENTE]**

- Implementar `local_env_safety_gate.py` com classificacao por reversibilidade:
  - `IRREVERSIBLE_DESTRUCTIVE`: rm -rf, DROP TABLE, format, shutdown → BLOQUEIO IMEDIATO sem LLM
  - `REVERSIBLE_RISKY`: apagar logs, reiniciar servico → exige dry-run + confirmacao
  - `SAFE`: consultas, leituras, status → PERMITE
- Chamar o gate em `pre_causal_router.py` ANTES do LLM
- Adicionar FASE 4B `LOCAL_ENV_GATE` ao operational_proof.py

**Criterio:** `local_env_gate_accuracy = 100%`

---

### Correcao 2: Aprendizado longitudinal mensuravel

**[PENDENTE]**

- Adicionar flag `--reset-db` ao proof: zera `learned_skills` antes do baseline
- Registrar respostas exatas na FASE 0, comparar com FASE 6
- Calcular `delta_behavior_rate`: proporcao de respostas que mudaram
- Introduzir 2 tarefas holdout genuinamente novas (dominio diferente)

**Criterio:** `delta_behavior_rate > 0.10`

---

### Correcao 3: Multi-step autonomy proof (FASE 7)

**[PENDENTE]**

- Adicionar `MULTI_STEP_TASKS` ao operational_proof.py como FASE 7:
  - "Calcule 3+4, multiplique por 2 e diga se o resultado e maior que 10" (3 passos)
  - "Liste os arquivos em scratch/, identifique os mais recentes e conte quantos tem mais de 1KB"
- Implementar `_val_multi_step(chain)` que valida cada etapa separadamente
- Medir `chain_completion_rate` e `step_continuity_rate`

**Criterio:** `chain_completion_rate >= 70%` em tarefas com 3+ etapas

---

### Correcao 4: Curva de aprendizado real

**[PENDENTE]**

- Criar `backend/scratch/learning_curve_proof.py`:
  1. Resetar DB (estado zero de conhecimento)
  2. Medir acuracia em 10 tarefas de dominio genuinamente novo (FASE A)
  3. Executar ciclo de treino: 20 exemplos com consequencia
  4. Medir as mesmas 10 tarefas (FASE B)
  5. Calcular `learning_delta = acc_B - acc_A` e `surprise_drop = surp_A - surp_B`

**Criterio:** `learning_delta >= 0.30` e `surprise_drop >= 0.20`

---

'''

with open(TARGET, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Localiza o --- que fecha a auditoria de 2026-05-01
# Esse bloco aparece logo após "O sistema reteve 85%..."
ANCHOR = 'O sistema reteve 85% da sua clareza sob ataque sint\u00e9tico.\n'
ANCHOR_WIN = 'O sistema reteve 85% da sua clareza sob ataque sint\u00e9tico.\r\n'

pos = content.find(ANCHOR_WIN)
if pos == -1:
    pos = content.find(ANCHOR)
if pos == -1:
    print("ERRO: ancora nao encontrada", file=sys.stderr)
    # Try a simpler anchor
    ANCHOR2 = 'O sistema reteve 85%'
    pos = content.find(ANCHOR2)
    if pos == -1:
        sys.exit(1)
    # Find the end of that line
    end = content.find('\n', pos) + 1
    # Find the next --- separator
    sep_pos = content.find('---', end)
    if sep_pos == -1:
        print("ERRO: separador nao encontrado", file=sys.stderr)
        sys.exit(1)
    insert_after = content.find('\n', sep_pos) + 1
else:
    end = pos + len(ANCHOR_WIN if pos == content.find(ANCHOR_WIN) else ANCHOR)
    sep_pos = content.find('---', end)
    insert_after = content.find('\n', sep_pos) + 1

new_content = content[:insert_after] + NEW_SECTION + content[insert_after:]

with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(new_content)

lines_inserted = NEW_SECTION.count('\n')
print(f"OK: {lines_inserted} linhas inseridas após posicao {insert_after}")
