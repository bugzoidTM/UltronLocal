# UltronPro

UltronPro é uma plataforma de agente cognitivo/autônomo para operação técnica contínua: observar, decidir, aprender, executar, auditar e se reorganizar com segurança operacional.

Hoje o projeto está em uma fase importante de transição:

- o caminho principal de metacog saiu do **Qwen remoto no U1**,
- o router ganhou **provider nativo Gemini**,
- `judge`, `reflexion`, `roadmap`, `agi_path` e `autonomy` rodam em **serviços separados**,
- o sistema está sendo endurecido para **evoluir sozinho sem se auto-sabotar**.

---

## Estado atual real

### O que já está funcionando
- **Gemini como provider principal** do fluxo de `/api/metacognition/ask`
- **Router multi-provider** com telemetria, health e fallback controlado
- **Serviços separados** para:
  - `ultronpro` (control plane / API / UI)
  - `ultronpro_autonomy`
  - `ultronpro_judge`
  - `ultronpro_reflexion`
  - `ultronpro_roadmap`
  - `ultronpro_agi_path`
- **RAG / busca semântica / cache semântico**
- **Memória e traces persistidos** em `/app/data`
- **Patch loop / benchmark / promotion gate / rollback manager**
- **Teacher feedback** vindo do ecossistema OpenClaw

### O que está em endurecimento
- autonomia longitudinal com cadência segura
- autoalimentação (`autofeeder`) sem gerar ruído excessivo
- estabilidade dos workers após a migração para Gemini
- consolidação de roadmap/agi-path como laços de evolução contínua

### O que foi despriorizado/abandonado como caminho principal
- **U1 / Ollama / Qwen** como inferência principal interativa
- uso do `ultron_infer`/`ollama_local` no caminho primário do chat
- fallbacks cloud quebrados que estavam só piorando latência e erro

---

## Arquitetura

### 1. Control plane
Arquivo principal:
- `backend/ultronpro/main.py`

Responsável por:
- API FastAPI
- UI servida pelo backend
- roteamento metacognitivo
- traces, memória, governança, benchmark, patching
- health/status/usage

### 2. Router LLM
Arquivos centrais:
- `backend/ultronpro/llm.py`
- `backend/ultronpro/llm_adapter.py`
- `backend/ultronpro/settings.py`

Providers suportados no código atual:
- `gemini`
- `openai`
- `anthropic`
- `groq`
- `deepseek`
- `openrouter`
- `huggingface`
- `ollama_local`
- `ultron_infer`

**Estado operacional recomendado hoje:**
- principal: `gemini`
- `ollama_local` e `ultron_infer`: desabilitados no caminho primário
- `openrouter` e `deepseek`: manter desligados se estiverem quebrados ou sem crédito/modelo útil

### 3. Loops autônomos
Serviços separados para evitar acoplamento excessivo do plano principal:
- `autonomy_worker`
- `judge_worker`
- `reflexion_worker`
- `roadmap_worker`
- `agi_path_worker`

Isso reduz competição desnecessária dentro do processo principal e facilita calibração de cadência/timeout por loop.

### 4. Memória, RAG e observabilidade
- cache semântico
- semantic search
- decision traces
- replay
- PRM-lite observacional
- stores locais em `/app/data`

---

## Provider principal: Gemini

### Motivação
O Qwen remoto no U1 estava funcional, mas:
- lento para requests triviais
- frágil sob concorrência leve
- causando timeout no chat e nos workers

Gemini 3 Flash Preview se mostrou muito mais responsivo no uso real.

### Variáveis principais
Exemplo de configuração operacional:

```env
ULTRON_PRIMARY_LOCAL_PROVIDER=gemini
ULTRON_CANARY_PROVIDER=gemini
GEMINI_DEFAULT_MODEL=gemini-3-flash-preview
GEMINI_API_KEY=AIza...

ULTRON_DISABLE_OLLAMA_LOCAL=1
ULTRON_DISABLE_ULTRON_INFER=1
ULTRON_DISABLE_OPENROUTER=1
ULTRON_DISABLE_DEEPSEEK=1

ULTRON_LLM_ROUTER_TIMEOUT_SEC=15
ULTRON_LLM_COMPAT_TIMEOUT_SEC=25
ULTRON_PROVIDER_FAILURE_COOLDOWN_SEC=180
ULTRON_GEMINI_FAILURE_COOLDOWN_SEC=15
```

### Notas operacionais
- `429` do Gemini não deve virar quarentena persistente longa
- cooldown curto é melhor que banimento implícito do provider
- workers precisam usar ticks conservadores para não se atropelarem

---

## Serviços no Swarm

Stack principal em:
- `deploy/docker-stack.swarm.yml`

Serviços esperados:
- `ultronpro_ultronpro`
- `ultronpro_ultronpro_autonomy`
- `ultronpro_ultronpro_judge`
- `ultronpro_ultronpro_reflexion`
- `ultronpro_ultronpro_roadmap`
- `ultronpro_ultronpro_agi_path`

### Estratégia atual de cadência
Recomendação prática atual:
- `autonomy`: ligado, cadência moderada, orçamento baixo porém útil
- `judge`: ligado, tick conservador
- `reflexion`: ligado, tick conservador
- `roadmap`: ligado em worker separado
- `agi_path`: ligado em worker separado
- `autofeeder`: ligado com tick mais lento para não gerar ruído artificial

---

## Endpoints importantes

### Metacognição / LLM
- `POST /api/metacognition/ask`
- `GET /api/llm/health`
- `GET /api/llm/usage`
- `GET /api/settings`
- `POST /api/settings`

### RAG / busca
- `POST /api/search/semantic`
- `GET /api/rag/router`
- `POST /api/rag/eval`
- `GET /api/rag/eval/runs`

### Plasticidade / benchmark / governança
- `POST /api/plasticity/finetune/jobs`
- `POST /api/plasticity/finetune/jobs/{id}/start`
- `GET /api/plasticity/finetune/jobs/{id}/progress`
- `POST /api/plasticity/finetune/notify-complete`

### Professor OpenClaw
- `POST /api/openclaw/teacher/feedback`

---

## Desenvolvimento local

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn ultronpro.main:app --host 0.0.0.0 --port 8000
```

### Docker build
```bash
cd backend
docker build -t ultronpro_backend:local .
docker build -t ultronpro:local .
```

### Swarm deploy
```bash
docker stack deploy -c deploy/docker-stack.swarm.yml ultronpro
```

---

## Roadmap e maturidade

Roadmap vivo:
- `ROADMAP_AGI_FRONTS.md`

O roadmap não é decorativo. Ele deve ser atualizado sempre que houver:
- implementação real
- integração funcional
- observabilidade mínima
- evidência operacional/benchmark suficiente

No estado atual, os fronts mais fortes são:
- plasticidade estrutural
- generalização entre domínios

E os que mais estão recebendo atenção operacional agora são:
- automanutenção / individuação
- consciência operacional integrada

Principal motivo:
- estabilizar o sistema para **trabalhar sozinho sem travar, sem esquecer autoria, sem degradar a própria capacidade futura**.

---

## Filosofia operacional

UltronPro não deve ser só “um chat com ferramentas”.
A meta é um sistema que consiga:
- observar o próprio estado
- manter continuidade
- aprender com falha
- reorganizar estratégias
- propor mudanças estruturais
- validar antes de promover
- preservar integridade enquanto continua útil

Em resumo:
**um agente técnico que não apenas responde, mas mantém operação, evolução e memória com governança.**

---

## Observações honestas

O projeto ainda não está “pronto” nem “10/10”.
Mas já passou da fase de demo superficial.

Hoje ele já tem:
- loops cognitivos reais
- memória e replay
- patching e rollback
- benchmark e gates
- provider principal cloud funcional
- arquitetura suficiente para continuar endurecendo em produção

O trabalho atual é menos “inventar features” e mais:
- tirar acoplamentos ruins
- calibrar cadência
- evitar auto-sabotagem por fallback/timeout/quarentena
- aumentar evidência longitudinal

---

## Repositório

Remote principal:
- `git@github.com:bugzoidTM/UltronPro.git`

Se este README estiver desatualizado em relação ao deploy, o deploy está certo e o README está errado — então atualize o README.
