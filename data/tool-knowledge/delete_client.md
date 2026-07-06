# Tool: delete_client

## Purpose

Permanently delete a client and all their associated notes and data. This is irreversible and requires explicit confirmation.

## Use when

- The coach explicitly asks to delete or remove a client (not just a note)
- The client_id or name is mentioned

## Do NOT use when

- Only a specific note should be deleted → use `delete_client_note`
- The coach is just looking up a client → use `get_client` or `get_client_full`

## Example triggers

- "Delete client Ali"
- "Remove patient Sara"
- "Delete Ali and all his data"
- "Remove Mohammad from my client list"

## Do NOT confuse with

- `delete_client_note` — only removes one note, not the whole client
