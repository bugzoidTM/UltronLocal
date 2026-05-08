# Rota local non_llm_runtime_model

## Resumo curto
Reutilizar a rota local non_llm_runtime_model para mensagens semelhantes antes de acionar raciocinio caro.

## Quando usar
Quando a mensagem atual compartilha estrutura e intencao com episodios bem-sucedidos dessa rota.

## Instrucoes
Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Acao reutilizavel
- action_kind: non_llm_runtime_model
- status: promoted
- confidence: 0.800
- cognitive_status: local_only
- transfer_status: failed
- transfer_score: 0.910

## Transfer Gate
- source_domain: operational_episode
- target_domains: session_context, surface_variation, voice_transcript
- pass_rate: 0.800

## Exemplos observados
- Qual LLM você está usando para me responder?
