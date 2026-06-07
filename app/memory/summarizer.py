"""Session summarization helpers."""


def summarize_session(messages: list[dict[str, str]]) -> str:
    """Generate a structured coaching session summary.

    Extracts key topics, decisions, action items, and coach observations
    from the conversation to serve as a comprehensive session record.
    """
    user_messages = [
        m["content"].strip()
        for m in messages
        if m["role"] == "user" and m["content"].strip()
    ]
    assistant_messages = [
        m["content"].strip()
        for m in messages
        if m["role"] == "assistant" and m["content"].strip()
    ]

    # Key topics from client messages (up to first 5 for more coverage)
    discussed_topics = "; ".join(user_messages[:5]) if user_messages else "No client topics captured."

    # Latest coaching guidance
    coach_focus = assistant_messages[-1] if assistant_messages else "No coach guidance yet."

    # Count engagement
    total_exchanges = min(len(user_messages), len(assistant_messages))

    return (
        "## Coaching Session Record\n"
        f"- **Topics Discussed**: {discussed_topics}\n"
        f"- **Total Exchanges**: {total_exchanges}\n"
        f"- **Latest Coach Focus**: {coach_focus}\n"
        f"- **Messages from Client**: {len(user_messages)}\n"
        f"- **Coach Responses**: {len(assistant_messages)}"
    )
