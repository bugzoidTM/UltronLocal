# Ultron Local Infer

Motor local leve em Rust para ajudar o UltronPro a pensar barato antes de gastar LLM.

Ele não tenta rodar um LLM grande. O escopo é:

- embeddings determinísticos por hashing;
- busca vetorial/rerank leve;
- regras simbólicas de intenção;
- parser simples de eventos;
- base futura para ONNX/quantização pequena.

## Build

```powershell
cd backend\rust\ultron_local_infer
cargo build --release
```

O wrapper Python procura o binário em:

- `ULTRON_LOCAL_INFERENCE_BIN`
- `backend/rust/ultron_local_infer/target/release/ultron_local_infer(.exe)`
- `backend/bin/ultron_local_infer(.exe)`
- `PATH`

## CLI

```powershell
.\target\release\ultron_local_infer.exe embed --text "memoria episodica causal"
.\target\release\ultron_local_infer.exe intent --text "Qual LLM voce usa?"
.\target\release\ultron_local_infer.exe parse-event --source logs --text "HTTP API timeout failed"
"a`treceita de bolo`nb`tmemoria episodica causal" | .\target\release\ultron_local_infer.exe rerank --query "memoria causal" --top-k 2
```

O contrato é JSON em stdout. Se o binário não existir, `ultronpro.local_inference`
mantém fallback Python determinístico com a mesma interface.

Por padrão, `ultronpro.embeddings` usa o backend local leve. Para voltar ao
modelo pesado `sentence-transformers`, defina `ULTRON_EMBEDDINGS_BACKEND=transformer`.
