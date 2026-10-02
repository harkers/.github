# Security Policy

## Reporting security issues

Do not publish credentials, tokens, private keys, exploitable secret material, or sensitive logs in public issues.

For repository-level security findings, use the structured Security Finding form only when it is safe to disclose the technical details. Otherwise report privately to the repository owner before public disclosure.

## Review expectations

Changes touching authentication, authorisation, credentials, filesystem/path handling, shell or command execution, network exposure, dependency/supply-chain trust, logging/data leakage, prompt/tool abuse, or write-capable agent control planes require specialist security review.

Security-review findings are evidence-backed claims and should be independently verified before remediation work is accepted as complete.

## Cloud review boundary

Do not send secrets, credentials, `.env` material, private keys, unrelated repository content, or other unnecessary sensitive material to cloud-hosted review models. Supply only the minimum context required for the review.
