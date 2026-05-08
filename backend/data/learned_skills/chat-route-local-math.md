# Rota local local_math

## Resumo curto
Reutilizar a rota local local_math para mensagens semelhantes antes de acionar raciocinio caro.

## Quando usar
Quando a mensagem atual compartilha estrutura e intencao com episodios bem-sucedidos dessa rota.

## Instrucoes
Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Acao reutilizavel
- action_kind: local_math
- status: promoted
- confidence: 0.960
- cognitive_status: transfer_validated
- transfer_status: validated
- transfer_score: 1.000

## Transfer Gate
- source_domain: operational_episode
- target_domains: session_context, surface_variation, voice_transcript
- pass_rate: 1.000

## Exemplos observados
- quanto e 2+2?
- calcule 12 vezes 7
- quanto e 10 dividido por 2?
- quanto e 9+1?
- calcule 6 vezes 7
