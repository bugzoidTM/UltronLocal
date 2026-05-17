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

## Exemplos observados
- oi
- ola
