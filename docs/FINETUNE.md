# Fine-tuning Guide

> How to customize the base model to match the coach's voice and methodology. This is Phase 5 — do this AFTER collecting real conversation data.

---

## RAG vs Fine-tuning (LoRA) — Decision Rule

> **Ask yourself: "Am I teaching the model WHAT to know, or HOW to behave?"**
>
> - **WHAT to know → RAG**
> - **HOW to behave → Fine-tuning (LoRA)**

### Use RAG for Knowledge

Store information in RAG when:
- The content may change over time
- The content is large (books, documents, articles, manuals)
- The content must be retrieved accurately
- The source of the answer should be traceable
- New information should become available without retraining

**Examples:** books, articles, company documentation, product manuals, policies and procedures, user-uploaded documents, knowledge bases

### Use Fine-tuning (LoRA) for Behavior

Use fine-tuning when the goal is to change **how the model responds**, not what it knows.

**Examples:** coaching style, communication tone, questioning strategy, response structure, domain-specific reasoning patterns, output formatting, agent personality

### Do NOT Fine-tune Large Knowledge Sources

Avoid fine-tuning books, documentation, or knowledge repositories to inject information into the model weights.

> **Knowledge belongs in RAG. Behavior belongs in Fine-tuning.**

| Signal | Where it belongs |
|--------|-----------------|
| Content changes or grows | RAG |
| Needs accurate retrieval with a traceable source | RAG |
| Consistent response style, tone, or workflow | Fine-tuning |
| Reasoning patterns and coaching frameworks | Fine-tuning |

---

## When to Fine-tune

**Do NOT fine-tune until you have:**
- [ ] 500+ real coaching conversation examples
- [ ] Validated that RAG + prompting isn't sufficient
- [ ] Clear quality issues with base model responses

## Method: LoRA (Low-Rank Adaptation)

**Why LoRA:**
- Trains only ~1-2% of model parameters
- Needs only 1 GPU for a few hours
- Result can be loaded as an adapter (keeps base model intact)
- Easy to iterate and version

## Data Format

Convert conversations to this format (`training_data.jsonl`):

```json
{"messages": [{"role": "system", "content": "You are Coach Assistant AI..."}, {"role": "user", "content": "I feel stuck in my career"}, {"role": "assistant", "content": "I hear you. Let's explore that. When you say stuck, what does that look like day to day?"}]}
{"messages": [{"role": "system", "content": "You are Coach Assistant AI..."}, {"role": "user", "content": "I didn't do my homework"}, {"role": "assistant", "content": "No judgment. Let's understand what got in the way. What happened this week?"}]}
```

## Steps

### 1. Export Training Data

Export closed coaching sessions from the SQLite memory store. By default, only
sessions with at least **4 user→assistant turn pairs** are included (use
`--min-turns` to change the threshold).

```bash
python scripts/export_training_data.py --output training_data.jsonl
```

Options:

| Flag | Default | Purpose |
|------|---------|---------|
| `--output` | `training_data.jsonl` | Output JSONL path |
| `--db-path` | `data/coach_assistant.db` | SQLite database to read |
| `--min-turns` | `4` | Minimum user→assistant pairs per session |
| `--include-open-sessions` | off | Also export sessions that have not been closed |

Review the exported file manually before training — the script filters by
session length, not response quality.

### 2. Rent a GPU

| Provider | GPU | Cost | Time |
|----------|-----|------|------|
| RunPod | A100 40GB | $1.5/hr | ~3 hrs |
| Lambda | A100 80GB | $1.1/hr | ~2 hrs |
| Google Colab Pro | A100 | $10/mo | ~4 hrs |

### 3. Fine-tune with Unsloth (fastest)

```python
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/llama-3.1-8b-instruct",
    max_seq_length=4096,
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=16,              # LoRA rank
    lora_alpha=16,
    lora_dropout=0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
)

# Train
from trl import SFTTrainer
trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    max_seq_length=4096,
    num_train_epochs=3,
    per_device_train_batch_size=4,
    learning_rate=2e-4,
)
trainer.train()

# Save
model.save_pretrained_gguf("coach-assistant-model", tokenizer, quantization_method="q4_k_m")
```

### 4. Deploy to Ollama

```bash
# Create Modelfile
cat > Modelfile << 'EOF'
FROM ./coach-assistant-model-Q4_K_M.gguf
SYSTEM "You are Coach Assistant AI..."
PARAMETER temperature 0.7
PARAMETER top_p 0.9
EOF

# Import
ollama create coach-assistant -f Modelfile

# Test
ollama run coach-assistant "I want to change careers but I'm scared"
```

### 5. Update Config

In `app/core/config.py`, change:
```python
ollama_model: str = "coach-assistant"  # was "llama3.1:8b"
```

## Quality Checklist

After fine-tuning, verify:
- [ ] Responses match coach's tone and vocabulary
- [ ] Model uses correct coaching frameworks (GROW, etc.)
- [ ] Model asks questions instead of just giving advice
- [ ] Model handles emotional topics with empathy
- [ ] Model doesn't hallucinate coaching techniques
- [ ] Model still refuses to diagnose mental illness

---

## Infinia Life Coach Dataset Integration

The [Infinia Life Coach Dataset](https://huggingface.co/datasets/Infiniaai/infinia-life-coach-dataset)
(2,842 rows, Apache-2.0) provides poetic, empathy-focused prompt/completion pairs. Use it to give
the model warmer emotional attunement **before** or alongside real session data.

> **Do NOT store Infinia rows in `docs/knowledge/` (RAG).**
> They are behavior training data, not retrievable knowledge. See [`RAG.md`](RAG.md).

### When to use each profile

| Profile | When to use | Data |
|---------|-------------|------|
| `infinia-only` | First run, no real sessions yet | Adapted Infinia ~2.5k rows |
| `mixed` | After exporting ≥50 real sessions | 30% Infinia + 70% sessions |
| `sequential` | Mixed empathy gain is insufficient | Stage 1: Infinia → Stage 2: sessions |

### Expected benchmark deltas

| Variant | Empathy gain | Practicality risk |
|---------|-------------|-------------------|
| Infinia-only | +15–30% relative | Slight softening of actionable structure |
| Mixed (30/70) | +10–20% relative | Minimal; best for production |
| Sequential | Highest possible | High if stage 2 LR is too high |

Run `eval_coaching_style.py` before deploying to verify tool-routing accuracy
stays within ~2% of baseline.

### On-demand cadence

Fine-tuning is **manual** — run it when you choose, not on a schedule.

| Trigger | What to do |
|---------|-----------|
| First setup | `run_tuning_pipeline.py --profile infinia-only --steps all` |
| Monthly / when you want | `--profile mixed` if new sessions exist; else skip train |
| HF dataset revision | `download_infinia_dataset.py --refresh` then re-run |
| Quality regression | `--steps eval` only first; retrain only if scores justify it |

### Step-by-step

#### 1. Install fine-tune dependencies (once)

```bash
pip install -r requirements-finetune.txt
# For CUDA (RunPod/Lambda/Colab): also pip install unsloth[colab-new] bitsandbytes
```

#### 2. First run — Infinia only

```bash
# Dry run — verify paths before any GPU work
python3 scripts/run_tuning_pipeline.py --profile infinia-only --steps all --dry-run

# Sample 50 rows and review adapted output manually
python3 scripts/run_tuning_pipeline.py --profile infinia-only --steps prepare --sample 50
# Review data/external/infinia/infinia_adapted.jsonl (inspect 10 entries)

# Full prepare + train + eval
python3 scripts/run_tuning_pipeline.py --profile infinia-only --steps all
```

Use `--adapt-backend ollama` for higher quality adaptation (slower, requires Ollama running):

```bash
python3 scripts/run_tuning_pipeline.py --profile infinia-only --steps prepare \
    --adapt-backend ollama --ollama-model llama3.1:8b
```

#### 3. Later run — mixed (real sessions + Infinia)

```bash
# Export real coaching sessions first
python3 scripts/export_training_data.py --output data/training/sessions.jsonl

# Then run mixed pipeline
python3 scripts/run_tuning_pipeline.py --profile mixed --steps all
```

#### 4. Evaluate without retraining (quick check)

```bash
python3 scripts/run_tuning_pipeline.py --profile infinia-only --steps eval
```

Default eval compares `baseline` against the profile's Ollama model name
(`coach-assistant-infinia`, `coach-assistant-mixed`, or `coach-assistant-sequential`).

Or specify models explicitly:

```bash
python3 scripts/run_tuning_pipeline.py --steps eval \
    --models baseline,coach-assistant-infinia
```

This runs `eval_coaching_style.py` (empathy/practicality/metaphor scores) and
`eval_tool_routing.py` (regression check) without any GPU work.

#### 5. Deploy to Ollama (manual)

After reviewing eval results (model name depends on profile — e.g. `coach-assistant-infinia` for `infinia-only`):

```bash
ollama create coach-assistant-infinia -f artifacts/lora/<run_id>/Modelfile
# Update .env:
# OLLAMA_MODEL=coach-assistant-infinia
docker compose up --build
```

### Cloud GPU (if local device is insufficient)

The training script auto-detects your device. If it prints cloud instructions
(no CUDA ≥12 GB VRAM and no Apple MPS), use a cloud GPU:

| Provider | GPU | Cost | ~Time |
|----------|-----|------|-------|
| RunPod | A100 40 GB | $1.5/hr | ~3 hrs |
| Lambda | A100 80 GB | $1.1/hr | ~2 hrs |
| Google Colab Pro | A100 | $10/mo | ~4 hrs |

```bash
# On cloud instance:
pip install unsloth[colab-new] trl peft transformers datasets accelerate bitsandbytes
python3 scripts/run_tuning_pipeline.py --profile infinia-only --steps train --force-local
```

### Citation

```bibtex
@misc{infinia_life_coach_dataset_2025,
  author = {Infinia.ie},
  title  = {Infinia Life Coach Dataset},
  year   = {2025},
  howpublished = {HuggingFace Dataset},
  url    = {https://huggingface.co/datasets/Infiniaai/infinia-life-coach-dataset}
}
```

License: Apache-2.0. Non-clinical use only. Do not deploy in crisis response,
medical decision-making, or applications representing themselves as licensed professionals.
