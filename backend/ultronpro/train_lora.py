from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer, DataCollatorForLanguageModeling
from peft import LoraConfig, get_peft_model, TaskType


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
    ap.add_argument('--epochs', type=int, default=1)
    ap.add_argument('--lr', type=float, default=2e-4)
    ap.add_argument('--max-length', type=int, default=512)
    ap.add_argument('--batch-size', type=int, default=1)
    ap.add_argument('--grad-accum', type=int, default=8)
    args = ap.parse_args()

    ds_path = Path(args.dataset)
    if not ds_path.exists():
        raise SystemExit(f'dataset missing: {ds_path}')

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(args.base_model)

    lora_cfg = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
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
        t = tokenizer(ex['text'], truncation=True, max_length=args.max_length)
        t['labels'] = t['input_ids'].copy()
        return t

    ds = raw.map(tok, remove_columns=raw.column_names)
    ds_val = val_ds.map(tok, remove_columns=val_ds.column_names) if val_ds is not None else None

    targs_kwargs = dict(
        output_dir='/tmp/ultron_ft_out',
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        logging_steps=10,
        save_strategy='no',
        report_to=[],
    )
    if ds_val is not None:
        targs_kwargs['evaluation_strategy'] = 'epoch'
        targs_kwargs['per_device_eval_batch_size'] = args.batch_size

    targs = TrainingArguments(**targs_kwargs)

    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=ds,
        eval_dataset=ds_val,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )
    train_out = trainer.train()
    eval_out = trainer.evaluate() if ds_val is not None else None

    out = Path(args.adapter_out)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out))
    tokenizer.save_pretrained(str(out))

    meta = {
        'ok': True,
        'base_model': args.base_model,
        'dataset': str(ds_path),
        'val_dataset': str(args.val_dataset or ''),
        'adapter_out': str(out),
        'epochs': args.epochs,
        'lr': args.lr,
        'train_loss': float(getattr(train_out, 'training_loss', 0.0) or 0.0),
        'eval': eval_out or None,
    }
    (out / 'train_meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
