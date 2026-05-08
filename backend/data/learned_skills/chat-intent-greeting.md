# Chat intent greeting

## Resumo curto
Reconhecer e resolver rapidamente interacoes de chat do tipo greeting.

## Quando usar
Quando a mensagem do usuario se parece com exemplos anteriores bem-sucedidos dessa intencao.

## Instrucoes
Classifique a mensagem pela skill aprendida, responda por rota deterministica e registre o episodio. Use LLM apenas se a skill nao tiver confianca suficiente.

## Acao reutilizavel
- action_kind: intent_greeting
- status: promoted
- confidence: 0.960
- cognitive_status: transfer_stale
- transfer_status: stale
- transfer_score: 1.000

## Transfer Gate
- source_domain: chat_intent
- target_domains: session_context, surface_variation, voice_transcript
- pass_rate: 1.000

## Exemplos observados
- oi
- ola
