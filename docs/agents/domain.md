# Domain Docs

This repo uses a single-context domain documentation layout.

## Before Exploring

When working on domain-sensitive changes, read these if they exist:

- `CONTEXT.md` at the repo root
- relevant ADRs under `docs/adr/`

If these files do not exist, proceed silently. Do not create them just because they are missing.

The domain-modeling flow creates them lazily when terminology or decisions actually crystallize.

## Layout

Expected layout:

```text
/
|-- CONTEXT.md
|-- docs/
|   `-- adr/
|       |-- 0001-example-decision.md
|       `-- 0002-another-decision.md
`-- app/source files
```

## Glossary Use

Use terms exactly as defined in `CONTEXT.md` when naming issues, tests, refactors, and design proposals.

If a needed concept is not in the glossary yet, treat that as a signal for a future domain-modeling pass.

## ADR Conflicts

If a proposal or implementation contradicts an existing ADR, call that out explicitly instead of silently overriding the decision.

