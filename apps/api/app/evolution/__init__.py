"""Twin evolution events (Sprint 8).

A `TwinEvolutionEvent` is the record of a durable, user-authorized
change that *actually took effect*. Only written AFTER the matching
apply succeeds. A rejected reflection is NOT an evolution. A pending
reflection is NOT an evolution.

See docs/architecture/evolving-twin-loop.md for the full semantics.
"""
