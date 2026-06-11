# Tool: update_client_note

## Purpose

Edit an existing note by its note_id. Replaces the content of a previously saved note. Requires knowing the note_id (integer).

## Use when

- The coach refers to an existing note by number ("update note 3", "edit note 5")
- Correcting or revising previously saved note content
- The note_id is explicitly mentioned in the message

## Do NOT use when

- The coach wants to save a new note → use `add_client_note`
- The coach is updating a profile field (age, email) → use `create_client`
- There is no specific note_id mentioned → defer to LLM

## Example triggers

- "Update note 3 to: Ali now runs 5 times per week"
- "Edit note 5 for Ali"
- "Change note 7: Ali's goal is to read daily"
- "Revise note 2 with the new decision"
- "Fix note 4, Ali's decision has changed"

## Do NOT confuse with

- `add_client_note` — for new notes (no note_id required)
- `create_client` — for profile field updates
