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

```bash
python scripts/export_training_data.py --min-quality 4 --output training_data.jsonl
```

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
