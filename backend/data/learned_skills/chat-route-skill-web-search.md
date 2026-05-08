# Reutilizar skill web_search

## Resumo curto
Roteamento aprendido para reutilizar a skill web_search antes de RAG/LLM.

## Quando usar
Quando a tarefa atual combina com exemplos anteriores que foram resolvidos por essa skill.

## Instrucoes
Consultar e executar a skill web_search; se falhar, continuar o pipeline cognitivo normal.

## Acao reutilizavel
- action_kind: skill_web_search
- status: promoted
- confidence: 0.800
- cognitive_status: transfer_validated
- transfer_status: validated
- transfer_score: 1.000

## Transfer Gate
- source_domain: tool_route
- target_domains: session_context, surface_variation, voice_transcript
- pass_rate: 1.000

## Exemplos observados
- Eu pedi suas chaves de api
