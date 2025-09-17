"""
Bot da Chave — Telegram (transferência direta + Secretaria)
------------------------------------------------
Stack: Python 3.10+ • aiogram v3 • dotenv
Persistência: arquivo JSON (./state.json) + CSV de log (./log.csv)

Como usar (passo a passo rápido)
1) pip install -r requirements.txt
   # Conteúdo do requirements.txt:
   # aiogram==3.13.1
   # python-dotenv==1.0.1

2) Crie um arquivo .env na mesma pasta com:
   BOT_TOKEN=123456:seu_token_do_BotFather

3) Rode:  python bot.py

4) No Telegram:
   - Adicione o bot ao grupo e dê permissões de administrador (pelo menos: fixar mensagens, editar mensagens, apagar mensagens).
   - No grupo, rode /setup para criar a mensagem fixa de status.
   - Use os botões para "Transferir" diretamente.

Observações
- O estado atual (quem está com a chave) é salvo em state.json para sobreviver a reinícios.
- O log em CSV (log.csv) registra: timestamp, ação, de, para, user_id, group_id.
- Comando /status mostra o status atual; /reset coloca a chave "Na Secretaria".
- Se quiser mudar a lista de pessoas, edite a constante EMPREGADOS abaixo.
"""

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
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# ==========================
# Configuração e constantes
# ==========================

# >>> Edite aqui a lista de pessoas autorizadas <<<
EMPREGADOS: List[str] = [
    "Secretaria",
    "Lucas", "André", "Pâmela", "Maria Cecília", "Lívia", "Loreena",
    "Duda", "Maria Fernanda", "Jéssica", "Manoela", "Luara", "Enzo",
    "Maria Gabriela", "Guilherme"
]

STATE_FILE = Path("state.json")
LOG_FILE = Path("log.csv")
STATUS_PREFIX = "🔑 Status da Chave"
SECRETARIA = "Secretaria"
# Mensagem padrão quando ainda não há registro
DEFAULT_HOLDER = SECRETARIA

# ================
# Modelos simples
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
        STATE_FILE.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


# ==============
# Utilitários
# ==============

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fmt_brazil(dt_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_iso)
        # Converte para Horário de Brasília (America/Sao_Paulo) em 24h
        return dt.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return dt_iso


def ensure_log_header():
    exists = LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp_utc", "acao", "de", "para", "by_user_id", "chat_id"])  # header


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
    atualizado = fmt_brazil(state.updated_at_iso)
    na_secretaria = state.current_holder == SECRETARIA
    if na_secretaria:
        return f"🔑 **Chave na Secretaria**\n**Atualizado:** {atualizado}"
"
                f"**Atualizado:** {atualizado}")
    else:
        return (f"🔑 **Chave com:** {state.current_holder}
"
                f"**Atualizado:** {atualizado}")

"
            f"{banner}

"
            f"**Chave com:** {state.current_holder}
"
            f"**Atualizado:** {atualizado}
"
            f"**Local:** {local}
")


# =====================
# Inicialização do Bot
# =====================

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Defina BOT_TOKEN no .env")

bot = Bot(BOT_TOKEN, parse_mode="Markdown")
dp = Dispatcher()
state = State.load()


# =====================
# Handlers de comandos
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
                text=text,
                chat_id=state.chat_id,
                message_id=state.pinned_message_id,
                reply_markup=kb
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
                reply_markup=build_main_keyboard()
            )
        except Exception:
            pass

    log_event("reset", anterior, SECRETARIA, msg.from_user.id, msg.chat.id)
    await msg.reply("Status resetado para *Secretaria*.")


# =====================
# Handlers de callbacks
# =====================

@dp.callback_query(F.data == "transferir")
async def on_transferir(cb: CallbackQuery):
    atual = state.current_holder
    kb = build_transfer_keyboard(exclude=atual if atual != SECRETARIA else None)
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer("Escolha para quem transferir.")


@dp.callback_query(F.data == "voltar")
async def on_voltar(cb: CallbackQuery):
    await cb.message.edit_reply_markup(reply_markup=build_main_keyboard())
    await cb.answer()


@dp.callback_query(F.data.startswith("definir::"))
async def on_definir(cb: CallbackQuery):
    novo = cb.data.split("::", 1)[1]
    anterior = state.current_holder

    state.current_holder = novo
    state.updated_at_iso = utcnow_iso()
    state.save()

    # Atualiza a MENSAGEM FIXA com o alerta persistente
    if state.chat_id and state.pinned_message_id:
        try:
            await bot.edit_message_text(
                chat_id=state.chat_id,
                message_id=state.pinned_message_id,
                text=status_text(state),
                reply_markup=build_main_keyboard()
            )
        except Exception:
            pass

    # Atualiza a mensagem corrente (só para refletir o novo texto também)
    try:
        await cb.message.edit_text(status_text(state), reply_markup=build_main_keyboard())
    except Exception:
        pass

    # Log
    log_event("transferir", anterior, novo, cb.from_user.id, cb.message.chat.id)

    # Confirmação simples
    try:
        if anterior != novo:
            await cb.message.answer(f"✅ Status atualizado: {status_text(state).splitlines()[0]}")
        else:
            await cb.message.answer(f"ℹ️ Chave permanece: {status_text(state).splitlines()[0]}")
    except Exception:
        pass

    await cb.answer("Status atualizado.")


async def main():
    print("Bot da Chave rodando…")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Encerrando bot…")
