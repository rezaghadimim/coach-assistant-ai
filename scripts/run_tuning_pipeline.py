"""Manual orchestrator for the Infinia LoRA fine-tuning pipeline.

This script is the single entry point for all fine-tuning work. Run it
when you decide (e.g. monthly, after collecting new sessions, or when
response quality drifts). It is NOT part of docker compose or any scheduled job.

Usage:
    # First-time full run
    python scripts/run_tuning_pipeline.py --profile infinia-only --steps all

    # Dry run — verify paths without GPU work
    python scripts/run_tuning_pipeline.py --profile infinia-only --steps all --dry-run

    # Only prepare + train (skip eval)
    python scripts/run_tuning_pipeline.py --profile mixed --steps prepare,train

    # Eval only — check if retraining is worth it
    python scripts/run_tuning_pipeline.py --steps eval --models baseline,coach-assistant-infinia

    # Re-download fresh HF data then full run
    python scripts/run_tuning_pipeline.py --profile infinia-only --steps all --refresh-data

Steps (executed in this order when listed):
    prepare   — download (cached) + adapt + optionally merge with sessions
    train     — LoRA training with auto-device selection
    eval      — coaching style evaluation (no GPU needed)

Profile → data mapping:
    infinia-only  Uses adapted Infinia data only (recommended for first run)
    mixed         Merges adapted Infinia + exported real sessions (30/70 default)
    sequential    Two-stage: Infinia first, then real sessions at lower LR
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent

sys.path.insert(0, str(ROOT))

from app.training.model_names import ollama_model_name

_VALID_STEPS = ("prepare", "train", "eval")


def _run(cmd: list[str], dry_run: bool = False) -> int:
    print(f"\n$ {' '.join(cmd)}")
    if dry_run:
        print("  (dry-run — skipped)")
        return 0
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def _step_prepare(args: argparse.Namespace) -> int:
    """Download (cached) + adapt the Infinia dataset. Merge if mixed profile."""
    refresh_flag = ["--refresh"] if args.refresh_data else []
    rc = _run(
        [sys.executable, str(SCRIPTS_DIR / "download_infinia_dataset.py"),
         "--output-dir", args.infinia_dir, *refresh_flag],
        dry_run=args.dry_run,
    )
    if rc != 0:
        return rc

    sample_flags = ["--sample", str(args.sample)] if args.sample else []
    rc = _run(
        [sys.executable, str(SCRIPTS_DIR / "prepare_infinia_training.py"),
         "--data-dir", args.infinia_dir,
         "--adapt-backend", args.adapt_backend,
         "--ollama-base-url", args.ollama_base_url,
         "--ollama-model", args.ollama_model,
         *sample_flags],
        dry_run=args.dry_run,
    )
    if rc != 0:
        return rc

    if args.profile == "mixed":
        sessions_path = Path(args.sessions_data)
        if not sessions_path.exists() and not args.dry_run:
            print(
                f"\nWARNING: sessions file not found at {sessions_path}.\n"
                "Export sessions first:\n"
                f"  python3 scripts/export_training_data.py --output {sessions_path}\n"
                "Merge will write Infinia-only rows to combined.jsonl."
            )
        rc = _run(
            [sys.executable, str(SCRIPTS_DIR / "merge_training_datasets.py"),
             "--infinia", str(Path(args.infinia_dir) / "infinia_adapted.jsonl"),
             "--sessions", str(sessions_path),
             "--infinia-weight", str(args.infinia_weight),
             "--output", args.combined_data],
            dry_run=args.dry_run,
        )
    return rc


def _step_train(args: argparse.Namespace) -> int:
    dry_flag = ["--dry-run"] if args.dry_run else []
    force_flag = ["--force-local"] if args.force_local else []
    rc = _run(
        [sys.executable, str(SCRIPTS_DIR / "train_lora.py"),
         "--profile", args.profile,
         "--epochs", str(args.epochs),
         "--lr", str(args.lr),
         "--artifacts-dir", args.artifacts_dir,
         *dry_flag, *force_flag],
        dry_run=False,  # train_lora.py handles --dry-run internally
    )
    return rc


def _step_eval(args: argparse.Namespace) -> int:
    models_str = args.models or "baseline"

    # eval_coaching_style.py does not support --dry-run; just print the command.
    if args.dry_run:
        print(
            f"\n$ python3 scripts/eval_coaching_style.py "
            f"--models {models_str} --eval-file {args.eval_file}"
        )
        print("  (dry-run — skipped)")
        print(
            "\n$ python3 scripts/eval_tool_routing.py"
        )
        print("  (dry-run — skipped)")
        return 0

    rc = _run(
        [sys.executable, str(SCRIPTS_DIR / "eval_coaching_style.py"),
         "--models", models_str,
         "--eval-file", args.eval_file],
        dry_run=False,
    )
    # Always run tool routing regression check after eval.
    rc2 = _run(
        [sys.executable, str(SCRIPTS_DIR / "eval_tool_routing.py")],
        dry_run=False,
    )
    return rc or rc2


def _print_deploy_instructions(args: argparse.Namespace) -> None:
    model_name = ollama_model_name(args.profile)
    print(
        "\n────────────────────────────────────────────────────────────\n"
        "Manual deploy steps (run after reviewing eval results above):\n"
        "\n"
        f"  1. Find your trained adapter:\n"
        f"     ls {args.artifacts_dir}/\n"
        "\n"
        f"  2. Import into Ollama:\n"
        f"     ollama create {model_name} -f "
        f"{args.artifacts_dir}/<run_id>/Modelfile\n"
        "\n"
        f"  3. Update .env:\n"
        f"     OLLAMA_MODEL={model_name}\n"
        "\n"
        f"  4. Restart the app:\n"
        f"     docker compose up --build\n"
        "────────────────────────────────────────────────────────────\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual LoRA fine-tuning pipeline for Coach Assistant AI"
    )
    parser.add_argument(
        "--profile",
        choices=["infinia-only", "mixed", "sequential"],
        default="infinia-only",
        help="Training profile (default: infinia-only)",
    )
    parser.add_argument(
        "--steps",
        default="all",
        help=(
            "Comma-separated steps to run: prepare, train, eval, all "
            "(default: all)"
        ),
    )
    parser.add_argument(
        "--adapt-backend",
        choices=["template", "ollama"],
        default="template",
        help="Adaptation backend for prepare step (default: template)",
    )
    parser.add_argument(
        "--ollama-base-url",
        default="http://localhost:11434",
        help="Ollama base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--ollama-model",
        default="llama3.1:8b",
        help="Ollama model for adaptation (default: llama3.1:8b)",
    )
    parser.add_argument(
        "--infinia-dir",
        default="data/external/infinia",
        help="Infinia data directory (default: data/external/infinia)",
    )
    parser.add_argument(
        "--sessions-data",
        default="data/training/sessions.jsonl",
        help="Exported sessions JSONL for mixed profile (default: data/training/sessions.jsonl)",
    )
    parser.add_argument(
        "--combined-data",
        default="data/training/combined.jsonl",
        help="Output path for merged dataset (default: data/training/combined.jsonl)",
    )
    parser.add_argument(
        "--infinia-weight",
        type=float,
        default=0.3,
        help="Infinia fraction in mixed dataset (default: 0.3)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Training epochs (default: 3)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=2e-4,
        help="Learning rate (default: 2e-4)",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts/lora",
        help="Root artifacts directory (default: artifacts/lora)",
    )
    parser.add_argument(
        "--eval-file",
        default="data/eval/coaching_empathy.jsonl",
        help="Eval JSONL path (default: data/eval/coaching_empathy.jsonl)",
    )
    parser.add_argument(
        "--models",
        default=None,
        help=(
            "Comma-separated models for eval step "
            "(default: baseline,<profile-model-name>)"
        ),
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Prepare step: only process N rows (quick review mode)",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Force re-download of HF dataset during prepare step",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all commands without executing them",
    )
    parser.add_argument(
        "--force-local",
        action="store_true",
        help="Pass --force-local to train_lora.py (CPU / low-VRAM override)",
    )
    args = parser.parse_args()

    # Resolve steps.
    if args.steps.strip().lower() == "all":
        steps = list(_VALID_STEPS)
    else:
        steps = [s.strip() for s in args.steps.split(",")]
        unknown = [s for s in steps if s not in _VALID_STEPS]
        if unknown:
            print(f"ERROR: Unknown steps: {unknown}. Valid: {_VALID_STEPS}", file=sys.stderr)
            return 1

    # Default eval models.
    if args.models is None:
        args.models = f"baseline,{ollama_model_name(args.profile)}"

    print("=== Coach Assistant AI — LoRA Tuning Pipeline ===")
    print(f"  Profile  : {args.profile}")
    print(f"  Steps    : {', '.join(steps)}")
    print(f"  Dry run  : {args.dry_run}")
    print(f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    rc = 0
    for step in steps:
        print(f"\n--- Step: {step} ---")
        if step == "prepare":
            rc = _step_prepare(args)
        elif step == "train":
            rc = _step_train(args)
        elif step == "eval":
            rc = _step_eval(args)

        if rc != 0:
            print(f"\nERROR: Step '{step}' failed (exit code {rc}).", file=sys.stderr)
            return rc

    if "train" in steps and not args.dry_run:
        _print_deploy_instructions(args)

    print(f"\n=== Pipeline complete ({', '.join(steps)}) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
