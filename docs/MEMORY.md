# Memory System

> How the AI remembers each client's history, goals, and progress across sessions.

## Why Memory Matters for Coaching

A good coach remembers:
- Client's goals and values
- What was discussed last session
- Action items and whether they were completed
- Emotional patterns and breakthroughs

## Architecture: Two-Layer Memory

```
┌─────────────────────────────────────────┐
│          SHORT-TERM MEMORY              │
│  (Current session messages in RAM)       │
│  [msg1, msg2, msg3, ... msg_n]          │
└─────────────────┬───────────────────────┘
                  │ auto-summarize when > 20 msgs
                  ▼
┌─────────────────────────────────────────┐
│          LONG-TERM MEMORY (SQLite)       │
│                                          │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │   Client    │  │    Sessions      │  │
│  │   Profile   │  │  (summaries)     │  │
│  └─────────────┘  └──────────────────┘  │
└─────────────────────────────────────────┘
```

## Database Schema

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    profile JSON  -- goals, values, challenges, notes
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    summary TEXT,  -- AI-generated session summary
    action_items JSON  -- extracted action items
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Client Profile Structure

```json
{
  "goals": ["Get promoted to director", "Improve work-life balance"],
  "values": ["Family", "Growth", "Impact"],
  "challenges": ["Procrastination", "People-pleasing"],
  "notes": "Responds well to accountability. Prefers direct feedback.",
  "coaching_style": "Challenge-oriented, not too soft"
}
```

## Session Summary Format

Auto-generated after each session:

```
Session Summary (2024-01-15):
- Discussed: Career transition anxiety
- Key Insight: Client realized fear of failure stems from childhood perfectionism
- Action Items: 1) Journal about worst-case scenario 2) Talk to mentor by Friday
- Mood: Started anxious (4/10), ended hopeful (7/10)
- Follow-up: Ask about mentor conversation next session
```

## How Memory Integrates with Chat

The prompt is built as:

```
[System Prompt: You are a life coach...]
[RAG Context: Relevant coaching knowledge...]
[Client Profile: Goals, values, challenges...]
[Last Session Summary: What happened last time...]
[Current Messages: msg1, msg2, ... msg_n]
[New User Message]
```

## Auto-Summarization

Triggered when current session exceeds 20 messages:

```python
SUMMARY_PROMPT = """
Summarize this coaching session. Include:
1. Main topics discussed
2. Key insights or breakthroughs
3. Action items agreed upon
4. Client's emotional state (start vs end)
5. What to follow up on next session
"""
```

The summary is stored in SQLite and loaded at the start of the next session.
