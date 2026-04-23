# claude-telegram-bot

Telegram-бот, через который ты говоришь с [Claude Code](https://claude.com/claude-code) на своём VPS с любого телефона. Любое сообщение в чат = промт в текущую Claude-сессию на сервере. Ответ Claude, включая прогресс по инструментам — в чат.

**Зачем:** есть VPS с установленным Claude Code и собственной памятью (`~/.claude/projects/<hash>/memory`, через [claude-memory-sync](https://github.com/DevKitRU/claude-memory-sync) или руками). Хочется общаться с ним с телефона в метро, не таскать ноут. Родного мобильного клиента у Claude Code нет — бот закрывает пробел.

**Что умеет:**
- Whitelist по Telegram user-id (кто не в списке — `⛔ Доступ запрещён`).
- Сохраняет `session_id` Claude per-chat в SQLite. Следующее сообщение продолжает ту же сессию — Claude помнит прошлый контекст.
- Переключение между проектами через `/cd <alias>`: меняется `cwd` Claude → подтягивается память конкретного проекта. Алиасы настраиваешь в `config/projects.json`.
- Показ прогресса: пока Claude работает — видно какие инструменты он зовёт (`Bash: ls ...`, `Read: /etc/...`, `Grep: ...`).
- История сессий (`/sessions`) с возможностью вернуться в любую (`/resume <id>`).
- Системные метрики (`/status`): uptime, RAM, диск — агностично, без hardcoded-списков сервисов.

**Чего НЕ умеет (пока):** голосовые (TODO, через Groq Whisper), approval-hooks (для блокировки опасных команд), мультимедиа (фото/документы).

---

## Архитектура

```
Telegram   →   bot.py (systemd)   →   claude -p "..." --resume <sid>
                      │                       │
                      ▼                       ▼
                  SQLite                  ~/.claude/projects/<hash>/memory/
                  (chat_id →              (читается автоматически, т.к.
                  session_id,              запускаем с cwd = project_path)
                  project_path)
```

- Claude CLI запускается в headless-режиме (`-p`) с `--output-format stream-json` — бот читает JSONL поток событий и вытаскивает `tool_use`, финальный текст, новый `session_id`.
- `--dangerously-skip-permissions` — да, опасно. Для personal-use бота на твоём VPS ок; если расшариваешь с людьми — снимай флаг, но тогда каждый bash-вызов будет зависать (у Claude нет способа спросить approval через stdin в headless-режиме). В v2 планирую approval-hook с reply-кнопками в TG.
- Смена проекта (`/cd`) автоматически обнуляет `session_id` — в новом `cwd` другая память, смешивать сессии нельзя.

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

Открой `.env` — впиши `BOT_TOKEN` (получить у [@BotFather](https://t.me/BotFather)) и `ADMIN_IDS` (узнать свой Telegram user-id у [@userinfobot](https://t.me/userinfobot)).

Открой `config/projects.json` — пропиши реальные пути к твоим проектам и дефолтный.

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

Если `which claude` не находит — в `.env` укажи полный путь: `CLAUDE_BIN=/home/user/.npm-global/bin/claude`.

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

Напиши боту в Telegram `/start` — должен ответить приветствием с твоим текущим проектом.

Подробная инструкция с граблями — [docs/vps-setup.md](docs/vps-setup.md).

---

## Использование

- **Любое текстовое сообщение** — промт в текущую сессию Claude. Если сессии ещё нет, создаст новую.
- `/new` — забыть текущий контекст, следующее сообщение начнёт с нуля.
- `/cd <alias>` — переключиться на проект из `config/projects.json` (или `/cd` без аргумента — покажет кнопки).
- `/cwd` — показать текущий проект и id сессии.
- `/sessions` — последние 10 сессий, можно нажать кнопку чтобы вернуться.
- `/resume <session_id>` — продолжить конкретную сессию (первые 8 символов id достаточны).
- `/status` — uptime, RAM, диск.

Нижнее reply-меню дублирует основные команды кнопками — удобно с телефона.

---

## Безопасность

1. **Whitelist через `ADMIN_IDS`** — все остальные отказ.
2. **Токен в `.env`**, `.env` в `.gitignore` — никогда не уходит в git.
3. **Рекомендуется fresh VPS**: сам бот имеет полный `sudo` через Claude (`--dangerously-skip-permissions`). Если кому-то удастся обойти whitelist (например через уязвимость в `python-telegram-bot`) — он получит shell на твоём VPS. Поэтому:
   - **Не держи в переписке/памяти ключи от production-сервисов.** Ключи — в `~/.claude/secrets/api-keys.env` (chmod 600), с чётким разделением dev/prod.
   - **2FA на Telegram-аккаунте обязательно.** Угон аккаунта = угон бота.
   - **Для чувствительных операций делай separate VPS** — не смешивай бот-подсобку с инфрой которую нельзя потерять.
4. **Логи**: `httpx` логирует URL с токеном в INFO — бот глушит их до WARNING, но убедись что твой `journalctl` не утекает куда-то наружу (на VPS по умолчанию — локальный journal, ок).

---

## Что ещё в репо

- [bot.py](bot.py) — весь код, ~500 строк, monolithic на python-telegram-bot.
- [config/projects.example.json](config/projects.example.json) — шаблон алиасов проектов.
- [.env.example](.env.example) — env-переменные с комментариями.
- [claude-telegram-bot.service](claude-telegram-bot.service) — systemd unit (шаблон).
- [docs/vps-setup.md](docs/vps-setup.md) — пошаговая установка с граблями.

---

## Roadmap

- [ ] Голосовые сообщения через Groq Whisper (по env-флагу `GROQ_API_KEY`).
- [ ] Approval-hook: когда Claude хочет `rm -rf` / `git push --force` — TG-кнопки «разрешить / запретить».
- [ ] Multi-user: отдельные сессии per-user, не один whitelist.
- [ ] Фото и документы — передавать в Claude как контекст.
- [ ] Android/iOS PWA вместо бота — если Telegram заблокируют.

PR приветствуются. Issues тоже.

---

## Лицензия

[MIT](LICENSE).
