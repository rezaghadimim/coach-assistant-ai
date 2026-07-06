# Tool: get_client_full

## Purpose

Retrieve everything on file for a client: profile fields AND all saved notes, stories, decisions, goals, and progress updates.

## Use when

- The coach asks for "everything", "all data", "full details", or "complete record"
- Comprehensive overview needed before a coaching session
- The coach asks to "show everything about" a client

## Do NOT use when

- Only profile fields needed → use `get_client`
- Only specific note types needed → use `list_client_notes` with note_type filter
- Updating data → use `create_client` or `add_client_note`

## Example triggers

- "Show me everything about Ali"
- "Get all data about Sara"
- "Give me Ali's full details"
- "Pull up the complete record for Mohammad"
- "Everything on file for Ali"
- "Full profile and notes for Sara"
- "Tell me all about Ali"

## Do NOT confuse with

- `get_client` — profile fields only, no notes
- `list_client_notes` — notes only, filtered by type
