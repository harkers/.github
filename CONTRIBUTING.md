# Contributing

## Work starts from a structured issue

Use the repository's Issue Forms. Broad features and epics must be decomposed into bounded implementation tasks before coding begins.

## Required delivery sequence

Unless a repository explicitly documents a narrower process:

`issue → specification → implementation plan → dedicated branch/worktree → implementation → tests → draft PR → independent review → evidence verification → specialist review where triggered → completion packet → PR ready`

## Pull requests

- Keep changes bounded to the linked issue/specification.
- Use atomic commits.
- Open a draft PR after the first verified implementation commit when practical.
- Record commands and test results; do not claim a check passed unless it actually ran.
- Treat reviewer findings as claims that may be SUPPORTED, REFUTED or UNCLEAR after evidence verification.
- Do not make a PR ready while required checks or blocking findings remain unresolved.

## Security and secrets

Never commit credentials, tokens, `.env` contents, private keys, or unrelated sensitive repository content. Cloud-model review must receive only the minimum necessary diff/context and must exclude secrets.

## Repository-specific rules

Repository-local `AGENTS.md`, specifications, plans, security requirements and profile configuration take precedence where they are stricter or more specific.
