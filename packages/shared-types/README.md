# @pat/shared-types

Type contracts shared between `apps/api` (Python) and `apps/mobile`
(TypeScript). Sprint 1 keeps this hand-authored; Sprint 2 wires
`openapi-typescript` to generate `src/generated.ts` from the FastAPI
OpenAPI document.

## Rules

- `apps/api` is the source of truth. If the two disagree, the backend wins.
- Never import from `apps/mobile/src/api/types.ts` — re-export from here.
- Adding a field to a Pydantic schema in the backend without updating this
  package is a CI failure once the generator lands.
