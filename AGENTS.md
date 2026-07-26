# Public Repository Privacy Rules

These rules apply to the entire ReelFire repository.

## Required anonymization

- Treat this repository as public. Never add real names, student numbers, personal email addresses, phone numbers, private account identifiers, home addresses, or other personally identifying information.
- In source code, tests, documentation, screenshots, reports, examples, logs, fixtures, and commit-ready generated files, identify contributors only by project roles such as `产品与项目负责人`, `CV/数据工程师`, `后端工程师`, `前端工程师`, and `Agent/工作流工程师`.
- Do not copy, quote, link to, summarize, or expose the contents of the local `RealName.md` mapping in any tracked file. `RealName.md` must remain ignored by Git and local-only.
- Do not add absolute local filesystem paths, machine usernames, access tokens, API keys, private repository URLs, or environment-specific secrets.
- Before committing or pushing, review all tracked changes, screenshots, exported reports, logs, Git patches, and generated artifacts for personal information. If uncertain, remove or generalize the data.
- Personal mappings needed for private course administration must be stored outside this public repository or in an explicitly ignored local file.

## Verification

- Confirm `RealName.md` remains ignored with `git check-ignore -q RealName.md`.
- Search all tracked files for any known private identifiers before commit or push.
- Inspect `git diff --cached` and newly added binary assets before publishing.
- If personal information is found in tracked content, replace it with a role label before continuing.
