# @pat/prompt-templates

Versioned, hashed, provider-neutral prompt fragments.

Sprint 1 ships a single system prompt built inline in
`apps/api/app/conversation/pipeline.py`. This directory is the destination
for the versioned YAML fragments once the pipeline is extended in Sprint 2
(intent detection, extraction, reflection). Each fragment will carry a
semantic version and a hash so trace records can pin which prompt produced
which response.

## Layout (planned)

```
prompt-templates/
├── sprint1/
│   └── system.yaml            # Sprint 1 baseline (currently in code)
├── intent/
│   └── v1.yaml
├── extraction/
│   └── v1.yaml
└── reflection/
    └── v1.yaml
```
