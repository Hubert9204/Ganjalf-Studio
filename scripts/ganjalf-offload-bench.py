#!/usr/bin/env python3
"""How much layer offload costs on this machine: QLoRA steps at several VRAM budgets.

Each budget runs in its own process (a clean CUDA allocator), with the same calls Studio's
trainer makes: from_pretrained(offload_layers = "auto") and get_peft_model(offload_layers = "auto"),
capped with torch.cuda.set_per_process_memory_fraction exactly like the "VRAM budget" field.
"full" is the whole card, so Auto offloads nothing when the model fits.

Run it with Studio's own Python:
  ~/.ganjalf-studio/unsloth_studio/bin/python scripts/ganjalf-offload-bench.py \
      --model unsloth/Qwen3.6-27B --budgets full,16,12
  (Docker: /opt/unsloth-studio/unsloth_studio/bin/python, with nothing else training on the GPU.)

The model must be a safetensors checkpoint (not GGUF); it is loaded in 4 bit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

GIB = 1024**3


def _args(argv = None):
    p = argparse.ArgumentParser(description = __doc__, formatter_class = argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required = True, help = "Hugging Face id or local folder (safetensors)")
    p.add_argument("--budgets", default = "full,16,12", help = "comma list of GiB, or 'full' for the whole card")
    p.add_argument("--seq-len", type = int, default = 2048)
    p.add_argument("--batch", type = int, default = 1)
    p.add_argument("--rank", type = int, default = 16)
    p.add_argument("--steps", type = int, default = 12, help = "timed steps after 3 warm-up steps")
    p.add_argument("--prefetch", default = "auto", help = "prefetch depth: 1-8 or auto")
    p.add_argument("--gpu", type = int, default = 0)
    p.add_argument("--one", default = None, help = argparse.SUPPRESS)
    return p.parse_args(argv)


def _one_run(a) -> dict:
    """One budget, in this process. Returns the measurements as a dict."""
    import torch

    budget = None if a.one == "full" else float(a.one)
    torch.cuda.set_device(a.gpu)
    total = torch.cuda.get_device_properties(a.gpu).total_memory
    if budget is not None:
        torch.cuda.set_per_process_memory_fraction(min(1.0, budget * GIB / total), a.gpu)

    from unsloth import FastLanguageModel

    prefetch = a.prefetch if a.prefetch == "auto" else int(a.prefetch)
    t0 = time.perf_counter()
    model, tokenizer = FastLanguageModel.from_pretrained(
        a.model,
        max_seq_length = a.seq_len,
        load_in_4bit = True,
        offload_layers = "auto",
        device_map_planner_kwargs = {
            "prefetch_depth": prefetch,
            "batch_size": a.batch,
            "lora_rank": a.rank,
        },
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r = a.rank,
        lora_alpha = a.rank,
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing = "unsloth",
        offload_layers = "auto",
        prefetch_depth = prefetch,
    )
    load_s = time.perf_counter() - t0

    params = [p for p in model.parameters() if p.requires_grad]
    optim = torch.optim.AdamW(params, lr = 1e-5)
    vocab = getattr(model.config, "vocab_size", None) or len(tokenizer)
    gen = torch.Generator().manual_seed(3407)
    ids = torch.randint(100, min(vocab, 32000), (a.batch, a.seq_len), generator = gen).to(f"cuda:{a.gpu}")
    swapper = getattr(model, "_unsloth_block_swap", None) or getattr(
        getattr(model, "base_model", None), "_unsloth_block_swap", None
    )

    def step():
        out = model(input_ids = ids, labels = ids)
        out.loss.backward()
        optim.step()
        optim.zero_grad(set_to_none = True)

    model.train()
    for _ in range(3):
        step()
    torch.cuda.synchronize()
    if swapper is not None:
        swapper.stats(reset = True)
    torch.cuda.reset_peak_memory_stats(a.gpu)

    times = []
    for _ in range(a.steps):
        s = time.perf_counter()
        step()
        torch.cuda.synchronize()
        times.append(time.perf_counter() - s)

    stats = swapper.stats(reset = True) if swapper is not None else {}
    times.sort()
    return {
        "budget": a.one,
        "load_s": round(load_s, 1),
        "step_s_median": round(times[len(times) // 2], 3),
        "tokens_per_s": round(a.batch * a.seq_len / times[len(times) // 2], 1),
        "peak_vram_gib": round(torch.cuda.max_memory_allocated(a.gpu) / GIB, 2),
        "layers_on_host": len(stats.get("swapped") or []),
        "total_layers": stats.get("total_layers"),
        "prefetch_depth": stats.get("prefetch_depth"),
        "copy_gib_per_step": round((stats.get("copy_bytes") or 0) / GIB / a.steps, 2),
        "stall_ms_per_step": round((stats.get("stall_ms") or 0) / a.steps, 1),
        "compute_ms_per_step": round((stats.get("compute_ms") or 0) / a.steps, 1),
    }


def main() -> int:
    a = _args()
    if a.one is not None:
        print("BENCH " + json.dumps(_one_run(a)), flush = True)
        return 0

    rows = []
    for budget in [b.strip() for b in a.budgets.split(",") if b.strip()]:
        print(f"--- budget {budget} GiB ---" if budget != "full" else "--- whole card ---", flush = True)
        cmd = [sys.executable, os.path.abspath(__file__), *sys.argv[1:], "--one", budget]
        proc = subprocess.run(cmd, capture_output = True, text = True)
        line = next((l for l in proc.stdout.splitlines() if l.startswith("BENCH ")), None)
        if line is None:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-6:]
            print("  failed:\n    " + "\n    ".join(tail), flush = True)
            rows.append({"budget": budget, "error": tail[-1] if tail else "no output"})
            continue
        row = json.loads(line[6:])
        rows.append(row)
        print("  " + json.dumps(row), flush = True)

    print("\nbudget   step(s)  tok/s   VRAM peak  host layers  copy GiB/step  stall ms/step")
    base = next((r["step_s_median"] for r in rows if "step_s_median" in r), None)
    for r in rows:
        if "error" in r:
            print(f"{r['budget']:<8} failed: {r['error']}")
            continue
        slow = f"  (x{r['step_s_median'] / base:.2f})" if base else ""
        print(
            f"{r['budget']:<8} {r['step_s_median']:<8} {r['tokens_per_s']:<7} {r['peak_vram_gib']:<10} "
            f"{r['layers_on_host']}/{r['total_layers'] or '?':<10} {r['copy_gib_per_step']:<14} "
            f"{r['stall_ms_per_step']}{slow}"
        )
    print("\nstall ms/step is the time the GPU waited for PCIe; near 0 means the copies were hidden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
