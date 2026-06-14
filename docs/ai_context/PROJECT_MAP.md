# PROJECT_MAP

Короткая карта `claude-telegram-bot` для Codex, Claude и других AI-агентов.

Это роутер, а не архив.

## Что это за проект

Публичный DevKitRU Telegram bot для управления Claude Code на своем VPS.

Бот принимает сообщения из whitelisted Telegram user IDs, запускает `claude -p` в выбранном project cwd, хранит session_id в SQLite и возвращает ответ/progress в Telegram.

## Быстрый вход

1. Прочитай этот файл.
2. Если задача касается `.env`, доступа, systemd, Claude CLI permissions или VPS, прочитай `DANGER_ZONES.md`.
3. Открой только `bot.py` и нужный doc/config.
4. Перед финалом смотри `VERIFICATION.md`.

## Карта файлов

| Путь | Роль | Читать когда |
| --- | --- | --- |
| `README.md` | Главная витрина и usage | Меняем публичную подачу |
| `bot.py` | Основной Telegram/Claude runtime | Меняем поведение бота |
| `.env.example` | Env template без реальных значений | Меняем конфигурацию |
| `config/projects.example.json` | Project alias template | Меняем `/cd` и project routing docs |
| `claude-telegram-bot.service` | systemd unit template | Меняем deploy/service docs |
| `docs/vps-setup.md` | Пошаговая установка на VPS | Меняем beginner onboarding |
| `requirements.txt` | Python deps | Меняем runtime dependencies |

## Главные потоки

- Telegram message -> whitelist check -> SQLite state -> `claude -p ... --resume` -> stream-json parser -> Telegram reply.
- `/cd <alias>` -> whitelist path from `config/projects.json` -> reset session -> next prompt starts in new cwd.
- `.env` -> bot runtime only. Claude subprocess gets a filtered env to reduce secret leakage.

## Точки поиска

```bash
rg -n "dangerously|ADMIN_IDS|BOT_TOKEN|CLAUDE_BIN|session_id|projects.json|systemd|stream-json" .
rg -n "TODO|Roadmap|approval|voice|GROQ|timeout|whitelist" .
```

## Правило контекста

Не читать `.env`, runtime DB, Telegram logs или реальные project configs.

Сначала карта. Потом danger zones. Потом конкретный файл.
