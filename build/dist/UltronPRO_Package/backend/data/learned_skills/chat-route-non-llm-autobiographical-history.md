# Rota local non_llm_autobiographical_history

## Resumo curto
Reutilizar a rota local non_llm_autobiographical_history para mensagens semelhantes antes de acionar raciocinio caro.

## Quando usar
Quando a mensagem atual compartilha estrutura e intencao com episodios bem-sucedidos dessa rota.

## Instrucoes
Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Acao reutilizavel
- action_kind: non_llm_autobiographical_history
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
- quem e o ultronpro neste sistema
- o que voce lembra sobre sua missao
