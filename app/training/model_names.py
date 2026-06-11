"""Ollama model names for fine-tuning profiles."""

PROFILE_OLLAMA_MODELS: dict[str, str] = {
    "infinia-only": "coach-assistant-infinia",
    "mixed": "coach-assistant-mixed",
    "sequential": "coach-assistant-sequential",
}


def ollama_model_name(profile: str) -> str:
    """Return the Ollama model tag for a training profile."""
    try:
        return PROFILE_OLLAMA_MODELS[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown profile: {profile!r}") from exc
