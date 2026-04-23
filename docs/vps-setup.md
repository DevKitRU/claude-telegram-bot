# Установка на VPS — пошагово

Гайд для новичка: от пустого VPS до работающего бота в Telegram.

## Что понадобится

- VPS с Ubuntu 22.04+ / Debian 12+ (на других Linux тоже заведётся, проверены эти).
- SSH-доступ.
- Telegram-аккаунт.
- Учётка с [Claude Pro/Max](https://claude.com/) или API-ключ (нужно для Claude Code).

---

## 1. Подготовка VPS

```bash
ssh user@your-vps.example

# Базовые пакеты
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl nano

# Node.js (для Claude Code)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Проверка
python3 --version   # 3.11+
node --version      # v20+
```

## 2. Установка Claude Code

```bash
# Глобально — но без sudo (в свой $HOME, чтобы не ловить npm-права на прод-сервере)
mkdir -p ~/.npm-global
npm config set prefix ~/.npm-global
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
source ~/.bashrc

npm install -g @anthropic-ai/claude-code
claude --version    # должно показать версию
```

Если ты в России и VPS тоже в РФ — Anthropic заблокирует логин из российских датацентров с 403. Нужно:
- Либо брать VPS вне РФ (OVH Канада, Hetzner FI/DE).
- Либо настраивать исходящий прокси через свой VLESS-tunnel (см. [my-vpn-kit](https://github.com/DevKitRU/my-vpn-kit)).

Авторизация:
```bash
claude
# В первом запуске он покажет OAuth-ссылку → открой в браузере → залогинься
```

После успеха `claude -p "привет, кто ты?"` должно отвечать.

## 3. Настройка памяти (опционально но рекомендуется)

Если хочешь чтобы Claude «знал тебя» — подключи его память к git-репо через [claude-memory-sync](https://github.com/DevKitRU/claude-memory-sync):

```bash
cd ~
git clone https://github.com/<твой-ник>/claude-memory.git
git clone https://github.com/DevKitRU/claude-memory-sync.git
cd claude-memory-sync
./setup/linux.sh
```

Без этого шага бот тоже заработает — просто Claude будет с нулевой памятью на каждой новой сессии.

## 4. Клонирование бота

```bash
cd ~
git clone https://github.com/DevKitRU/claude-telegram-bot.git
cd claude-telegram-bot
```

## 5. Создание Telegram-бота

1. В Telegram открой [@BotFather](https://t.me/BotFather).
2. `/newbot` → придумай имя (любое) и username (должен кончаться на `bot`, быть уникальным глобально).
3. BotFather пришлёт токен формата `1234567890:ABCdef...`. **Сохрани его**.
4. **Важно:** НЕ пересылай сообщение BotFather в другие чаты — токен там в открытом виде. Копируй **только** строку токена.

Узнай свой user-id: напиши [@userinfobot](https://t.me/userinfobot), он пришлёт твой `id`.

## 6. Конфигурация

```bash
cp .env.example .env
nano .env
```

Впиши:
```
BOT_TOKEN=1234567890:ABCdef...твой токен от BotFather
ADMIN_IDS=123456789        # твой id от userinfobot
```

Если нужно несколько админов: `ADMIN_IDS=111,222,333`.

```bash
cp config/projects.example.json config/projects.json
nano config/projects.json
```

Поправь пути под себя:
```json
{
    "default": "/home/ubuntu",
    "aliases": {
        "home": "/home/ubuntu",
        "memory": "/home/ubuntu/claude-memory"
    }
}
```

Тут `default` — откуда Claude стартует по умолчанию. `aliases` — что можно указать в `/cd <name>`.

Права на `.env` (важно — там токен):
```bash
chmod 600 .env
```

## 7. Python venv + запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Проверка что запускается руками
.venv/bin/python bot.py
```

Если всё ок — в терминале будет `[INFO] Бот запущен...`. Напиши боту в Telegram `/start` — должен ответить. Если не отвечает:
- Проверь что токен правильный (нет лишних пробелов/переносов в `.env`).
- Проверь что твой `id` в `ADMIN_IDS`.
- Проверь что VPS имеет исходящий интернет к `api.telegram.org` (`curl -sI https://api.telegram.org`).

Теперь останови (`Ctrl+C`) и ставь через systemd.

## 8. Systemd

Отредактируй unit под свои пути:
```bash
nano claude-telegram-bot.service
```

Замени `ubuntu` на своё имя пользователя, поправь путь `/home/ubuntu/claude-telegram-bot` если у тебя другой.

```bash
sudo cp claude-telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now claude-telegram-bot

# Проверка
sudo systemctl status claude-telegram-bot
sudo journalctl -u claude-telegram-bot -f
```

В логе должно быть `Бот запущен`. Напиши в Telegram — готово.

---

## Грабли

### Claude CLI не найден

В логе `❌ Claude CLI не найден: /usr/local/bin/claude`. Посмотри где он реально:
```bash
which claude   # /home/ubuntu/.npm-global/bin/claude
```

В `.env` пропиши точный путь:
```
CLAUDE_BIN=/home/ubuntu/.npm-global/bin/claude
```

Перезапусти сервис: `sudo systemctl restart claude-telegram-bot`.

### Таймаут на длинных запросах

По умолчанию `CLAUDE_TIMEOUT=300` (5 минут). Если Claude долго работает (например ищет по большой кодовой базе) — увеличь в `.env`:
```
CLAUDE_TIMEOUT=900
```

### Бот работает, но Claude «не помнит» меня

Значит память не подключена. Проверь:
```bash
ls ~/.claude/projects/
# Должна быть одна или несколько папок типа -home-ubuntu/
ls ~/.claude/projects/-home-ubuntu/memory/
# Должны быть MEMORY.md и другие файлы
```

Если папка пустая — либо поставь [claude-memory-sync](https://github.com/DevKitRU/claude-memory-sync) и клонируй свой memory-репо, либо просто начни писать Claude — он сам создаст.

### `Telegram API timeout` в логах

Сеть нестабильна либо VPS за прокси. Если у тебя VPS за файрволом:
- Открой исходящий на `149.154.160.0/20` (Telegram DC).
- Или используй `base_url` через webhook — но это доп. настройка, за рамками этого гайда.

### systemd падает с `KillMode=process` warning

Это норма. `KillMode=process` нужен чтобы при рестарте бота не убивать уже запущенные claude-subprocess'ы (иначе long-running ответы оборвутся). Варнинг можно игнорировать.

---

## Обновление

```bash
cd ~/claude-telegram-bot
git pull
.venv/bin/pip install -r requirements.txt   # на случай новых зависимостей
sudo systemctl restart claude-telegram-bot
sudo journalctl -u claude-telegram-bot -f
```

## Удаление

```bash
sudo systemctl disable --now claude-telegram-bot
sudo rm /etc/systemd/system/claude-telegram-bot.service
sudo systemctl daemon-reload
rm -rf ~/claude-telegram-bot
```

---

## Что дальше

- Почитай [README.md](../README.md) — что бот умеет и чего пока нет.
- Если столкнулся с новой граблей — открой issue в репо, добавим в этот гайд.
