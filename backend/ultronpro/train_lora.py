from __future__ import annotations

import argparse
import json
import time
import signal
import logging
import os
from contextlib import contextmanager
from pathlib import Path

import httpx

from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer, DataCollatorForLanguageModeling, TrainerCallback, EarlyStoppingCallback, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, TaskType, prepare_model_for_kbit_training


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def timeout_handler(signum, frame):
    raise TimeoutError('Operação excedeu timeout de 5 minutos')


@contextmanager
def _timeout(sec: int, label: str):
    sec = max(1, int(sec or 1))

    def _handler(signum, frame):
        raise TimeoutError(f"timeout in {label} after {sec}s")

    prev = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(sec)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)


def _notify_control_plane(adapter_out: str, notes: str = 'notify_from_train_lora') -> dict:
    job_id = Path(str(adapter_out or '')).name.strip()
    if not job_id.startswith('ft_'):
        return {'ok': False, 'error': 'job_id_not_inferred', 'job_id': job_id}

    url = str(os.getenv('ULTRON_FINETUNE_NOTIFY_URL', 'http://ultronpro:8000/api/plasticity/finetune/notify-complete')).strip()
    token = str(os.getenv('ULTRON_FINETUNE_NOTIFY_TOKEN', '')).strip()
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['x-api-key'] = token

    payload = {
        'job_id': job_id,
        'adapter_out': str(adapter_out or ''),
        'notes': str(notes or '')[:200],
    }

    try:
        with httpx.Client(timeout=8.0) as hc:
            r = hc.post(url, headers=headers, json=payload)
            r.raise_for_status()
            js = r.json() if r.text else {'ok': True}
        return {'ok': bool(js.get('ok', True)), 'response': js}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:220], 'url': url}


def _fmt(example):
    ins = str(example.get('instruction') or '').strip()
    out = str(example.get('output') or '').strip()
    txt = f"### Instruction:\n{ins}\n\n### Response:\n{out}"
    return {'text': txt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-model', required=True)
    ap.add_argument('--dataset', required=True)
    ap.add_argument('--adapter-out', required=True)
    ap.add_argument('--val-dataset', default='')
    ap.add_argument('--method', choices=['qlora', 'lora'], default='qlora')
    ap.add_argument('--epochs', type=int, default=1)
    ap.add_argument('--max-steps', type=int, default=0)
    ap.add_argument('--run-preset', default='production')
    ap.add_argument('--lr', type=float, default=2e-4)
    ap.add_argument('--max-length', type=int, default=512)
    ap.add_argument('--batch-size', type=int, default=1)
    ap.add_argument('--grad-accum', type=int, default=8)
    ap.add_argument('--early-stopping-patience', type=int, default=2)
    args = ap.parse_args()

    ds_path = Path(args.dataset)
    if not ds_path.exists():
        raise SystemExit(f'dataset missing: {ds_path}')

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    qlora_enabled = str(args.method or 'qlora').strip().lower() == 'qlora'
    if qlora_enabled:
        bnb_cfg = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type='nf4',
            bnb_4bit_compute_dtype='float16',
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.base_model,
            quantization_config=bnb_cfg,
            device_map='auto',
            torch_dtype='auto',
        )
        model = prepare_model_for_kbit_training(model)
    else:
        model = AutoModelForCausalLM.from_pretrained(args.base_model)

    lora_cfg = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias='none',
        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'up_proj', 'down_proj', 'gate_proj'],
    )
    model = get_peft_model(model, lora_cfg)

    raw = load_dataset('json', data_files=str(ds_path), split='train')
    raw = raw.map(_fmt)

    val_ds = None
    if str(args.val_dataset or '').strip():
        vp = Path(str(args.val_dataset))
        if vp.exists():
            val_raw = load_dataset('json', data_files=str(vp), split='train')
            val_raw = val_raw.map(_fmt)
            val_ds = val_raw

    def tok(ex):
        t = tokenizer(
            str(ex['text']),
            truncation=True,
            padding='max_length',
            max_length=args.max_length,
        )
        t['labels'] = list(t['input_ids'])
        return t

    ds = raw.map(tok, remove_columns=raw.column_names)
    ds_val = val_ds.map(tok, remove_columns=val_ds.column_names) if val_ds is not None else None

    targs_kwargs = dict(
        output_dir='/tmp/ultron_ft_out',
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        max_steps=max(0, int(args.max_steps or 0)),
        logging_steps=10,
        save_strategy='no',
        report_to=[],
    )
    if ds_val is not None:
        targs_kwargs['evaluation_strategy'] = 'epoch'
        targs_kwargs['per_device_eval_batch_size'] = args.batch_size
        # Required when using EarlyStoppingCallback
        targs_kwargs['save_strategy'] = 'epoch'
        targs_kwargs['load_best_model_at_end'] = True
        targs_kwargs['metric_for_best_model'] = 'eval_loss'
        targs_kwargs['greater_is_better'] = False
        targs_kwargs['save_total_limit'] = 1

    targs = TrainingArguments(**targs_kwargs)

    metrics_path = Path(args.adapter_out) / 'metrics.jsonl'
    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    class EpochMetricsCallback(TrainerCallback):
        def __init__(self):
            self.last_train_loss = None
            self.last_lr = None
            self.bad_val_streak = 0
            self.best_val = None
            self.worsen_epoch = None

        def _append(self, row: dict):
            with metrics_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')

        def on_log(self, args, state, control, logs=None, **kwargs):
            logs = logs or {}
            if 'loss' in logs:
                self.last_train_loss = float(logs.get('loss'))
            if 'learning_rate' in logs:
                self.last_lr = float(logs.get('learning_rate'))

        def on_epoch_end(self, args, state, control, **kwargs):
            row = {
                'event': 'epoch_end',
                'epoch': float(state.epoch or 0),
                'train_loss': self.last_train_loss,
                'learning_rate': self.last_lr,
                'ts': int(time.time()),
            }
            self._append(row)

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            metrics = metrics or {}
            v = metrics.get('eval_loss')
            row = {
                'event': 'eval',
                'epoch': float(state.epoch or 0),
                'val_loss': float(v) if v is not None else None,
                'train_loss': self.last_train_loss,
                'learning_rate': self.last_lr,
                'ts': int(time.time()),
            }
            if row['val_loss'] is not None:
                if self.best_val is None or row['val_loss'] < self.best_val:
                    self.best_val = row['val_loss']
                    self.bad_val_streak = 0
                else:
                    self.bad_val_streak += 1
                    if self.worsen_epoch is None:
                        self.worsen_epoch = float(state.epoch or 0)
                row['bad_val_streak'] = self.bad_val_streak
                row['best_val'] = self.best_val
            self._append(row)

    callbacks = [EpochMetricsCallback()]
    if ds_val is not None and int(args.early_stopping_patience or 0) > 0:
        callbacks.append(EarlyStoppingCallback(early_stopping_patience=int(args.early_stopping_patience)))

    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=ds,
        eval_dataset=ds_val,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
        callbacks=callbacks,
    )
    logger.info(f"PASSO 0: Iniciando treino... preset={str(args.run_preset or 'production')} max_steps={int(args.max_steps or 0)}")
    train_out = trainer.train()
    logger.info('PASSO 1: Treino concluído. Iniciando save_model...')

    out = Path(args.adapter_out)
    out.mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(300)
    try:
        trainer.save_model(str(out))
        logger.info('PASSO 2: save_model ok.')
    finally:
        signal.alarm(0)

    logger.info('PASSO 3: Iniciando merge/registro do adapter...')

    eval_out = None
    if ds_val is not None:
        with _timeout(300, 'evaluate'):
            eval_out = trainer.evaluate()

    with _timeout(300, 'tokenizer.save_pretrained'):
        tokenizer.save_pretrained(str(out))

    logger.info('PASSO 4: Registro ok. Notificando control plane...')

    # summarize epoch curve
    first_worsen_epoch = None
    try:
        for ln in metrics_path.read_text(encoding='utf-8', errors='ignore').splitlines():
            j = json.loads(ln)
            if j.get('event') == 'eval' and int(j.get('bad_val_streak') or 0) >= 1:
                first_worsen_epoch = float(j.get('epoch') or 0)
                break
    except Exception:
        first_worsen_epoch = None

    meta = {
        'ok': True,
        'base_model': args.base_model,
        'method': str(args.method or 'qlora'),
        'dataset': str(ds_path),
        'val_dataset': str(args.val_dataset or ''),
        'adapter_out': str(out),
        'run_preset': str(args.run_preset or 'production'),
        'epochs': args.epochs,
        'max_steps': int(args.max_steps or 0),
        'early_stopping_patience': args.early_stopping_patience,
        'lr': args.lr,
        'train_loss': float(getattr(train_out, 'training_loss', 0.0) or 0.0),
        'eval': eval_out or None,
        'metrics_path': str(metrics_path),
        'first_val_worsen_epoch': first_worsen_epoch,
    }
    (out / 'train_meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

    notify = _notify_control_plane(str(out), notes='PASSO5_train_done')
    if bool(notify.get('ok')):
        logger.info('PASSO 5: Job finalizado com sucesso e control plane notificado.')
    else:
        logger.warning(f"PASSO 5: Job finalizado, mas falha ao notificar control plane: {notify}")

    print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
