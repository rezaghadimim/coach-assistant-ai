"""LoRA fine-tuning script for Coach Assistant AI.

Detects the available device and either trains locally or prints cloud instructions.

Usage:
    python scripts/train_lora.py --profile infinia-only
    python scripts/train_lora.py --profile mixed
    python scripts/train_lora.py --profile sequential
    python scripts/train_lora.py --profile infinia-only --dry-run

Device auto-selection (default):
    CUDA ≥12 GB VRAM  → full Unsloth recipe, batch 4
    Apple MPS          → transformers + peft (no unsloth), batch 1 (~6-10 hrs)
    CPU / <12 GB VRAM  → print cloud instructions and exit (use --force-local to override)

Profiles:
    infinia-only  → data/external/infinia/infinia_adapted.jsonl  (first run)
    mixed         → data/training/combined.jsonl                 (when real sessions exist)
    sequential    → stage 1: infinia-only, stage 2: sessions     (advanced)

Outputs:
    artifacts/lora/<run_id>/adapter/     — PEFT LoRA adapter
    artifacts/lora/<run_id>/model.gguf   — quantised GGUF (if llama.cpp available)
    artifacts/lora/<run_id>/Modelfile    — Ollama Modelfile ready to use
    artifacts/lora/<run_id>/manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.training.model_names import ollama_model_name

_BASE_MODEL = "unsloth/llama-3.1-8b-instruct"
_LORA_RANK = 16
_LORA_ALPHA = 16
_MAX_SEQ_LEN = 4096
_DEFAULT_EPOCHS = 3
_DEFAULT_LR = 2e-4

_PROFILE_DATA: dict[str, str] = {
    "infinia-only": "data/external/infinia/infinia_adapted.jsonl",
    "mixed": "data/training/combined.jsonl",
}

_CLOUD_INSTRUCTIONS = textwrap.dedent("""\
    ──────────────────────────────────────────────────────────────────
    No suitable local GPU detected (need CUDA ≥12 GB or Apple MPS).

    Recommended cloud options (from docs/FINETUNE.md):
      RunPod   — A100 40 GB  ~$1.5/hr  ~3 hrs
      Lambda   — A100 80 GB  ~$1.1/hr  ~2 hrs
      Colab Pro — A100       ~$10/mo   ~4 hrs

    Steps on a cloud GPU:
      1. Upload your training JSONL to the instance.
      2. pip install unsloth[colab-new] trl peft transformers datasets accelerate bitsandbytes
      3. python scripts/train_lora.py --profile {profile} --force-local

    Pass --force-local to train on CPU/low VRAM (very slow, not recommended).
    ──────────────────────────────────────────────────────────────────
""")


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def _detect_device() -> str:
    """Return 'cuda', 'mps', or 'cpu'."""
    try:
        import torch  # noqa: PLC0415
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _cuda_vram_gb() -> float:
    try:
        import torch  # noqa: PLC0415
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return props.total_memory / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def _check_device(device: str, force_local: bool) -> bool:
    """Return True if training should proceed locally."""
    if device == "cuda":
        vram = _cuda_vram_gb()
        if vram >= 12:
            print(f"CUDA GPU detected: {vram:.1f} GB VRAM — proceeding locally.")
            return True
        if force_local:
            print(f"WARNING: Low VRAM ({vram:.1f} GB). Proceeding anyway (--force-local).")
            return True
        return False
    if device == "mps":
        print("Apple MPS detected — using transformers+peft (no unsloth). Expect slower training.")
        return True
    if force_local:
        print("WARNING: CPU-only training is very slow. Proceeding anyway (--force-local).")
        return True
    return False


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def _load_dataset(path: Path, tokenizer):
    """Load a JSONL file as a HuggingFace Dataset with the model chat template."""
    from datasets import Dataset  # type: ignore[import]  # noqa: PLC0415

    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    texts = []
    for row in rows:
        messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in row.get("messages", [])
        ]
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
        texts.append(text)

    return Dataset.from_dict({"text": texts})


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def _train_cuda(
    data_path: Path,
    output_dir: Path,
    epochs: int,
    learning_rate: float,
    batch_size: int,
    *,
    adapter_dir: Path | None = None,
    resume_adapter_path: Path | None = None,
) -> None:
    """Train using Unsloth (fastest CUDA path)."""
    try:
        from unsloth import FastLanguageModel  # type: ignore[import]  # noqa: PLC0415
    except ImportError:
        print(
            "ERROR: unsloth not installed.\n"
            "  pip install unsloth[colab-new]",
            file=sys.stderr,
        )
        sys.exit(1)

    from peft import PeftModel  # type: ignore[import]  # noqa: PLC0415
    from trl import SFTTrainer  # type: ignore[import]  # noqa: PLC0415
    from transformers import TrainingArguments  # type: ignore[import]  # noqa: PLC0415

    adapter_dir = adapter_dir or (output_dir / "adapter")
    checkpoint_dir = output_dir / f"checkpoints_{adapter_dir.name}"

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=_BASE_MODEL,
        max_seq_length=_MAX_SEQ_LEN,
        load_in_4bit=True,
    )
    if resume_adapter_path:
        model = PeftModel.from_pretrained(
            model,
            str(resume_adapter_path),
            is_trainable=True,
        )
    else:
        model = FastLanguageModel.get_peft_model(
            model,
            r=_LORA_RANK,
            lora_alpha=_LORA_ALPHA,
            lora_dropout=0,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                            "gate_proj", "up_proj", "down_proj"],
        )

    dataset = _load_dataset(data_path, tokenizer)

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=_MAX_SEQ_LEN,
        args=TrainingArguments(
            output_dir=str(checkpoint_dir),
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            learning_rate=learning_rate,
            fp16=True,
            logging_steps=50,
            save_steps=500,
        ),
    )
    trainer.train()

    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    if adapter_dir.name == "adapter":
        gguf_path = output_dir / "model.gguf"
        try:
            model.save_pretrained_gguf(
                str(gguf_path.with_suffix("")),
                tokenizer,
                quantization_method="q4_k_m",
            )
        except Exception as exc:
            print(f"NOTE: GGUF export skipped ({exc}). You can quantize manually with llama.cpp.")


def _train_mps_or_cpu(
    data_path: Path,
    output_dir: Path,
    device: str,
    epochs: int,
    learning_rate: float,
    batch_size: int,
    *,
    adapter_dir: Path | None = None,
    resume_adapter_path: Path | None = None,
) -> None:
    """Train using standard transformers + peft (MPS / CPU fallback)."""
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments  # type: ignore[import]  # noqa: PLC0415
        from peft import LoraConfig, PeftModel, get_peft_model  # type: ignore[import]  # noqa: PLC0415
        from trl import SFTTrainer  # type: ignore[import]  # noqa: PLC0415
    except ImportError as exc:
        print(
            f"ERROR: Missing dependency: {exc}\n"
            "  pip install -r requirements-finetune.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    adapter_dir = adapter_dir or (output_dir / "adapter")
    checkpoint_dir = output_dir / f"checkpoints_{adapter_dir.name}"

    print(f"Loading {_BASE_MODEL} (this may take a few minutes)…")
    tokenizer = AutoTokenizer.from_pretrained(_BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(_BASE_MODEL, device_map=device)

    if resume_adapter_path:
        model = PeftModel.from_pretrained(
            model,
            str(resume_adapter_path),
            is_trainable=True,
        )
    else:
        lora_config = LoraConfig(
            r=_LORA_RANK,
            lora_alpha=_LORA_ALPHA,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_config)

    model.print_trainable_parameters()

    dataset = _load_dataset(data_path, tokenizer)
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=_MAX_SEQ_LEN,
        args=TrainingArguments(
            output_dir=str(checkpoint_dir),
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            learning_rate=learning_rate,
            fp16=False,
            bf16=(device == "mps"),
            logging_steps=50,
            save_steps=500,
            no_cuda=(device != "cuda"),
        ),
    )
    trainer.train()

    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"Adapter saved to {adapter_dir}")
    if adapter_dir.name == "adapter":
        print(
            "NOTE: GGUF export requires CUDA+Unsloth. "
            "Merge and quantize manually with llama.cpp if needed."
        )


# ---------------------------------------------------------------------------
# Modelfile generation
# ---------------------------------------------------------------------------

def _write_modelfile(output_dir: Path, source: str) -> Path:
    """Write an Ollama Modelfile for the trained model."""
    from app.core.prompts import COACH_ASSISTANT_SYSTEM_PROMPT  # noqa: PLC0415

    gguf_candidates = list(output_dir.glob("*.gguf"))
    if gguf_candidates:
        from_line = f"FROM ./{gguf_candidates[0].name}"
    else:
        from_line = (
            "# Merge adapter with base weights and export a GGUF before importing:\n"
            "#   FROM ./your-merged-model.gguf"
        )

    modelfile_content = (
        f"{from_line}\n"
        f'SYSTEM """{COACH_ASSISTANT_SYSTEM_PROMPT}"""\n'
        "PARAMETER temperature 0.7\n"
        "PARAMETER top_p 0.9\n"
    )
    path = output_dir / "Modelfile"
    path.write_text(modelfile_content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _write_manifest(
    output_dir: Path,
    run_id: str,
    profile: str,
    data_path: Path,
    config: dict,
    *,
    stage2_data_path: Path | None = None,
) -> None:
    model_name = ollama_model_name(profile)
    manifest = {
        "run_id": run_id,
        "profile": profile,
        "ollama_model": model_name,
        "base_model": _BASE_MODEL,
        "data_path": str(data_path),
        "config": config,
        "artifacts": {
            "adapter": str(output_dir / "adapter"),
            "modelfile": str(output_dir / "Modelfile"),
        },
        "deploy_command": (
            f"ollama create {model_name} -f {output_dir}/Modelfile\n"
            f"# then set OLLAMA_MODEL={model_name} in .env"
        ),
    }
    if stage2_data_path:
        manifest["stage2_data_path"] = str(stage2_data_path)
        manifest["artifacts"]["adapter_stage1"] = str(output_dir / "adapter_stage1")
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LoRA fine-tune Coach Assistant AI with automatic device selection"
    )
    parser.add_argument(
        "--profile",
        choices=["infinia-only", "mixed", "sequential"],
        default="infinia-only",
        help="Training profile (default: infinia-only)",
    )
    parser.add_argument(
        "--data",
        default=None,
        help="Override training data path (auto-selected from --profile by default)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=_DEFAULT_EPOCHS,
        help=f"Training epochs (default: {_DEFAULT_EPOCHS})",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=_DEFAULT_LR,
        help=f"Learning rate (default: {_DEFAULT_LR})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Batch size per device (auto-selected from device by default)",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts/lora",
        help="Root directory for run artifacts (default: artifacts/lora)",
    )
    parser.add_argument(
        "--force-local",
        action="store_true",
        help="Train locally even on CPU or low-VRAM GPU",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without starting training",
    )
    # Sequential profile: allow specifying session data separately.
    parser.add_argument(
        "--sessions-data",
        default="data/training/sessions.jsonl",
        help="Sessions data for the second stage of sequential training",
    )
    args = parser.parse_args()

    # Resolve data path.
    if args.profile == "sequential":
        infinia_path = Path(_PROFILE_DATA["infinia-only"])
        sessions_path = Path(args.sessions_data)
    else:
        data_path = Path(args.data) if args.data else Path(_PROFILE_DATA.get(args.profile, ""))
        if not data_path or not data_path.exists():
            print(
                f"ERROR: training data not found at {data_path}\n"
                f"For profile '{args.profile}', run the preparation step first:\n"
                f"  python scripts/run_tuning_pipeline.py --profile {args.profile} --steps prepare",
                file=sys.stderr,
            )
            sys.exit(1)

    device = _detect_device()
    can_train_locally = _check_device(device, args.force_local)

    run_id = f"{datetime.now().strftime('%Y-%m-%d_%H%M')}_{args.profile}"
    output_dir = Path(args.artifacts_dir) / run_id

    if args.dry_run:
        print(f"DRY RUN — would train with:")
        print(f"  Profile   : {args.profile}")
        if args.profile == "sequential":
            print(f"  Stage 1   : {infinia_path}")
            print(f"  Stage 2   : {sessions_path}")
        else:
            print(f"  Data      : {data_path}")
        print(f"  Device    : {device}")
        print(f"  Epochs    : {args.epochs}")
        print(f"  LR        : {args.lr}")
        print(f"  Output    : {output_dir}")
        return

    if not can_train_locally:
        print(_CLOUD_INSTRUCTIONS.format(profile=args.profile))
        sys.exit(0)

    output_dir.mkdir(parents=True, exist_ok=True)

    batch_size = args.batch_size or (4 if device == "cuda" else 1)

    config = {
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "batch_size": batch_size,
        "device": device,
        "lora_rank": _LORA_RANK,
        "lora_alpha": _LORA_ALPHA,
    }

    if args.profile == "sequential":
        print(f"Sequential training — Stage 1: Infinia ({infinia_path})")
        if not infinia_path.exists():
            print(f"ERROR: {infinia_path} not found.", file=sys.stderr)
            sys.exit(1)

        final_adapter_dir = output_dir / "adapter"
        stage2_path: Path | None = None

        if sessions_path.exists():
            stage1_dir = output_dir / "adapter_stage1"
            stage2_epochs = max(1, args.epochs - 1)
            stage2_lr = args.lr * 0.3
            if device == "cuda":
                _train_cuda(
                    infinia_path,
                    output_dir,
                    args.epochs,
                    args.lr,
                    batch_size,
                    adapter_dir=stage1_dir,
                )
                print(f"\nSequential training — Stage 2: Sessions ({sessions_path})")
                _train_cuda(
                    sessions_path,
                    output_dir,
                    stage2_epochs,
                    stage2_lr,
                    batch_size,
                    adapter_dir=final_adapter_dir,
                    resume_adapter_path=stage1_dir,
                )
            else:
                _train_mps_or_cpu(
                    infinia_path,
                    output_dir,
                    device,
                    args.epochs,
                    args.lr,
                    batch_size,
                    adapter_dir=stage1_dir,
                )
                print(f"\nSequential training — Stage 2: Sessions ({sessions_path})")
                _train_mps_or_cpu(
                    sessions_path,
                    output_dir,
                    device,
                    stage2_epochs,
                    stage2_lr,
                    batch_size,
                    adapter_dir=final_adapter_dir,
                    resume_adapter_path=stage1_dir,
                )
            stage2_path = sessions_path
        else:
            print(
                f"WARNING: Sessions data not found at {sessions_path}. "
                "Training on Infinia only."
            )
            if device == "cuda":
                _train_cuda(
                    infinia_path,
                    output_dir,
                    args.epochs,
                    args.lr,
                    batch_size,
                    adapter_dir=final_adapter_dir,
                )
            else:
                _train_mps_or_cpu(
                    infinia_path,
                    output_dir,
                    device,
                    args.epochs,
                    args.lr,
                    batch_size,
                    adapter_dir=final_adapter_dir,
                )
    else:
        if device == "cuda":
            _train_cuda(data_path, output_dir, args.epochs, args.lr, batch_size)
        else:
            _train_mps_or_cpu(data_path, output_dir, device, args.epochs, args.lr, batch_size)

    modelfile_path = _write_modelfile(output_dir)
    manifest_data_path = infinia_path if args.profile == "sequential" else data_path
    stage2_data_path = sessions_path if args.profile == "sequential" and sessions_path.exists() else None
    _write_manifest(
        output_dir,
        run_id,
        args.profile,
        manifest_data_path,
        config,
        stage2_data_path=stage2_data_path,
    )

    model_name = ollama_model_name(args.profile)
    print(f"\nTraining complete. Artifacts: {output_dir}")
    print(f"\nTo deploy:")
    print(f"  ollama create {model_name} -f {modelfile_path}")
    print(f"  # Set OLLAMA_MODEL={model_name} in .env, then restart the app")
    print(f"\nTo evaluate:")
    print(f"  python scripts/eval_coaching_style.py --models baseline,{model_name}")
    print(f"  python scripts/eval_tool_routing.py")


if __name__ == "__main__":
    main()
