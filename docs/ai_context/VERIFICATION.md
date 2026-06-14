# VERIFICATION

Что проверить перед финалом.

## Docs-only

```bash
git diff --check
./scripts/check-ai-context.sh .
```

`check-ai-context.sh` может предупредить про tracked `.env.example`; для этого публичного repo это ожидаемо, если файл содержит только placeholders.

## Python

```bash
python3 -m py_compile bot.py
```

## Dependency sanity

```bash
python3 -m venv /tmp/claude-telegram-bot-venv
/tmp/claude-telegram-bot-venv/bin/pip install -r requirements.txt
```

Не запускай `bot.py` как smoke без тестового `.env`, Telegram token и изолированного VPS-сценария.

## Safety checklist

- Реальные Telegram tokens/user IDs не попали в diff.
- Runtime DB/log/session файлы не попали в git.
- Если менялся subprocess command, объяснен риск `--dangerously-skip-permissions`.
- В `SESSION_SUMMARY.md` записано, что изменилось.
