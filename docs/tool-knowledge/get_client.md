# Tool: get_client

## Purpose

Retrieve a client's structured profile fields only: name, age, email, phone, occupation, background. Does NOT return notes.

## Use when

- The coach asks for a specific profile field (email, phone, age, occupation)
- Lookups that need contact details only
- The coach asks "what is Ali's email?" or "what is Ali's phone?"

## Do NOT use when

- The coach wants all data including notes → use `get_client_full`
- The coach wants to see notes, goals, or decisions → use `list_client_notes`
- The coach wants to update a field → use `create_client`

## Example triggers

- "What is Ali's email?"
- "What is Ali's phone number?"
- "Show me Ali's contact info"
- "What is Ali's age?"
- "What is Sara's occupation?"
- "Get Ali's profile details"

## Do NOT confuse with

- `get_client_full` — returns profile AND all notes
- `list_client_notes` — returns notes only, no profile fields
