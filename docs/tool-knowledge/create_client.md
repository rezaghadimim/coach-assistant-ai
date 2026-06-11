# Tool: create_client

## Purpose

Create a new client profile or update existing profile fields (name, phone, email, age, occupation, background). This is the only tool that writes to the client's structured profile — it merges fields, never duplicates.

## Use when

- Registering a new client by name
- Updating any profile field: age, email, phone, occupation, background
- The message states a fact about the client that belongs in structured data

## Do NOT use when

- The message is a narrative note, story, decision, goal, or progress update → use `add_client_note`
- The coach is asking for coaching advice or asking a question → answer in plain text
- The coach wants to update a previously saved note → use `update_client_note`

## Profile fields (always use create_client, never add_client_note)

- `age` — "Ali is 23 years old", "Ali's age is 23", "Set Ali's age to 30", "Add age for Ali 13"
- `email` — "Ali's email is ali@example.com"
- `phone` — "Ali's phone is +1-555-0100"
- `occupation` — "Ali works as a software engineer"
- `background` — "Ali grew up in Tehran"
- `name` — updating a display name

## Example triggers

- "Add Ali as a client"
- "Register Sara as a new patient"
- "Create a client named Mohammad"
- "Ali is 23 years old"
- "Ali's age is 23"
- "Set Ali's age to 30"
- "Add age for Ali 13"
- "Set age for Ali to 13"
- "Update Ali's age to 25"
- "Ali's email is ali@test.com"
- "Ali's phone number is 09121234567"
- "Save Ali's contact info"
- "Ali works as a doctor"
- "Ali is a software engineer"

## Do NOT confuse with

- `add_client_note` — for narrative content (stories, goals, decisions, progress)
- `update_client_note` — for editing an existing note by note ID
