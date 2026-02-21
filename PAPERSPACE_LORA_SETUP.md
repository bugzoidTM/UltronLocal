# UltronPro LoRA no Paperspace (sem sobrecarregar a VPS)

## Objetivo
Executar o `trainer_api` no Paperspace e deixar a VPS apenas como orquestradora (envia jobs para remoto).

## 1) Subir Trainer API no Paperspace Notebook
No terminal do notebook (workspace UltronPro):

```bash
# dentro do notebook Paperspace
cd /notebooks
[ -d UltronPro ] || git clone <SEU_REPO_URL> UltronPro
cd UltronPro/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements-trainer.txt
# se quiser CUDA/GPU, ajuste torch conforme imagem GPU do notebook
```

Defina token de API e rode o servidor:

```bash
export TRAINER_API_TOKEN="troque-por-um-token-forte"
export PYTHONPATH=/notebooks/UltronPro/backend
uvicorn ultronpro.trainer_api:app --host 0.0.0.0 --port 8010
```

## 2) Expor endpoint HTTPS público
Use o recurso de app/port forwarding do Paperspace para a porta `8010`.
Você deve obter algo como:

`https://<seu-endpoint-publico>/train`

Teste:

```bash
curl -s https://<endpoint>/health
```

## 3) Apontar UltronPro (VPS) para o remoto
No serviço `ultronpro_ultronpro`, configurar variáveis:

- `ULTRON_FINETUNE_URL=https://<endpoint-publico>/train`
- `ULTRON_FINETUNE_TOKEN=<mesmo TRAINER_API_TOKEN>`

Depois reiniciar o serviço.

## 4) Verificação
No UltronPro:

- `GET /api/plasticity/finetune/auto/status`
- `POST /api/plasticity/finetune/auto/trigger`
- `GET /api/plasticity/finetune/status`

No remoto (Paperspace):

- `GET /jobs`
- `GET /jobs/{job_id}`

Com header:

`x-api-key: <TRAINER_API_TOKEN>`

## 5) Observações importantes
- Sem endpoint remoto válido, o UltronPro acumula `remote_error` (comportamento atual).
- Ideal: deixar `auto.enabled=false` até o endpoint Paperspace ficar estável.
- Recomendado usar modelo base que caiba na GPU/VRAM disponível no Paperspace.
