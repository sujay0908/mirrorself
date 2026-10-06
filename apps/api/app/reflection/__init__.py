"""Reflection domain (Sprint 7).

The Twin reads its own confirmed memories, active goals, and recent
conversation turns and proposes user-confirmable observations:
`profile_update`, `memory_dedup`, `goal_update`, or `insight`. The user
is the sole author of durable changes — the LLM only proposes.

See docs/architecture/reflection.md.
"""
