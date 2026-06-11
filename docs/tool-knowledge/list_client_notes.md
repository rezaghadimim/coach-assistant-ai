# Tool: list_client_notes

## Purpose

List all notes for a client, optionally filtered by note type (goal, decision, story, progress, general).

## Use when

- The coach asks for a client's goals, decisions, stories, or progress notes
- Filtering notes by type: "What are Ali's goals?", "Show Ali's decisions"
- Reviewing what has been documented for a client

## Do NOT use when

- The coach needs full profile + notes → use `get_client_full`
- The coach needs only profile fields → use `get_client`
- The coach wants to add a new note → use `add_client_note`

## Note types

- `goal` — "What are Ali's goals?", "Show Ali's objectives"
- `decision` — "What decisions has Ali made?", "Show Ali's decisions"
- `story` — "Tell me Ali's background story", "What is Ali's story?"
- `progress` — "What progress has Ali made?", "Show Ali's progress updates"
- `general` — "List all notes for Ali"

## Example triggers

- "What are Ali's goals?"
- "Show me Ali's decisions"
- "List Ali's notes"
- "What progress has Sara made?"
- "Tell me Mohammad's background story"
- "What objectives does Ali have?"
- "What has Ali committed to?"
- "Show all documentation for Ali"

## Do NOT confuse with

- `get_client_full` — returns profile + all notes at once
- `get_client` — returns only structured profile fields
