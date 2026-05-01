# claude-telegram-bot

Telegram-бот для работы с [Claude Code](https://claude.com/claude-code) на своём VPS.

Зачем он нужен: Claude Code стоит на VPS, там же лежат проекты и память. С телефона хочется отправить задачу, проверить статус или продолжить сессию без ноутбука.

Любое текстовое сообщение уходит в текущую Claude-сессию на сервере. Ответ и прогресс по инструментам возвращаются в Telegram.

Что умеет:
- Whitelist по Telegram user-id.
- Хранит `session_id` Claude в SQLite.
- Продолжает ту же сессию при следующем сообщении.
- Переключает проекты через `/cd <alias>`.
- Показывает, какие инструменты вызывает Claude.
- Показывает историю сессий через `/sessions`.
- Показывает uptime, RAM и диск через `/status`.

Чего пока нет: голосовых, approval-hooks, фото и документов.

---

## Архитектура

```
Telegram   ->   bot.py (systemd)   ->   claude -p "..." --resume <sid>
                      │                       │
                      ▼                       ▼
                  SQLite                  ~/.claude/projects/<hash>/memory/
                  (chat_id ->             (читается автоматически, т.к.
                  session_id,              запускаем с cwd = project_path)
                  project_path)
```

- Claude CLI запускается в headless-режиме (`-p`) с `--output-format stream-json`.
- Бот читает JSONL поток и вытаскивает `tool_use`, финальный текст и новый `session_id`.
- Смена проекта (`/cd`) обнуляет `session_id`, потому что у другого `cwd` другая память.

Про `--dangerously-skip-permissions`: это опасный режим. Я использую его только для личного бота на своём VPS. Если даёшь доступ другим людям, убери флаг и продумай approval-flow.

---

## Установка на VPS (3 шага)

Предполагается Linux-сервер (Ubuntu/Debian проверены), установленные [Claude Code](https://claude.com/claude-code), Python 3.11+, systemd, git.

### 1. Клонировать и настроить

```bash
ssh user@your-vps
cd ~
git clone https://github.com/DevKitRU/claude-telegram-bot.git
cd claude-telegram-bot

cp .env.example .env
cp config/projects.example.json config/projects.json
```

Открой `.env` и впиши `BOT_TOKEN` (получить у [@BotFather](https://t.me/BotFather)) и `ADMIN_IDS` (узнать свой Telegram user-id у [@userinfobot](https://t.me/userinfobot)).

Открой `config/projects.json` и пропиши реальные пути к твоим проектам и дефолтный.

### 2. Python venv и зависимости

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Проверь что Claude Code установлен и работает:
```bash
which claude
claude --version
```

Если `which claude` не находит, в `.env` укажи полный путь: `CLAUDE_BIN=/home/user/.npm-global/bin/claude`.

### 3. Запуск через systemd

```bash
# Отредактируй пути в unit-файле под свой $HOME и имя пользователя
nano claude-telegram-bot.service

sudo cp claude-telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now claude-telegram-bot

# Посмотреть логи:
sudo journalctl -u claude-telegram-bot -f
```

Напиши боту в Telegram `/start`. Он должен ответить текущим проектом.

Подробная инструкция: [docs/vps-setup.md](docs/vps-setup.md).

---

## Использование

- Любое текстовое сообщение: промт в текущую сессию Claude.
- `/new`: начать новую сессию.
- `/cd <alias>`: переключиться на проект из `config/projects.json`.
- `/cwd`: показать текущий проект и id сессии.
- `/sessions`: последние 10 сессий.
- `/resume <session_id>`: продолжить конкретную сессию.
- `/status`: uptime, RAM, диск.

Нижнее reply-меню дублирует основные команды кнопками.

---

## Безопасность

1. Whitelist через `ADMIN_IDS`.
2. Токен хранится в `.env`. Файл `.env` в `.gitignore`.
3. Для бота лучше использовать отдельный VPS. С `--dangerously-skip-permissions` Claude получает shell на сервере.
4. Включи 2FA на Telegram-аккаунте. Угон аккаунта означает доступ к боту.
5. Не держи production-ключи в переписке и памяти. Храни их отдельно, например в `~/.claude/secrets/api-keys.env`.
6. Бот глушит `httpx` до WARNING, чтобы URL с токеном не попадал в INFO-логи. Всё равно проверь свои логи на VPS.

---

## Что ещё в репо

- [bot.py](bot.py): основной код.
- [config/projects.example.json](config/projects.example.json): шаблон алиасов проектов.
- [.env.example](.env.example): env-переменные.
- [claude-telegram-bot.service](claude-telegram-bot.service): systemd unit.
- [docs/vps-setup.md](docs/vps-setup.md): установка на VPS.

---

## Roadmap

- [ ] Голосовые сообщения через Groq Whisper (по env-флагу `GROQ_API_KEY`).
- [ ] Approval-hook: кнопки в Telegram для опасных команд.
- [ ] Multi-user: отдельные сессии per-user, не один whitelist.
- [ ] Фото и документы как контекст для Claude.
- [ ] Android/iOS PWA вместо бота.

Issues лучше PR на этом этапе. Так проще понять, какие сценарии повторяются.

---

## Лицензия

[MIT](LICENSE).
