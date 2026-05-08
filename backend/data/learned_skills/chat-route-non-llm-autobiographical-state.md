# Rota local non_llm_autobiographical_state

## Resumo curto
Reutilizar a rota local non_llm_autobiographical_state para mensagens semelhantes antes de acionar raciocinio caro.

## Quando usar
Quando a mensagem atual compartilha estrutura e intencao com episodios bem-sucedidos dessa rota.

## Instrucoes
Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Acao reutilizavel
- action_kind: non_llm_autobiographical_state
- status: promoted
- confidence: 0.960
- cognitive_status: transfer_validated
- transfer_status: validated
- transfer_score: 1.000

## Transfer Gate
- source_domain: operational_episode
- target_domains: lexical_abstraction, session_context, surface_variation, voice_transcript
- pass_rate: 1.000

## Exemplos observados
- resuma seu estado operacional atual
- qual e seu estado operacional agora
- como esta seu estado cognitivo operacional
- resuma sua situacao interna atual
