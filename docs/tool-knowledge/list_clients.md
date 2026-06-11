# Tool: list_clients

## Purpose

List all registered clients for the coach. No client_id required.

## Use when

- The coach asks who their clients are
- Requesting an overview of all patients
- The coach wants to see all registered names

## Do NOT use when

- The coach wants details about a specific client → use `get_client` or `get_client_full`
- The coach wants notes for a specific client → use `list_client_notes`

## Example triggers

- "Who are my clients?"
- "List my clients"
- "Show all my patients"
- "List all clients"
- "Who am I coaching?"
- "Show everyone I am coaching"
- "Which clients do I have?"

## Do NOT confuse with

- `get_client_full` — detailed view of a single client
- `list_client_notes` — notes for a specific client
