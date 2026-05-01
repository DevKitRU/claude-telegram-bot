"""
claude-telegram-bot — Telegram-бот для работы с Claude Code CLI с телефона.

Любое сообщение из разрешённого чата превращается в промт в Claude-сессии,
Claude запускается как CLI subprocess с нужным cwd. Сессии хранятся в SQLite
по chat_id, память Claude (та что в ~/.claude/projects/<hash>/memory/)
подгружается автоматически по cwd — Claude "знает тебя" на каждом проекте.

Установка: см. README.md + docs/vps-setup.md.
"""
import os
import json
import sqlite3
import asyncio
import logging
import shutil
import time
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from telegram import (
    Update,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# ——— Обязательная конфигурация ———
BOT_TOKEN = os.environ["BOT_TOKEN"]

# Несколько админов через запятую: ADMIN_IDS=12345,67890
_admin_ids_raw = os.environ.get("ADMIN_IDS") or os.environ.get("ADMIN_ID", "")
ADMIN_IDS = {int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip()}
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS or ADMIN_ID must be set in .env")

# ——— Опциональная конфигурация ———
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "/usr/local/bin/claude"
DB_PATH = Path(os.environ.get("DB_PATH", "data/bot.db")).resolve()
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "300"))
PROJECTS_FILE = Path(os.environ.get("PROJECTS_FILE", "config/projects.json")).resolve()

# Если config/projects.json нет — используем $HOME и fallback
def load_projects() -> tuple[str, dict[str, str]]:
    default_project = os.environ.get("DEFAULT_PROJECT") or str(Path.home())
    aliases: dict[str, str] = {}
    if PROJECTS_FILE.exists():
        try:
            data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
            default_project = data.get("default", default_project)
            aliases = {k: os.path.expanduser(v) for k, v in (data.get("aliases") or {}).items()}
        except Exception as e:
            logging.warning("Не смог прочесть %s: %s — использую дефолт", PROJECTS_FILE, e)
    # Всегда добавляем ~ как алиас на $HOME
    aliases.setdefault("~", str(Path.home()))
    aliases.setdefault("home", str(Path.home()))
    return default_project, aliases


DEFAULT_PROJECT, PROJECT_ALIASES = load_projects()

# ——— UI ———
BTN_NEW = "🆕 Новая"
BTN_PROJECT = "📁 Проект"
BTN_SESSIONS = "📜 Сессии"
BTN_WHERE = "📍 Где я"
BTN_STATUS = "🖥 Статус"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_NEW), KeyboardButton(BTN_PROJECT), KeyboardButton(BTN_STATUS)],
        [KeyboardButton(BTN_SESSIONS), KeyboardButton(BTN_WHERE)],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

BOT_COMMANDS = [
    BotCommand("start", "приветствие и текущее состояние"),
    BotCommand("new", "новая сессия (забыть контекст)"),
    BotCommand("cd", "сменить проект"),
    BotCommand("cwd", "текущий проект и сессия"),
    BotCommand("sessions", "последние 10 сессий"),
    BotCommand("resume", "вернуться к сессии по id"),
    BotCommand("status", "системные метрики"),
]

# ——— Логирование ———
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
log = logging.getLogger("claude-telegram-bot")


# ——— SQLite ———
def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    # WAL для конкурентного чтения/записи (несколько админов, одновременный
    # on_callback + on_message не блокируют друг друга).
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS state (
            chat_id INTEGER PRIMARY KEY,
            session_id TEXT,
            project_path TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            project_path TEXT NOT NULL,
            first_prompt TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def get_state(chat_id: int) -> tuple[str | None, str]:
    conn = db()
    row = conn.execute(
        "SELECT session_id, project_path FROM state WHERE chat_id=?",
        (chat_id,),
    ).fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return None, DEFAULT_PROJECT


def set_state(chat_id: int, session_id: str | None, project_path: str) -> None:
    conn = db()
    conn.execute(
        """INSERT INTO state (chat_id, session_id, project_path, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET
             session_id=excluded.session_id,
             project_path=excluded.project_path,
             updated_at=excluded.updated_at""",
        (chat_id, session_id, project_path, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def remember_session(session_id: str, chat_id: int, project_path: str, first_prompt: str) -> None:
    conn = db()
    conn.execute(
        """INSERT OR IGNORE INTO sessions (session_id, chat_id, project_path, first_prompt, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, chat_id, project_path, first_prompt[:200], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def list_sessions(chat_id: int, limit: int = 10) -> list[tuple]:
    conn = db()
    rows = conn.execute(
        """SELECT session_id, project_path, first_prompt, created_at
           FROM sessions WHERE chat_id=?
           ORDER BY created_at DESC LIMIT ?""",
        (chat_id, limit),
    ).fetchall()
    conn.close()
    return rows


# ——— Права доступа ———
def is_admin(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id in ADMIN_IDS


async def deny(update: Update):
    """Безопасное сообщение об отказе — работает и для обычных чатов, и для callback'ов."""
    if update.message:
        await update.message.reply_text("⛔ Доступ запрещён.")
    elif update.callback_query:
        try:
            await update.callback_query.answer("⛔ Доступ запрещён.", show_alert=True)
        except Exception:
            pass


# ——— Запуск Claude CLI ———
async def run_claude(
    prompt: str,
    project_path: str,
    session_id: str | None,
    on_event=None,
) -> tuple[str, str | None, str | None]:
    """Вызывает Claude CLI в stream-json режиме.

    Возвращает: (final_text, new_session_id, error_message).
    on_event(kind, payload) — callback для отправки прогресса в UI.
    """
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]
    if session_id:
        cmd += ["--resume", session_id]

    log.info("claude run cwd=%s session=%s", project_path, session_id)
    try:
        # ВАЖНО: передаём Claude минимальный env. По дефолту systemd EnvironmentFile
        # подставляет ВСЁ из .env включая BOT_TOKEN и ADMIN_IDS — Claude c
        # --dangerously-skip-permissions может прочитать их через `Bash: env`
        # и выдать в чат. Поэтому явный whitelist переменных которые ему реально нужны.
        SAFE_ENV_KEYS = {
            "PATH", "HOME", "USER", "LOGNAME", "SHELL",
            "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ",
            "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
            "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
            "https_proxy", "http_proxy", "no_proxy",
        }
        env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        return "", None, f"❌ Claude CLI не найден: {CLAUDE_BIN}"
    except Exception as e:
        return "", None, f"❌ Ошибка запуска: {e}"

    final_text = ""
    new_sid = session_id
    accumulated_text = ""

    async def read_stream():
        nonlocal final_text, new_sid, accumulated_text
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                ev = json.loads(line.decode(errors="replace"))
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "system" and ev.get("subtype") == "init":
                new_sid = ev.get("session_id") or new_sid
            elif t == "assistant":
                msg = ev.get("message", {}) or {}
                for block in msg.get("content", []) or []:
                    bt = block.get("type")
                    if bt == "tool_use" and on_event:
                        tool_name = block.get("name", "?")
                        tin = block.get("input", {}) or {}
                        if "command" in tin:
                            preview = str(tin["command"])[:120]
                        elif "file_path" in tin:
                            preview = str(tin["file_path"])
                        elif "url" in tin:
                            preview = str(tin["url"])[:120]
                        elif "pattern" in tin:
                            preview = str(tin["pattern"])[:80]
                        else:
                            preview = json.dumps(tin, ensure_ascii=False)[:120]
                        try:
                            await on_event("tool", f"{tool_name}: {preview}")
                        except Exception as e:
                            log.warning("on_event tool failed: %s", e)
                    elif bt == "text":
                        accumulated_text = block.get("text", "") or accumulated_text
            elif t == "result":
                final_text = ev.get("result", "") or final_text
                new_sid = ev.get("session_id") or new_sid

    try:
        await asyncio.wait_for(read_stream(), timeout=CLAUDE_TIMEOUT)
        await proc.wait()
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return "", None, f"⏱ Таймаут (>{CLAUDE_TIMEOUT}с)"

    if proc.returncode != 0:
        stderr = (await proc.stderr.read()).decode(errors="replace").strip()
        return "", None, f"❌ exit {proc.returncode}: {stderr[:1500] or 'без stderr'}"

    text = final_text or accumulated_text
    if not text:
        return "", None, "❌ Пустой ответ"
    return text, new_sid, None


async def send_chunked(update: Update, text: str) -> None:
    """TG лимит 4096 — режем на куски. Клавиатуру только на последнем."""
    LIMIT = 3900
    if len(text) <= LIMIT:
        await update.message.reply_text(text, reply_markup=MAIN_KEYBOARD)
        return
    chunks = [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)]
    for i, c in enumerate(chunks):
        prefix = f"({i + 1}/{len(chunks)})\n" if i == 0 else ""
        is_last = i == len(chunks) - 1
        await update.message.reply_text(
            prefix + c,
            reply_markup=MAIN_KEYBOARD if is_last else None,
        )


def project_picker_keyboard() -> InlineKeyboardMarkup:
    """Inline-клавиатура со всеми проектами из конфига."""
    rows = []
    row: list[InlineKeyboardButton] = []
    for alias in PROJECT_ALIASES:
        row.append(InlineKeyboardButton(alias, callback_data=f"cd:{alias}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# ——— Команды ———
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    session_id, project = get_state(update.effective_chat.id)
    await update.message.reply_text(
        f"👋 Привет. Я — твой Claude Code на этом сервере.\n\n"
        f"📁 Проект: <code>{project}</code>\n"
        f"🔗 Сессия: <code>{session_id or 'новая будет создана'}</code>\n\n"
        f"Любое сообщение — промт в Claude. Команды в меню или через /.",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    _, project = get_state(update.effective_chat.id)
    set_state(update.effective_chat.id, None, project)
    await update.message.reply_text(
        "🆕 Сессия сброшена. Следующее сообщение создаст новую.",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_cwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    sid, project = get_state(update.effective_chat.id)
    await update.message.reply_text(
        f"📁 Проект: <code>{project}</code>\n🔗 Сессия: <code>{sid or '—'}</code>",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_cd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Выбери проект:",
            reply_markup=project_picker_keyboard(),
        )
        return
    target = " ".join(args).strip()
    # ВАЖНО: только whitelisted пути из config/projects.json.
    # Произвольные пути запрещены — иначе /cd /etc + --dangerously-skip-permissions даст
    # Claude root-read на VPS. Чтобы разрешить новый путь — добавь в config/projects.json.
    if target in PROJECT_ALIASES:
        path = PROJECT_ALIASES[target]
    elif target == DEFAULT_PROJECT or Path(target).resolve() == Path(DEFAULT_PROJECT).resolve():
        path = DEFAULT_PROJECT
    else:
        await update.message.reply_text(
            f"❌ Проект <code>{target}</code> не в whitelist.\n\n"
            f"Доступные алиасы: {', '.join(PROJECT_ALIASES.keys())}\n\n"
            f"Чтобы добавить новый путь — пропиши в <code>config/projects.json</code> и рестартни бот.",
            parse_mode="HTML",
            reply_markup=MAIN_KEYBOARD,
        )
        return
    if not Path(path).is_dir():
        await update.message.reply_text(
            f"❌ Директории нет: <code>{path}</code> (алиас есть в конфиге, но путь битый)",
            parse_mode="HTML",
            reply_markup=MAIN_KEYBOARD,
        )
        return
    # Смена проекта — новая сессия (контекст другой)
    set_state(update.effective_chat.id, None, path)
    await update.message.reply_text(
        f"✅ Переключился на <code>{path}</code>\nСессия обнулена (новая память).",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    rows = list_sessions(update.effective_chat.id, 10)
    if not rows:
        await update.message.reply_text("Пока нет сохранённых сессий.", reply_markup=MAIN_KEYBOARD)
        return
    lines = ["📜 Последние сессии (нажми чтобы продолжить):\n"]
    keyboard = []
    for i, (sid, proj, prompt, created) in enumerate(rows, 1):
        short_sid = sid[:8]
        short_prompt = (prompt or "").replace("\n", " ")[:60]
        lines.append(f"{i}) <code>{short_sid}</code> [{Path(proj).name}] {short_prompt}")
        keyboard.append([InlineKeyboardButton(f"{i}) {short_sid}", callback_data=f"resume:{sid}")])
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def resume_text(chat_id: int, sid: str) -> str:
    conn = db()
    row = conn.execute(
        "SELECT project_path FROM sessions WHERE session_id=? AND chat_id=?",
        (sid, chat_id),
    ).fetchone()
    conn.close()
    if not row:
        return "❌ Сессия не найдена или не твоя."
    set_state(chat_id, sid, row[0])
    return f"✅ Вернулись в сессию <code>{sid[:8]}</code>\n📁 <code>{row[0]}</code>"


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    args = context.args or []
    if not args:
        await update.message.reply_text("Использование: /resume <session_id>", reply_markup=MAIN_KEYBOARD)
        return
    text = resume_text(update.effective_chat.id, args[0].strip())
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=MAIN_KEYBOARD)


# ——— /status (агностический, без сервис-списков) ———
async def _sh(cmd: list[str], timeout: int = 5) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return out.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        return "⏱ timeout"
    except FileNotFoundError:
        return "—"
    except Exception as e:
        return f"err: {e}"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    # Агностические метрики: работает на Linux и macOS без дополнительных зависимостей.
    uptime = await _sh(["uptime"])
    df = await _sh(["df", "-h", str(Path.home())])
    mem_line = ""
    try:
        if Path("/proc/meminfo").exists():
            meminfo = Path("/proc/meminfo").read_text().split("\n")
            total = int(next(l for l in meminfo if l.startswith("MemTotal:")).split()[1])
            avail = int(next(l for l in meminfo if l.startswith("MemAvailable:")).split()[1])
            used_pct = (total - avail) * 100 // total
            mem_line = f"RAM: {used_pct}% used ({(total - avail) // 1024}/{total // 1024} MB)"
    except Exception as e:
        mem_line = f"RAM: — ({e})"

    text = (
        f"🖥 <b>Status</b>\n\n"
        f"<code>{uptime}</code>\n\n"
        f"{mem_line}\n\n"
        f"<code>{df}</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=MAIN_KEYBOARD)


# ——— Обработчики кнопок ———
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    q = update.callback_query
    data = q.data or ""
    chat_id = q.message.chat.id if q.message and q.message.chat else q.from_user.id

    if data.startswith("cd:"):
        alias = data[3:]
        if alias not in PROJECT_ALIASES:
            await q.edit_message_text(f"❌ Неизвестный проект: {alias}")
            await q.answer()
            return
        path = PROJECT_ALIASES[alias]
        if Path(path).is_dir():
            set_state(chat_id, None, path)
            await q.edit_message_text(
                f"✅ Переключился на <code>{path}</code>\nСессия обнулена.",
                parse_mode="HTML",
            )
        else:
            await q.edit_message_text(f"❌ Директории нет: {path}")
    elif data.startswith("resume:"):
        sid = data[7:]
        text = resume_text(chat_id, sid)
        await q.edit_message_text(text, parse_mode="HTML")

    try:
        await q.answer()
    except Exception:
        pass  # callback истёк — не критично


# ——— Основной обработчик текста ———
async def process_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    chat_id = update.effective_chat.id
    session_id, project = get_state(chat_id)

    # Показываем "typing" и отправляем стартовое сообщение
    await update.message.chat.send_action(ChatAction.TYPING)
    progress_msg = await update.message.reply_text(f"⏳ Думаю в <code>{Path(project).name}</code>...", parse_mode="HTML")

    tool_lines: list[str] = []
    last_edit_ts = 0.0  # debounce — Telegram rate-limit edit одного сообщения: 1/сек

    async def on_event(kind: str, payload: str):
        nonlocal last_edit_ts
        if kind == "tool":
            tool_lines.append(f"🔧 {payload}")
            now = time.monotonic()
            if now - last_edit_ts < 1.2:
                return  # пропускаем — отрисуем со следующим tool или в финале
            last_edit_ts = now
            try:
                preview = "\n".join(tool_lines[-6:])
                await progress_msg.edit_text(f"⏳ Работаю...\n\n{preview}", parse_mode=None)
            except Exception:
                pass

    text, new_sid, error = await run_claude(prompt, project, session_id, on_event=on_event)

    try:
        await progress_msg.delete()
    except Exception:
        pass

    if error:
        await update.message.reply_text(error, reply_markup=MAIN_KEYBOARD)
        return

    # Запоминаем новую сессию если она впервые
    if new_sid and new_sid != session_id:
        remember_session(new_sid, chat_id, project, prompt)
    set_state(chat_id, new_sid, project)

    await send_chunked(update, text)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    text = (update.message.text or "").strip()
    if not text:
        return

    # Обработка reply-кнопок
    if text == BTN_NEW:
        return await cmd_new(update, context)
    if text == BTN_PROJECT:
        await update.message.reply_text("Выбери проект:", reply_markup=project_picker_keyboard())
        return
    if text == BTN_SESSIONS:
        return await cmd_sessions(update, context)
    if text == BTN_WHERE:
        return await cmd_cwd(update, context)
    if text == BTN_STATUS:
        return await cmd_status(update, context)

    await process_prompt(update, context, text)


# ——— Инициализация ———
async def post_init(app: Application):
    await app.bot.set_my_commands(BOT_COMMANDS)
    log.info("Бот запущен. Проекты: %s. Админы: %s", list(PROJECT_ALIASES), list(ADMIN_IDS))


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("cd", cmd_cd))
    app.add_handler(CommandHandler("cwd", cmd_cwd))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
