# Tool: delete_client_note

## Purpose

Permanently delete a single note by its note_id. Requires explicit confirmation before deleting.

## Use when

- The coach explicitly says to delete or remove a specific note
- The note_id is clearly mentioned

## Do NOT use when

- The coach wants to edit or update a note → use `update_client_note`
- No note_id is given → defer to LLM
- The coach wants to delete the entire client record → use `delete_client`

## Example triggers

- "Delete note 3"
- "Remove note 5 for Ali"
- "Get rid of note 7"
- "Drop note 2"

## Do NOT confuse with

- `delete_client` — removes the entire client and all their notes
- `update_client_note` — modifies a note instead of deleting it
