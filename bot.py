from __future__ import annotations
import asyncio
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

# --- mini servidor HTTP para "abrir porta" no Render ---
from aiohttp import web

# ==========================
# Configuração e constantes
# ==========================
EMPREGADOS: List[str] = [
    "Secretaria", "Serviços", 
    "Lucas", "André", "Pamela", "Maria Cecília", "Lívia", "Loreena",
    "Duda", "Maria Fernanda", "Jéssica", "Manoela", "Luara", "Enzo",
    "Maria Gabriela", "Guilherme",
]

STATE_FILE = Path("state.json")
LOG_FILE = Path("log.csv")
SECRETARIA = "Secretaria"
DEFAULT_HOLDER = SECRETARIA

# ================
# Estado persistido
# ================
@dataclass
class State:
    current_holder: str = DEFAULT_HOLDER
    updated_at_iso: str = datetime.now(timezone.utc).isoformat()
    pinned_message_id: Optional[int] = None
    chat_id: Optional[int] = None

    @classmethod
    def load(cls) -> "State":
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                return cls(**data)
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        STATE_FILE.write_text(
            json.dumps(self.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

# ==============
# Utilitários
# ==============
def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def fmt_brazil(dt_iso: str) -> str:
    """Converte ISO UTC para horário de Brasília (24h)."""
    try:
        dt = datetime.fromisoformat(dt_iso)
        return dt.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return dt_iso

def ensure_log_header():
    exists = LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp_utc", "acao", "de", "para", "by_user_id", "chat_id"])

def log_event(action: str, de: str, para: str, by_user_id: int, chat_id: int):
    ensure_log_header()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([utcnow_iso(), action, de, para, by_user_id, chat_id])

def build_main_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Transferir", callback_data="transferir")
    kb.adjust(1)
    return kb.as_markup()

def build_transfer_keyboard(exclude: Optional[str] = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for nome in EMPREGADOS:
        if exclude and nome == exclude:
            continue
        kb.button(text=nome, callback_data=f"definir::{nome}")
    kb.adjust(3)
    kb.button(text="⬅️ Voltar", callback_data="voltar")
    kb.adjust(3)
    return kb.as_markup()

def status_text(state: State) -> str:
    """Mensagem fixada: alterna entre 'na Secretaria' e 'com NOME'."""
    atualizado = fmt_brazil(state.updated_at_iso)
    if state.current_holder == SECRETARIA:
        return (
            f"🔑 **Chave na Secretaria**\n"
            f"**Atualizado:** {atualizado}"
        )
    else:
        return (
            f"🔑 **Chave com:** {state.current_holder}\n"
            f"**Atualizado:** {atualizado}"
        )

# =====================
# Bot & helpers
# =====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Defina BOT_TOKEN nas variáveis de ambiente do Render (Environment).")

# aiogram 3.x: parse_mode vai via DefaultBotProperties
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
state = State.load()

async def safe_answer(cb: CallbackQuery, text: str = ""):
    """Responde callback imediatamente e ignora erro de expiração do Telegram."""
    try:
        await cb.answer(text)
    except TelegramBadRequest:
        pass
    except Exception:
        pass

# =====================
# Comandos
# =====================
@dp.message(Command("start"))
async def cmd_start(msg: Message, command: CommandObject):
    await msg.reply("Olá! Use /setup no grupo para criar/atualizar a mensagem fixa de status.")

@dp.message(Command("setup"))
async def cmd_setup(msg: Message):
    if msg.chat.type not in ("group", "supergroup"):
        await msg.reply("Use este comando dentro do grupo onde o status deve ficar fixado.")
        return

    text = status_text(state)
    kb = build_main_keyboard()

    try:
        if state.pinned_message_id and state.chat_id == msg.chat.id:
            await bot.edit_message_text(
                chat_id=state.chat_id,
                message_id=state.pinned_message_id,
                text=text,
                reply_markup=kb,
            )
        else:
            m = await msg.answer(text, reply_markup=kb)
            try:
                await bot.pin_chat_message(msg.chat.id, m.message_id, disable_notification=True)
            except Exception:
                pass
            state.pinned_message_id = m.message_id
            state.chat_id = msg.chat.id
            state.save()
    except Exception:
        m = await msg.answer(text, reply_markup=kb)
        try:
            await bot.pin_chat_message(msg.chat.id, m.message_id, disable_notification=True)
        except Exception:
            pass
        state.pinned_message_id = m.message_id
        state.chat_id = msg.chat.id
        state.save()

    await msg.reply("Status preparado e (tentei) fixado. Use os botões para transferir.")

@dp.message(Command("status"))
async def cmd_status(msg: Message):
    await msg.reply(status_text(state), reply_markup=build_main_keyboard())

@dp.message(Command("reset"))
async def cmd_reset(msg: Message):
    anterior = state.current_holder
    state.current_holder = SECRETARIA
    state.updated_at_iso = utcnow_iso()
    state.save()

    if state.chat_id and state.pinned_message_id:
        try:
            await bot.edit_message_text(
                chat_id=state.chat_id,
                message_id=state.pinned_message_id,
                text=status_text(state),
                reply_markup=build_main_keyboard(),
            )
        except Exception:
            pass

    log_event("reset", anterior, SECRETARIA, msg.from_user.id, msg.chat.id)
    await msg.reply("Status resetado para *Secretaria*.")

# =====================
# Callbacks (botões)
# =====================
@dp.callback_query(F.data == "transferir")
async def on_transferir(cb: CallbackQuery):
    await safe_answer(cb, "Escolha para quem transferir.")
    atual = state.current_holder
    kb = build_transfer_keyboard(exclude=atual if atual != SECRETARIA else None)
    try:
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass

@dp.callback_query(F.data == "voltar")
async def on_voltar(cb: CallbackQuery):
    await safe_answer(cb)
    try:
        await cb.message.edit_reply_markup(reply_markup=build_main_keyboard())
    except Exception:
        pass

@dp.callback_query(F.data.startswith("definir::"))
async def on_definir(cb: CallbackQuery):
    await safe_answer(cb, "Atualizando…")
    novo = cb.data.split("::", 1)[1]
    anterior = state.current_holder

    state.current_holder = novo
    state.updated_at_iso = utcnow_iso()
    state.save()

    if state.chat_id and state.pinned_message_id:
        try:
            await bot.edit_message_text(
                chat_id=state.chat_id,
                message_id=state.pinned_message_id,
                text=status_text(state),
                reply_markup=build_main_keyboard(),
            )
        except Exception:
            pass

    try:
        await cb.message.edit_text(status_text(state), reply_markup=build_main_keyboard())
    except Exception:
        pass

    log_event("transferir", anterior, novo, cb.from_user.id, cb.message.chat.id)

    try:
        resumo = status_text(state).splitlines()[0]
        if anterior != novo:
            await cb.message.answer(f"✅ Status atualizado: {resumo}")
        else:
            await cb.message.answer(f"ℹ️ Chave permanece: {resumo}")
    except Exception:
        pass

# =====================
# HTTP server (para Render Web Service)
# =====================
async def run_http_server():
    app = web.Application()

    async def root(_):
        return web.Response(text="Bot da Chave — OK")

    async def health(_):
        return web.Response(text="ok")

    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    port = int(os.environ.get("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    # mantém o server vivo
    await asyncio.Event().wait()

# ============
# Entrypoint
# ============
async def main():
    print("Bot da Chave rodando…")
    # roda bot + http em paralelo
    poll_task = asyncio.create_task(dp.start_polling(bot, allowed_updates=["message", "callback_query"]))
    http_task = asyncio.create_task(run_http_server())
    await asyncio.gather(poll_task, http_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Encerrando bot…")
