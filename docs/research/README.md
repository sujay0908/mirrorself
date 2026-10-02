# Research

> **The avatar is the interface; the evolving personal intelligence is the product.**

This directory holds research inputs, gap analyses, and design notes that
underpin the product. Nothing here is normative for engineering — the
architecture and product docs are. Research documents evolve independently.

---

## Foundational reference

- **A Survey on LLM-Based Human Digital Twins and Generative Agents**
  (Sujay, June 2026). 40 papers, 2018–2026.
- **DT taxonomy:** DT 1.0 (physical) → DT 2.0 (predictive) → DT 3.0
  (health) → **DT 4.0 (personal behavioural / emotional LLM twins)**.
  This product targets DT 4.0.

---

## Gaps identified by the survey (and how the MVP addresses them)

| Gap | Survey observation | MVP position |
|---|---|---|
| G1: Memory grounding | Existing systems inject too much / too little context. | Retrieval-first Twin Engine with a hard cap of 24 memories per turn. |
| G2: Profile vs episodic conflation | Systems overwrite personality with recent affect. | Structural separation: `TwinProfile` vs `Memory` vs `EmotionalState`; profile only mutates via confirmed reflection candidates. |
| G3: On-device / CPU-local twins | No published DT 4.0 system runs offline. | `LLMProvider` interface with a `LocalProvider` slot; MVP uses Claude cloud, but the seam is present from day one. |
| G4: Confirmation and user control | Memory silently accretes; users cannot steer it. | First-class memory drawer + candidate confirmation flow; hard delete and export. |
| G5: Emotional realism without permanence | Systems either ignore affect or let it dominate. | `emotional_states` as a rolling, decaying single row; no write path to profile. |

---

## Open research threads (post-MVP)

1. **Consolidation cadence and thresholds** — how many corroborating
   memories, over what window, should propose a profile update?
2. **Personality trait ontology** — Big Five vs HEXACO vs a compact
   product-native vocabulary? Sprint 3 will start with a product-native
   vocabulary of ~12 dimensions; a formal ontology is a Sprint 5+
   decision.
3. **Reflection prompt design** — what does the twin's own inner
   monologue look like, and how do we score its quality?
4. **Local model viability** — quantised Llama / Mistral / Gemma on
   Apple Silicon and CPU. Benchmarks needed for latency and quality of
   the extraction stage specifically (cheapest to move first).
5. **Longitudinal evaluation** — how do we measure that the twin is
   *actually getting to know* the user? Candidate metrics: recall
   accuracy on a private eval set; tone-similarity delta over sessions;
   user-reported "this felt like it knew me" ratings.

---

## Adding a research note

- Filename: `YYYY-MM-DD-short-slug.md`.
- Frontmatter: `title`, `author`, `status ∈ {draft, review, adopted, superseded}`.
- Body starts with a one-paragraph abstract.
- Cite sources with DOI or arXiv id where possible.
- Adopted notes update the relevant architecture or product doc; the
  research note remains as the reasoning trail.
