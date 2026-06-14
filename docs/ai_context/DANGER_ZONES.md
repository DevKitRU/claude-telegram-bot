# DANGER_ZONES

Куда агенту нельзя лезть без явной причины.

## Секреты и доступ

- Не читать и не печатать `.env`.
- Не добавлять реальные `BOT_TOKEN`, `ADMIN_IDS`, API keys или Telegram user data.
- Не коммитить `config/projects.json` с реальными путями, если он не является примером.
- Не коммитить `data/*.db`, SQLite WAL/SHM, logs или session dumps.

## Claude permissions

- `bot.py` запускает Claude CLI с `--dangerously-skip-permissions`.
- Это допустимо только для личного whitelisted VPS-сценария.
- Любые изменения access control, env filtering, project whitelist или subprocess command требуют отдельного review.
- Не расширять `/cd` на произвольные пути. Только aliases из `config/projects.json`.

## VPS/systemd

- `claude-telegram-bot.service` влияет на автозапуск.
- Не менять systemd unit как побочный эффект docs-задачи.
- Не запускать или рестартить сервис на реальном VPS без явной команды.

## Telegram UX

- Не печатать private prompts, session IDs или project paths в публичные docs.
- Не добавлять multi-user behavior без ясного per-user state model.
- Approval hooks и file/photo upload требуют отдельного threat model.
