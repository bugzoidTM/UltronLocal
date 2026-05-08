# Rota local non_llm_autobiographical_identity

## Resumo curto
Reutilizar a rota local non_llm_autobiographical_identity para mensagens semelhantes antes de acionar raciocinio caro.

## Quando usar
Quando a mensagem atual compartilha estrutura e intencao com episodios bem-sucedidos dessa rota.

## Instrucoes
Usar a rota local aprendida se a similaridade for suficiente; registrar uso e continuar o pipeline normal se houver baixa confianca.

## Acao reutilizavel
- action_kind: non_llm_autobiographical_identity
- status: promoted
- confidence: 0.960
- cognitive_status: transfer_stale
- transfer_status: stale
- transfer_score: 0.712

## Transfer Gate
- source_domain: operational_episode
- target_domains: session_context, surface_variation, voice_transcript
- pass_rate: 0.667

## Exemplos observados
- me diga quem voce e
- qual e a sua identidade registrada
- qual seu nome?
- mas seu fundador tem um nome?
- como é seu nome?
- mas qual o nome de quem te criou?
- você nao sabe o nome de quem te fez?
