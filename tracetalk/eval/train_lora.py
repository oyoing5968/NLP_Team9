#!/usr/bin/env python3
"""LoRA SFT of the student on one GPU (no DDP), then merge for Ollama import.

Run inside a venv with torch + transformers + peft. The base model keeps its own
architecture class (Qwen3.5 is image-text; training uses text only) so the merged
folder has the same layout as the base and can go through the same Ollama import.
Only the assistant turn is in the loss. Examples longer than --max-len are dropped
and counted, never truncated (a cut JSON target teaches broken output).
"""
import argparse
import hashlib
import json
import math
import platform
import random
import shutil
import time
from pathlib import Path


def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def load_model(base, torch):
    from transformers import AutoModelForCausalLM, AutoModelForImageTextToText
    errors = []
    for cls in (AutoModelForImageTextToText, AutoModelForCausalLM):
        try:
            # safetensors only: never unpickle weights; trust_remote_code stays off (default).
            return cls.from_pretrained(base, dtype=torch.bfloat16, use_safetensors=True), cls.__name__
        except (ValueError, KeyError, OSError) as exc:
            errors.append(f"{cls.__name__}: {exc}")
    raise SystemExit("모델을 불러오지 못했습니다:\n" + "\n".join(errors))


def encode(tok, messages, max_len, end_text):
    prompt = tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True,
                                     enable_thinking=False)
    prompt_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    target_ids = tok(messages[-1]["content"] + end_text, add_special_tokens=False)["input_ids"]
    if len(prompt_ids) + len(target_ids) > max_len:
        return None
    return {"input_ids": prompt_ids + target_ids, "labels": [-100] * len(prompt_ids) + target_ids}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="Qwen/Qwen3.5-4B")
    p.add_argument("--data", required=True, help="folder with sft_train.jsonl and sft_val.jsonl")
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--accum", type=int, default=8)
    p.add_argument("--max-len", type=int, default=4096)
    p.add_argument("--max-steps", type=int, default=0, help="stop after N optimizer steps (round-trip test)")
    p.add_argument("--eval-every", type=int, default=25)
    p.add_argument("--seed", type=int, default=1026)
    args = p.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer
    import peft
    import transformers

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    tok = AutoTokenizer.from_pretrained(args.base)
    end_text = "<|im_end|>" if "<|im_end|>" in tok.get_vocab() else tok.eos_token
    model, model_class = load_model(args.base, torch)
    model.to("cuda")

    linear = [n for n, m in model.named_modules() if isinstance(m, torch.nn.Linear)]
    language = [n for n in linear if not any(k in n for k in ("visual", "vision", "mtp", "lm_head"))]
    suffixes = sorted({n.rsplit(".", 1)[-1] for n in language})
    pattern = r"^(?!.*(visual|vision|mtp|lm_head)).*\.(" + "|".join(suffixes) + r")$"
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05,
                                             target_modules=pattern, task_type="CAUSAL_LM"))
    trainable = sum(x.numel() for x in model.parameters() if x.requires_grad)
    if not trainable:
        raise SystemExit("LoRA 대상 모듈이 없습니다.")
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()

    data_dir = Path(args.data)
    dropped = {}
    sets = {}
    for name in ("sft_train", "sft_val"):
        rows = read_jsonl(data_dir / f"{name}.jsonl")
        encoded = [encode(tok, r["messages"], args.max_len, end_text) for r in rows]
        dropped[name] = sum(e is None for e in encoded)
        sets[name] = [e for e in encoded if e is not None]
    train, val = sets["sft_train"], sets["sft_val"]
    total_steps = math.ceil(len(train) * args.epochs / args.accum)
    if args.max_steps:
        total_steps = min(total_steps, args.max_steps)
    warmup = max(1, total_steps // 30)
    opt = torch.optim.AdamW([x for x in model.parameters() if x.requires_grad], lr=args.lr, weight_decay=0.0)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warmup) *
                                              0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, total_steps)))))

    meta = {"args": vars(args), "model_class": model_class, "lora_suffixes": suffixes,
            "trainable_params": trainable, "train_examples": len(train), "val_examples": len(val),
            "dropped_over_max_len": dropped, "total_steps": total_steps, "end_text": end_text,
            "versions": {"torch": torch.__version__, "transformers": transformers.__version__,
                         "peft": peft.__version__, "python": platform.python_version()},
            "gpu": torch.cuda.get_device_name(0),
            "data_sha256": {n: hashlib.sha256((data_dir / f"{n}.jsonl").read_bytes()).hexdigest()
                            for n in ("sft_train", "sft_val")}}
    (out / "train_config.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False), flush=True)
    log = (out / "train_log.jsonl").open("x", encoding="utf-8")

    def evaluate():
        model.eval()
        losses = []
        with torch.no_grad():
            for e in val:
                ids = torch.tensor([e["input_ids"]], device="cuda")
                labels = torch.tensor([e["labels"]], device="cuda")
                losses.append(model(input_ids=ids, labels=labels).loss.item())
        model.train()
        return sum(losses) / len(losses) if losses else None

    model.train()
    step, micro, running, started = 0, 0, [], time.time()
    order = []
    while step < total_steps:
        if not order:
            order = list(range(len(train)))
            random.shuffle(order)
        e = train[order.pop()]
        ids = torch.tensor([e["input_ids"]], device="cuda")
        labels = torch.tensor([e["labels"]], device="cuda")
        loss = model(input_ids=ids, labels=labels).loss
        (loss / args.accum).backward()
        running.append(loss.item())
        micro += 1
        if micro % args.accum:
            continue
        torch.nn.utils.clip_grad_norm_([x for x in model.parameters() if x.requires_grad], 1.0)
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        row = {"step": step, "train_loss": sum(running) / len(running), "lr": sched.get_last_lr()[0],
               "seconds": round(time.time() - started, 1)}
        running = []
        if step % args.eval_every == 0 or step == total_steps:
            row["val_loss"] = evaluate()
        log.write(json.dumps(row) + "\n")
        log.flush()
        print(json.dumps(row), flush=True)
    log.close()

    model.save_pretrained(out / "adapter")
    merged = model.merge_and_unload()
    merged.save_pretrained(out / "merged", safe_serialization=True)
    tok.save_pretrained(out / "merged")
    # Keep the base's processor/template files so the merged folder imports like the base.
    from huggingface_hub import snapshot_download
    base_dir = Path(args.base) if Path(args.base).is_dir() else Path(snapshot_download(args.base))
    for f in base_dir.iterdir():
        if f.is_file() and not f.name.endswith(".safetensors") and f.name not in (
                "model.safetensors.index.json", "config.json") and not (out / "merged" / f.name).exists():
            shutil.copy2(f, out / "merged" / f.name)
    print(json.dumps({"saved": str(out / "merged"), "steps": step}), flush=True)


if __name__ == "__main__":
    main()
