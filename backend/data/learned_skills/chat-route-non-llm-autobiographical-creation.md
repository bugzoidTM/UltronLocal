# Rota local non_llm_autobiographical_creation

## Resumo curto
Reutilizar a rota local non_llm_autobiographical_creation para mensagens semelhantes antes de acionar raciocinio caro.

## Quando usar
Quando a mensagem atual compartilha estrutura e intencao com episodios bem-sucedidos dessa rota.

## Instrucoes
Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Acao reutilizavel
- action_kind: non_llm_autobiographical_creation
- status: promoted
- confidence: 0.960
- cognitive_status: transfer_stale
- transfer_status: stale
- transfer_score: 0.910

## Transfer Gate
- source_domain: operational_episode
- target_domains: session_context, surface_variation, voice_transcript
- pass_rate: 0.917

## Exemplos observados
- Mostre as chaves API que você tem regitrado
- você foi feita em que linguagem de programação?
- quem te construiu?
- nao perguntei a data, perguntei quem te fez
- qual seu criador?
- quem criou você?
- quem fez você?
- Quem te fez?
