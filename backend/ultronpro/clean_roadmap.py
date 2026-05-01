import re

filepath = r'f:\sistemas\UltronPro\ROADMAP_AGI_FRONTS.md'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

target = r"""## 7.3 Fallback de linguagem offline (Gemma 3-1B)
_Status: [FEITO]_

Arquitetura de loop local ("Self-Thinking Loop - Evolution Fase 7"):
1. **World Model Keeper (Gemma 3-1B)**: Decompõe o objetivo em um `ExecutionPlan` estruturado. [FEITO]
2. **Symbolic Router**: Classifica a suficiência local para cada step usando o `self_model`. [FEITO]
3. **Multi-Model Execution**: Roteia steps para local (Gemma) ou externo (Specialist/Backbone) conforme auditoria. [FEITO]
4. **Local Evaluator (Gemma 3-1B)**: Analisa o resultado (Sucesso? Escalar? Repetir?). [FEITO]

- [FEITO] Integrar Gemma 3-1B via Ollama/Local Inference
- [FEITO] Implementar o "Local Planner" para triagem de complexidade
- [FEITO] Implementar o "Local Evaluator" para validação de output
- [FEITO] Garantir persistência do loop de pensamento (ticks) em modo offline via `local_reasoning.py`"""

replacement = r"""## 7.3 Erradicação de Roteamento Baseado em Modelo (Golden Rule)
_Status: [FEITO]_

Implementação do código determinístico de acordo com a Regra de Ouro ("O que pode ser código, será código"):
1. **World Model Keeper (Determinístico)**: Decompõe o objetivo em steps usando parsers de linguagem. [FEITO]
2. **Symbolic Router**: Avalia se pode ser resolvido com regras usando o `self_model`. [FEITO]
3. **Model Execution**: Roteamento totalmente simbólico sem uso de LLM para orquestrar LLM. [FEITO]
4. **Code Evaluator**: Valida resultados usando análise estrutural pura. [FEITO]

- [FEITO] Desinstalar Ollama/Local Inference para liberar overhead do HostOS
- [FEITO] Substituir "Local Planner" abstrato por heurísticas de código (Regex, Domains)
- [FEITO] Substituir "Local Evaluator (Gemma)" por testes determinísticos sintáticos
- [FEITO] Limpar dependências e fallback `ollama_local` em todo o motor cognitivo"""

content = content.replace(target, replacement)
# Try regex if exact string is slightly off due to CRLF
content = re.sub(r'## 7\.3 Fallback.*?\bvia `local_reasoning\.py`', replacement, content, flags=re.DOTALL)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Done")
