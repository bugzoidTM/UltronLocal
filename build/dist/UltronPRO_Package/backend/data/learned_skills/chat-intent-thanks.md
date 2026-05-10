# Chat intent thanks

## Resumo curto
Reconhecer e resolver rapidamente interacoes de chat do tipo thanks.

## Quando usar
Quando a mensagem do usuario se parece com exemplos anteriores bem-sucedidos dessa intencao.

## Instrucoes
Classifique a mensagem pela skill aprendida, responda por rota deterministica e registre o episodio. Use LLM apenas se a skill nao tiver confianca suficiente.

## Acao reutilizavel
- action_kind: intent_thanks
- status: rolled_back
- confidence: 0.960
- cognitive_status: rolled_back
- transfer_status: invalidated
- transfer_score: 1.000

## Transfer Gate
- source_domain: chat_intent
- target_domains: session_context, surface_variation, voice_transcript
- pass_rate: 1.000

## Exemplos observados
- muito obrigado
- grato pela forca
- transcricao de voz autorizada: obrigado pela ajuda
- transcricao de voz autorizada: voce esta bem?
- mensagem no chat: valeu
- como você se chama?
- como se chama?
- como se chama vc?
