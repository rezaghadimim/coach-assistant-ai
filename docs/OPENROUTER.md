# OpenRouter Integration (Optional Cloud Provider)

OpenRouter is an optional second LLM backend for testing and comparison with
cloud models. It is disabled by default — the system runs entirely on local
Ollama unless you explicitly configure an API key.

## When to Use OpenRouter

- **Quality comparison**: test how a larger cloud model (e.g. GPT-4o, Claude
  3.5 Sonnet) handles your coaching prompts vs. the local Llama model.
- **Latency relief**: use a cloud model when your hardware makes local inference
  too slow.
- **Prompt tuning**: get fast, high-quality responses while iterating on system
  prompts before finalising for local deployment.

> **Privacy notice**: selecting the cloud model sends conversation content to
> OpenRouter and the underlying model provider. Do not use the cloud model for
> sessions containing sensitive client data unless you have reviewed
> OpenRouter's data policies at <https://openrouter.ai/privacy>.

## Setup

### 1. Get an OpenRouter API key

Sign up at <https://openrouter.ai> and create a key at
<https://openrouter.ai/keys>. Add credits if you plan to use paid models.

### 2. Configure the environment

Copy `.env.example` to `.env` (if you haven't already) and fill in:

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here
# Optional: override the default cloud model
OPENROUTER_MODEL=openai/gpt-4o-mini
```

Browse all available models at <https://openrouter.ai/models>.

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | _(empty)_ | Your OpenRouter secret key. Leave empty to disable. |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | Model slug from OpenRouter's catalogue. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Override for testing/proxying. |
| `OPENROUTER_TIMEOUT` | `120.0` | HTTP timeout in seconds. |
| `OPENROUTER_HTTP_REFERER` | _(empty)_ | Optional site URL for OpenRouter attribution. |
| `OPENROUTER_APP_NAME` | `Coach Assistant AI` | Sent as `X-Title` header. |

### 3. Start the stack

```bash
docker compose up --build
```

When the API key is valid and OpenRouter is reachable, `GET /v1/models` returns
two entries:

```json
{
  "object": "list",
  "data": [
    { "id": "coach-assistant-ai",       "name": "Coach Assistant AI (Local · llama3.1:8b)" },
    { "id": "coach-assistant-ai-cloud", "name": "Coach Assistant AI (Cloud · openai/gpt-4o-mini)" }
  ]
}
```

Open WebUI will show both models in its model picker at
<http://localhost:3000>.

## Selecting the Model in Open WebUI

1. Open <http://localhost:3000> in your browser.
2. In the chat header, click the model name dropdown.
3. Choose **Coach Assistant AI (Cloud · …)** to route messages to OpenRouter,
   or **Coach Assistant AI (Local · …)** to use Ollama.
4. The selection persists for that chat session.

> The default model is always the local one (`coach-assistant-ai`). Switching
> to cloud requires an explicit choice in the UI.

## Verifying Provider Status

The `/health` endpoint reports both providers:

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "default_model": "coach-assistant-ai",
  "providers": {
    "ollama":      { "model": "llama3.1:8b",        "available": true },
    "openrouter":  { "model": "openai/gpt-4o-mini", "available": true }
  }
}
```

When the key is missing or the probe fails:

```json
"openrouter": { "model": "openai/gpt-4o-mini", "available": false, "reason": "api_key_missing" }
```

Possible `reason` values: `api_key_missing`, `probe_failed`, `unknown`.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Cloud model not listed in Open WebUI | API key missing or invalid | Check `OPENROUTER_API_KEY` in `.env`; restart the stack |
| Cloud model not listed despite valid key | Network issue or probe timeout | Check internet connectivity from the container; OpenRouter may be briefly unavailable |
| 503 response on cloud model request | Probe failed after model was listed | The 60-second probe cache expired and the re-probe failed; switch back to local model |
| High latency on first cloud request | Cold start / long context | Normal for cloud models with large contexts; increase `OPENROUTER_TIMEOUT` if timeouts occur |

## Model Cost Reference

OpenRouter passes through the upstream provider's pricing. A few common choices:

| Model slug | Quality | Approx. cost |
|---|---|---|
| `openai/gpt-4o-mini` | Good | ~$0.15 / 1M input tokens |
| `openai/gpt-4o` | High | ~$2.50 / 1M input tokens |
| `anthropic/claude-3.5-sonnet` | High | ~$3.00 / 1M input tokens |
| `meta-llama/llama-3.1-8b-instruct:free` | Comparable to local | Free (rate-limited) |

Prices change; check <https://openrouter.ai/models> for current rates.
