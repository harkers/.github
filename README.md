# Default GitHub Standards

This repository provides default GitHub community-health files for repositories owned by `harkers`.

## Included defaults

- structured YAML Issue Forms for epics, features, implementation tasks, investigations, spikes, ADRs, bugs/incidents, model evaluations, review findings and security findings;
- a standard pull request template with testing, review, evidence-verification, specialist-review and delivery gates;
- default contribution, security and support guidance.

Repository-local files take precedence over these defaults. Engineering process, agent contracts, model routing and synchronised managed files are maintained separately in the private `harkers/repo-standards` repository.

## Principles

1. Broad work is specified and decomposed before implementation.
2. Implementation tasks are bounded and evidence-backed.
3. Builders do not provide the final independent review of their own work.
4. Reviewer findings are claims requiring evidence, not instructions to obey blindly.
5. Security and safety/policy review are specialist gates rather than substitutes for functional testing.
6. Pull requests remain draft until required validation and review gates have passed.
