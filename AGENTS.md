# AGENTS.md

## Start Here

Read `docs/ai_context/PROJECT_MAP.md` first.

Then read only the context file that matches the task.

Do not load the whole repository unless the task really crosses project boundaries.

Context is a router, not an archive.

## Rules

- Do not read or print `.env`, tokens, passwords, private keys, DB files, logs, or private user data.
- Keep edits scoped to the task.
- If a change touches production, auth, payments, deploy, data deletion, or external APIs, read `docs/ai_context/DANGER_ZONES.md` first.
- Before finishing, read `docs/ai_context/VERIFICATION.md`.
- Keep `docs/ai_context/*` short. If a context file starts growing, read `docs/ai_context/CONTEXT_HYGIENE.md`.
- Use `DECISIONS.jsonl` for durable decisions. Use `optional/FINDINGS.jsonl` only when Level 3 is enabled.

## Checks

Use the project-specific checklist in `docs/ai_context/VERIFICATION.md`.

If available, run:

```bash
./scripts/check-ai-context.sh .
```
