"""Telegram UI: /menu to list, add and delete targets. Owner-only."""
import logging

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import ValidationError

import storage
from config import Target, settings

log = logging.getLogger(__name__)
router = Router()

# Access control. Every handler below hangs off this router, so anyone who is not
# the owner is dropped here and never reaches a handler -- silently, no reply.
router.message.filter(F.from_user.id == settings.telegram_owner_id)
router.callback_query.filter(F.from_user.id == settings.telegram_owner_id)

NAME_MAX = 32  # callback_data is capped at 64 bytes and carries "del:<name>"


class AddTarget(StatesGroup):
    name = State()
    url = State()
    kind = State()
    path = State()
    attribute = State()


MENU = InlineKeyboardMarkup(
    inline_keyboard=[[
        InlineKeyboardButton(text="📋 Listar", callback_data="list"),
        InlineKeyboardButton(text="➕ Agregar", callback_data="add"),
        InlineKeyboardButton(text="❌ Eliminar", callback_data="del"),
    ]]
)
KIND = InlineKeyboardMarkup(
    inline_keyboard=[[
        InlineKeyboardButton(text="JSON", callback_data="kind:json"),
        InlineKeyboardButton(text="HTML", callback_data="kind:html"),
    ]]
)


def _rule(t: Target) -> str:
    if t.json_path:
        return f"json_path: {t.json_path}"
    attr = f" [{t.css_attribute}]" if t.css_attribute else " (texto visible)"
    return f"css: {t.css_selector}{attr}"


# --- /menu and /cancelar come first: they must win over the FSM state handlers ---


@router.message(Command("menu", "start"))
async def menu(message: Message) -> None:
    await message.answer("Deal Hunter", reply_markup=MENU)


@router.message(Command("cancelar"))
async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Nada que cancelar.")
        return
    await state.clear()
    await message.answer("Cancelado.", reply_markup=MENU)


@router.callback_query(F.data == "list")
async def list_targets(cb: CallbackQuery) -> None:
    targets = await storage.get_all_targets()
    body = "\n\n".join(f"• {t.name}\n  {t.url}\n  {_rule(t)}" for t in targets)
    await cb.message.answer(body or "Sin targets. Usá ➕ Agregar.")
    await cb.answer()


# --- add: name -> url -> kind -> path -> attribute ---


@router.callback_query(F.data == "add")
async def add_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddTarget.name)
    await cb.message.answer("Nombre del target? (/cancelar para abortar)")
    await cb.answer()


@router.message(AddTarget.name)
async def add_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 0 < len(name) <= NAME_MAX:
        await message.answer(f"Nombre entre 1 y {NAME_MAX} caracteres.")
        return
    await state.update_data(name=name)
    await state.set_state(AddTarget.url)
    await message.answer("URL?")


@router.message(AddTarget.url)
async def add_url(message: Message, state: FSMContext) -> None:
    await state.update_data(url=(message.text or "").strip())
    await state.set_state(AddTarget.kind)
    await message.answer("Tipo de extracción?", reply_markup=KIND)


@router.callback_query(AddTarget.kind, F.data.startswith("kind:"))
async def add_kind(cb: CallbackQuery, state: FSMContext) -> None:
    kind = cb.data.removeprefix("kind:")
    await state.update_data(kind=kind)
    await state.set_state(AddTarget.path)
    await cb.message.answer(
        "Ruta JSON? (ej: data.price)" if kind == "json" else "Selector CSS? (ej: span.price)"
    )
    await cb.answer()


@router.message(AddTarget.path)
async def add_path(message: Message, state: FSMContext) -> None:
    data = await state.update_data(path=(message.text or "").strip())
    if data["kind"] == "json":
        await _save(message, state)
        return
    await state.set_state(AddTarget.attribute)
    await message.answer("Atributo? (ej: data-value) o `-` para usar el texto visible")


@router.message(AddTarget.attribute)
async def add_attribute(message: Message, state: FSMContext) -> None:
    await state.update_data(attribute=(message.text or "").strip())
    await _save(message, state)


async def _save(message: Message, state: FSMContext) -> None:
    d = await state.get_data()
    await state.clear()
    attr = d.get("attribute", "-")
    try:
        # The Pydantic model is the gate: mutual exclusion is enforced here, not by the UI.
        target = Target(
            name=d["name"],
            url=d["url"],
            json_path=d["path"] if d["kind"] == "json" else None,
            css_selector=d["path"] if d["kind"] == "html" else None,
            css_attribute=None if attr in ("-", "") else attr,
        )
    except ValidationError as e:
        await message.answer(f"Target inválido: {e.errors()[0]['msg']}", reply_markup=MENU)
        return
    await storage.add_target(target)
    log.info("target guardado: %s", target.name)
    await message.answer(f"✅ Guardado: {target.name}\n{_rule(target)}", reply_markup=MENU)


# --- delete ---


@router.callback_query(F.data == "del")
async def del_start(cb: CallbackQuery) -> None:
    targets = await storage.get_all_targets()
    if not targets:
        await cb.message.answer("Sin targets.")
    else:
        await cb.message.answer(
            "Cuál elimino?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"❌ {t.name}", callback_data=f"del:{t.name}")]
                    for t in targets
                ]
            ),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("del:"))
async def del_do(cb: CallbackQuery) -> None:
    name = cb.data.removeprefix("del:")
    gone = await storage.delete_target(name)
    log.info("target eliminado: %s (%s)", name, gone)
    await cb.message.answer(f"🗑 Eliminado: {name}" if gone else f"No existe: {name}")
    await cb.answer()


dp = Dispatcher()
dp.include_router(router)
