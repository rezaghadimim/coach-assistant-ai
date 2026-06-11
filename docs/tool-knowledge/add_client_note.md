# Tool: add_client_note

## Purpose

Save a narrative note for a client — a story, goal, decision, or progress update. Each call always inserts a new note row. Use note_type to categorize: general, story, decision, goal, progress.

## Use when

- The coach explicitly asks to save, document, note, or record something
- The content is a narrative (not a simple profile field like age or email)
- Saving a goal the client is working toward
- Documenting a decision the client made
- Recording progress or a story

## Do NOT use when

- The message contains a profile field (age, email, phone, occupation, background) → use `create_client`
- The coach is asking for coaching advice, techniques, or guidance → answer in plain text
- The coach wants to update an existing note → use `update_client_note`
- The message is a question or asks "how can I…" → do NOT save, respond instead

## Note types

- `goal` — coaching goals and objectives the client is working toward
- `decision` — committed decisions the client has made
- `story` — background stories and personal history
- `progress` — updates on previous goals or commitments
- `general` — any other narrative note

## Example triggers

- "Note that Ali decided to change careers"
- "Save a goal for Ali: run 3 times per week"
- "Document that Sara made progress on her goal"
- "Record that Mohammad's background is in engineering"
- "Ali wants to improve his work-life balance — save this as a goal"
- "Add a note: Ali is feeling overwhelmed with work"
- "Write down that Ali committed to journaling daily"

## Do NOT confuse with

- `create_client` — for profile fields (age, email, phone, occupation)
- `update_client_note` — to edit an existing saved note by note_id

## Hard negative pairs (use create_client instead)

- "Ali is 23 years old" → create_client (age)
- "Ali's age is 23" → create_client (age)
- "Set Ali's age to 30" → create_client (age)
- "Ali's email is ali@test.com" → create_client (email)
- "Ali works as a doctor" → create_client (occupation)
