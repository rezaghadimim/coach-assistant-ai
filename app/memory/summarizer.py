"""Session summarization helpers."""


def summarize_session(messages: list[dict[str, str]]) -> str:
    """Generate a lightweight summary of a coaching session."""
    user_messages = [m["content"].strip() for m in messages if m["role"] == "user" and m["content"].strip()]
    assistant_messages = [
        m["content"].strip() for m in messages if m["role"] == "assistant" and m["content"].strip()
    ]

    discussed = "; ".join(user_messages[:3]) if user_messages else "No user details captured yet."
    coach_focus = assistant_messages[-1] if assistant_messages else "No assistant guidance yet."

    return (
        "Session Summary:\n"
        f"- Discussed: {discussed}\n"
        f"- Latest Coach Focus: {coach_focus}"
    )
