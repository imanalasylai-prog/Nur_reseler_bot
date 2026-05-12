import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

import db
import state as st
from i18n import t, get_lang, LANGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REQUISITES_KEY = "topup_requisites"

router = Router()


def parse_admin_ids() -> set[int]:
    raw = os.environ.get("ADMIN_TELEGRAM_IDS", "")
    ids = set()
    for part in raw.replace(",", " ").split():
        try:
            ids.add(int(part))
        except ValueError:
            pass
    return ids


ADMIN_IDS = parse_admin_ids()


def is_env_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS


async def is_admin_user(telegram_id: int) -> bool:
    if is_env_admin(telegram_id):
        return True
    user = await db.get_user(telegram_id)
    return bool(user and user.get("is_admin"))


async def is_authenticated(telegram_id: int) -> bool:
        return True
        return True
        return True
        return True
def main_menu_keyboard(lang: str, is_admin: bool) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text=t(lang, "menu_catalog")), KeyboardButton(text=t(lang, "menu_topup"))],
        [KeyboardButton(text=t(lang, "menu_balance")), KeyboardButton(text=t(lang, "menu_language"))],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text=t(lang, "menu_admin"))])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def inline_kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
            for row in rows
        ]
    )


def language_inline() -> InlineKeyboardMarkup:
    return inline_kb([[("🇷🇺 Русский", "lang:ru"), ("🇰🇿 Қазақша", "lang:kz"), ("🇬🇧 English", "lang:en")]])


def back_to_menu_inline(lang: str) -> InlineKeyboardMarkup:
    return inline_kb([[(t(lang, "to_menu"), "to_menu")]])


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    tg_id = message.from_user.id
    user = await db.ensure_user(tg_id, message.from_user.username, message.from_user.first_name, is_env_admin(tg_id))
    st.clear_flow(tg_id)
    lang = get_lang(user.get("language"))
    if not await is_authenticated(tg_id):
        await message.answer(t(lang, "login_required"))
        return
    await message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang, user.get("is_admin", False)))


# ─── /login ───────────────────────────────────────────────────────────────────

@router.message(Command("login"))
async def cmd_login(message: Message):
    tg_id = message.from_user.id
    user = await db.ensure_user(tg_id, message.from_user.username, message.from_user.first_name, is_env_admin(tg_id))
    lang = get_lang(user.get("language"))
    if is_env_admin(tg_id):
        await message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang, True))
        return
    claimed = await db.find_account_by_telegram_id(tg_id)
    if claimed:
        await message.answer(t(lang, "login_already", username=claimed["username"]))
        await message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang, user.get("is_admin", False)))
        return
    st.set_flow(tg_id, {"kind": "login"})
    await message.answer(t(lang, "login_prompt"))


# ─── Language callbacks ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(call: CallbackQuery):
    tg_id = call.from_user.id
    lang = call.data.split(":")[1]
    if lang not in LANGS:
        await call.answer()
        return
    await db.set_user_language(tg_id, lang)
    await call.answer(t(lang, "lang_set"))
    user = await db.get_user(tg_id)
    try:
        await call.message.delete()
    except Exception:
        pass
    if not await is_authenticated(tg_id):
        await call.message.answer(t(lang, "login_required"))
        return
    await call.message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang, user.get("is_admin", False)))


@router.callback_query(F.data == "to_menu")
async def cb_to_menu(call: CallbackQuery):
    tg_id = call.from_user.id
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    if not await is_authenticated(tg_id):
        await call.message.answer(t(lang, "login_required"))
        return
    await call.message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang, user.get("is_admin", False)))


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


# ─── Catalog ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "catalog")
async def cb_catalog(call: CallbackQuery):
    await call.answer()
    await show_catalog(call.message, call.from_user.id)


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery):
    await call.answer()
    cat_id = int(call.data.split(":")[1])
    await show_category(call.message, call.from_user.id, cat_id)


@router.callback_query(F.data.startswith("prod:"))
async def cb_product(call: CallbackQuery):
    await call.answer()
    prod_id = int(call.data.split(":")[1])
    await show_product(call.message, call.from_user.id, prod_id)


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery):
    await call.answer()
    prod_id = int(call.data.split(":")[1])
    await confirm_buy(call.message, call.from_user.id, prod_id)


@router.callback_query(F.data.startswith("buyok:"))
async def cb_buyok(call: CallbackQuery, bot: Bot):
    await call.answer()
    prod_id = int(call.data.split(":")[1])
    await do_buy(call.message, call.from_user.id, prod_id)


@router.callback_query(F.data == "buycancel")
async def cb_buycancel(call: CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


# ─── Admin panel callbacks ─────────────────────────────────────────────────────

@router.callback_query(F.data == "admin")
async def cb_admin(call: CallbackQuery):
    await call.answer()
    if not await is_admin_user(call.from_user.id):
        return
    await show_admin_panel(call.message, call.from_user.id)


@router.callback_query(F.data == "adm:cat_add")
async def cb_adm_cat_add(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_add_category"})
    await call.message.answer(t(lang, "admin_ask_category_name"))


@router.callback_query(F.data == "adm:cat_del")
async def cb_adm_cat_del(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    cats = await db.list_categories()
    if not cats:
        await call.message.answer(t(lang, "admin_no_categories"))
        return
    rows = [[(c["name"], f"adm:catdeldo:{c['id']}")] for c in cats]
    await call.message.answer(t(lang, "admin_choose_category_to_delete"), reply_markup=inline_kb(rows))


@router.callback_query(F.data.startswith("adm:catdeldo:"))
async def cb_adm_catdeldo(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    cat_id = int(call.data.split(":")[2])
    await db.delete_category(cat_id)
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    await call.message.answer(t(lang, "admin_category_deleted"))


@router.callback_query(F.data == "adm:prod_add")
async def cb_adm_prod_add(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    cats = await db.list_categories()
    if not cats:
        await call.message.answer(t(lang, "admin_no_categories"))
        return
    rows = [[(c["name"], f"adm:prodaddcat:{c['id']}")] for c in cats]
    await call.message.answer(t(lang, "admin_choose_category_for_product"), reply_markup=inline_kb(rows))


@router.callback_query(F.data.startswith("adm:prodaddcat:"))
async def cb_adm_prodaddcat(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    cat_id = int(call.data.split(":")[2])
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_add_product_name", "category_id": cat_id})
    await call.message.answer(t(lang, "admin_ask_product_name"))


@router.callback_query(F.data == "adm:prod_del")
async def cb_adm_prod_del(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    rows = await build_all_products_keyboard("adm:proddeldo")
    if not rows:
        await call.message.answer(t(lang, "admin_no_products"))
        return
    await call.message.answer(t(lang, "admin_choose_product_to_delete"), reply_markup=inline_kb(rows))


@router.callback_query(F.data.startswith("adm:proddeldo:"))
async def cb_adm_proddeldo(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    prod_id = int(call.data.split(":")[2])
    product = await db.get_product(prod_id)
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    if not product:
        return
    await call.message.answer(
        t(lang, "admin_confirm_delete_product", name=product["name"]),
        reply_markup=inline_kb([
            [(t(lang, "admin_confirm_yes"), f"adm:proddeldoyes:{prod_id}"), (t(lang, "admin_confirm_no"), "noop")]
        ])
    )


@router.callback_query(F.data.startswith("adm:proddeldoyes:"))
async def cb_adm_proddeldoyes(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    prod_id = int(call.data.split(":")[2])
    await db.delete_product(prod_id)
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    await call.message.answer(t(lang, "admin_product_deleted"))


@router.callback_query(F.data == "adm:keys")
async def cb_adm_keys(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    rows = await build_all_products_keyboard("adm:keysprod")
    if not rows:
        await call.message.answer(t(lang, "admin_no_products"))
        return
    await call.message.answer(t(lang, "admin_choose_product_for_keys"), reply_markup=inline_kb(rows))


@router.callback_query(F.data.startswith("adm:keysprod:"))
async def cb_adm_keysprod(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    prod_id = int(call.data.split(":")[2])
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_add_keys", "product_id": prod_id})
    await call.message.answer(t(lang, "admin_ask_keys"))


@router.callback_query(F.data == "adm:price")
async def cb_adm_price(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    rows = await build_all_products_keyboard("adm:priceprod")
    if not rows:
        await call.message.answer(t(lang, "admin_no_products"))
        return
    await call.message.answer(t(lang, "admin_choose_product_for_price"), reply_markup=inline_kb(rows))


@router.callback_query(F.data.startswith("adm:priceprod:"))
async def cb_adm_priceprod(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    prod_id = int(call.data.split(":")[2])
    product = await db.get_product(prod_id)
    if not product:
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_edit_price", "product_id": prod_id})
    await call.message.answer(t(lang, "admin_ask_new_price", name=product["name"], price=product["price_tenge"]))


@router.callback_query(F.data == "adm:bal")
async def cb_adm_bal(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_balance_user_id"})
    await call.message.answer(t(lang, "admin_ask_user_id"))


@router.callback_query(F.data == "adm:req")
async def cb_adm_req(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_set_requisites"})
    await call.message.answer(t(lang, "admin_set_requisites_intro"))


@router.callback_query(F.data == "adm:topups")
async def cb_adm_topups(call: CallbackQuery):
    await call.answer()
    if not await is_admin_user(call.from_user.id):
        return
    await show_pending_topups(call.message, call.from_user.id)


@router.callback_query(F.data.startswith("adm:topok:"))
async def cb_adm_topok(call: CallbackQuery, bot: Bot):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    req_id = int(call.data.split(":")[2])
    await approve_topup(call.message, bot, tg_id, req_id)


@router.callback_query(F.data.startswith("adm:topno:"))
async def cb_adm_topno(call: CallbackQuery, bot: Bot):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    req_id = int(call.data.split(":")[2])
    await reject_topup(call.message, bot, tg_id, req_id)


@router.callback_query(F.data == "adm:stats")
async def cb_adm_stats(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    s = await db.get_stats()
    await call.message.answer(t(lang, "admin_stats_text", **s))


@router.callback_query(F.data == "adm:newuser")
async def cb_adm_newuser(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_create_account", "role": "user"})
    await call.message.answer(t(lang, "admin_create_account_intro"))


@router.callback_query(F.data == "adm:newadmin")
async def cb_adm_newadmin(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_create_account", "role": "admin"})
    await call.message.answer(t(lang, "admin_create_account_intro"))


@router.callback_query(F.data == "adm:listacc")
async def cb_adm_listacc(call: CallbackQuery):
    await call.answer()
    if not await is_admin_user(call.from_user.id):
        return
    await show_accounts_list(call.message, call.from_user.id)


@router.callback_query(F.data == "adm:delacc")
async def cb_adm_delacc(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    accs = await db.list_accounts()
    if not accs:
        await call.message.answer(t(lang, "admin_accounts_empty"))
        return
    rows = [[(f"🗑 #{a['id']} {a['username']} ({a['role']})", f"adm:delaccdo:{a['id']}")] for a in accs]
    await call.message.answer(t(lang, "admin_account_choose_delete"), reply_markup=inline_kb(rows))


@router.callback_query(F.data.startswith("adm:delaccdo:"))
async def cb_adm_delaccdo(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    acc_id = int(call.data.split(":")[2])
    await db.delete_account(acc_id)
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    await call.message.answer(t(lang, "admin_account_deleted"))


@router.callback_query(F.data == "adm:broadcast")
async def cb_adm_broadcast(call: CallbackQuery):
    await call.answer()
    tg_id = call.from_user.id
    if not await is_admin_user(tg_id):
        return
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    st.set_flow(tg_id, {"kind": "admin_broadcast"})
    await call.message.answer(t(lang, "admin_broadcast_intro"))


# ─── Photo handler ─────────────────────────────────────────────────────────────

@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
    tg_id = message.from_user.id
    flow = st.get_flow(tg_id)
    if flow.get("kind") != "topup_proof":
        return
    if not await is_authenticated(tg_id):
        return
    photo = message.photo[-1]
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    req = await db.create_topup_request(tg_id, flow["amount"], proof_file_id=photo.file_id)
    st.clear_flow(tg_id)
    await message.answer(t(lang, "topup_submitted", id=req["id"], amount=flow["amount"]))
    await notify_admins_of_topup(bot, req["id"])


# ─── Text router ───────────────────────────────────────────────────────────────

@router.message(F.text)
async def handle_text(message: Message, bot: Bot):
    tg_id = message.from_user.id
    text = message.text
    user = await db.ensure_user(tg_id, message.from_user.username, message.from_user.first_name, is_env_admin(tg_id))
    lang = get_lang(user.get("language"))
    flow = st.get_flow(tg_id)

    if flow.get("kind") == "login":
        await handle_login_flow(message, text, lang)
        return

    if not await is_authenticated(tg_id):
        await message.answer(t(lang, "login_required"))
        return

    if flow.get("kind") != "idle":
        if await handle_flow_text(message, bot, flow, text, lang, tg_id):
            return

    if matches_any_lang(text, "menu_catalog"):
        await show_catalog(message, tg_id)
    elif matches_any_lang(text, "menu_topup"):
        await start_topup(message, tg_id)
    elif matches_any_lang(text, "menu_balance"):
        await message.answer(t(lang, "balance_text", amount=user.get("balance_tenge", 0)))
    elif matches_any_lang(text, "menu_language"):
        await message.answer(t(lang, "choose_lang"), reply_markup=language_inline())
    elif matches_any_lang(text, "menu_admin"):
        if not await is_admin_user(tg_id):
            await message.answer(t(lang, "admin_only"))
        else:
            await show_admin_panel(message, tg_id)
    else:
        await message.answer(t(lang, "unknown"))


# ─── Flow handlers ─────────────────────────────────────────────────────────────

async def handle_login_flow(message: Message, text: str, lang: str):
    tg_id = message.from_user.id
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        await message.answer(t(lang, "login_invalid_format"))
        return
    username, password = lines[0], lines[1]
    result = await db.login_and_claim(tg_id, username, password)
    if not result["ok"]:
        reason = result["reason"]
        if reason == "not_found":
            await message.answer(t(lang, "login_not_found"))
        elif reason == "wrong_password":
            await message.answer(t(lang, "login_wrong_password"))
        elif reason == "claimed_by_other":
            await message.answer(t(lang, "login_claimed_by_other"))
        return
    st.clear_flow(tg_id)
    user = await db.get_user(tg_id)
    await message.answer(t(lang, "login_success", username=result["account"]["username"]))
    await message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang, user.get("is_admin", False)))


async def handle_flow_text(message: Message, bot: Bot, flow: dict, text: str, lang: str, tg_id: int) -> bool:
    kind = flow.get("kind")

    if kind == "topup_amount":
        try:
            amount = int(float(text))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await message.answer(t(lang, "topup_invalid_amount"))
            return True
        requisites = await db.get_setting(REQUISITES_KEY)
        if not requisites:
            await message.answer(t(lang, "topup_no_requisites"))
            st.clear_flow(tg_id)
            return True
        st.set_flow(tg_id, {"kind": "topup_proof", "amount": amount})
        await message.answer(t(lang, "topup_ask_proof", requisites=requisites))
        return True

    elif kind == "topup_proof":
        req = await db.create_topup_request(tg_id, flow["amount"], note=text)
        st.clear_flow(tg_id)
        await message.answer(t(lang, "topup_submitted", id=req["id"], amount=flow["amount"]))
        await notify_admins_of_topup(bot, req["id"])
        return True

    elif kind == "admin_add_category":
        name = text.strip()
        if not name:
            return True
        cat = await db.create_category(name)
        st.clear_flow(tg_id)
        await message.answer(t(lang, "admin_category_added", name=cat["name"]))
        return True

    elif kind == "admin_add_product_name":
        name = text.strip()
        if not name:
            return True
        st.set_flow(tg_id, {"kind": "admin_add_product_desc", "category_id": flow["category_id"], "name": name})
        await message.answer(t(lang, "admin_ask_product_desc"))
        return True

    elif kind == "admin_add_product_desc":
        desc = "" if text.strip() == "-" else text.strip()
        st.set_flow(tg_id, {
            "kind": "admin_add_product_price",
            "category_id": flow["category_id"],
            "name": flow["name"],
            "description": desc
        })
        await message.answer(t(lang, "admin_ask_product_price"))
        return True

    elif kind == "admin_add_product_price":
        try:
            price = int(float(text))
            if price < 0:
                raise ValueError
        except ValueError:
            await message.answer(t(lang, "topup_invalid_amount"))
            return True
        product = await db.create_product(flow["category_id"], flow["name"], flow["description"], price)
        st.clear_flow(tg_id)
        await message.answer(t(lang, "admin_product_added", name=product["name"]))
        return True

    elif kind == "admin_add_keys":
        keys = [l.strip() for l in text.splitlines() if l.strip()]
        result = await db.add_keys(flow["product_id"], keys)
        st.clear_flow(tg_id)
        await message.answer(t(lang, "admin_keys_added", added=result["added"], dup=result["dup"]))
        return True

    elif kind == "admin_edit_price":
        try:
            price = int(float(text))
            if price < 0:
                raise ValueError
        except ValueError:
            await message.answer(t(lang, "topup_invalid_amount"))
            return True
        await db.set_product_price(flow["product_id"], price)
        p = await db.get_product(flow["product_id"])
        st.clear_flow(tg_id)
        await message.answer(t(lang, "admin_price_updated", name=p["name"] if p else "", price=price))
        return True

    elif kind == "admin_balance_user_id":
        try:
            target_id = int(text.strip())
        except ValueError:
            await message.answer(t(lang, "admin_user_not_found"))
            return True
        target = await db.get_user(target_id)
        if not target:
            await message.answer(t(lang, "admin_user_not_found"))
            st.clear_flow(tg_id)
            return True
        st.set_flow(tg_id, {"kind": "admin_balance_delta", "target_telegram_id": target_id})
        await message.answer(t(lang, "admin_ask_balance_delta"))
        return True

    elif kind == "admin_balance_delta":
        try:
            delta = int(float(text))
        except ValueError:
            await message.answer(t(lang, "topup_invalid_amount"))
            return True
        try:
            new_bal = await db.adjust_balance(flow["target_telegram_id"], delta, "admin_adjust", meta=f"by={tg_id}")
            st.clear_flow(tg_id)
            await message.answer(t(lang, "admin_balance_changed", id=flow["target_telegram_id"], delta=delta, balance=new_bal))
        except Exception:
            await message.answer(t(lang, "admin_user_not_found"))
            st.clear_flow(tg_id)
        return True

    elif kind == "admin_set_requisites":
        await db.set_setting(REQUISITES_KEY, text)
        st.clear_flow(tg_id)
        await message.answer(t(lang, "admin_requisites_saved"))
        return True

    elif kind == "admin_create_account":
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            await message.answer(t(lang, "admin_create_account_invalid"))
            return True
        username, password = lines[0], lines[1]
        result = await db.create_account(username, password, flow["role"])
        st.clear_flow(tg_id)
        if not result["ok"]:
            await message.answer(t(lang, "admin_account_duplicate"))
        else:
            await message.answer(
                t(lang, "admin_account_created", username=username, password=password, role=flow["role"]),
                parse_mode=ParseMode.HTML
            )
        return True

    elif kind == "admin_broadcast":
        st.clear_flow(tg_id)
        ids = await db.list_all_user_telegram_ids()
        ok_count = 0
        fail_count = 0
        for uid in ids:
            try:
                await bot.send_message(uid, text)
                ok_count += 1
            except Exception:
                fail_count += 1
        await message.answer(t(lang, "admin_broadcast_done", ok=ok_count, fail=fail_count))
        return True

    return False


# ─── Helper functions ──────────────────────────────────────────────────────────

def matches_any_lang(text: str, key: str) -> bool:
    for lang in LANGS:
        if text == t(lang, key):
            return True
    return False


async def build_all_products_keyboard(prefix: str) -> list[list[tuple[str, str]]]:
    cats = await db.list_categories()
    rows = []
    for cat in cats:
        prods = await db.list_products_by_category(cat["id"])
        for p in prods:
            label = f"{cat['name']} / {p['name']} — {p['price_tenge']} ₸"
            rows.append([(label, f"{prefix}:{p['id']}")])
    return rows


async def show_catalog(message: Message, tg_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    if not await is_authenticated(tg_id):
        await message.answer(t(lang, "login_required"))
        return
    cats = await db.list_categories()
    if not cats:
        await message.answer(t(lang, "catalog_empty"))
        return
    rows = [[(f"📂 {c['name']}", f"cat:{c['id']}")] for c in cats]
    rows.append([(t(lang, "to_menu"), "to_menu")])
    await message.answer(t(lang, "catalog_title"), reply_markup=inline_kb(rows))


async def show_category(message: Message, tg_id: int, category_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    if not await is_authenticated(tg_id):
        await message.answer(t(lang, "login_required"))
        return
    cat = await db.get_category(category_id)
    if not cat:
        await message.answer(t(lang, "catalog_empty"))
        return
    products = await db.list_products_by_category(category_id)
    if not products:
        await message.answer(t(lang, "category_empty"), reply_markup=back_to_menu_inline(lang))
        return
    rows = [[(f"📦 {p['name']} — {p['price_tenge']} ₸", f"prod:{p['id']}")] for p in products]
    rows.append([(t(lang, "back"), "catalog")])
    await message.answer(t(lang, "category_title", name=cat["name"]), reply_markup=inline_kb(rows))


async def show_product(message: Message, tg_id: int, product_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    if not await is_authenticated(tg_id):
        await message.answer(t(lang, "login_required"))
        return
    product = await db.get_product(product_id)
    if not product:
        return
    stock = await db.get_stock_count(product_id)
    if stock > 0:
        btn_row = [(t(lang, "product_buy", price=product["price_tenge"]), f"buy:{product_id}")]
    else:
        btn_row = [(t(lang, "product_out_of_stock"), "noop")]
    rows = [btn_row, [(t(lang, "back"), f"cat:{product['category_id']}")]]
    await message.answer(
        t(lang, "product_card", name=product["name"], description=product["description"] or "—", price=product["price_tenge"]),
        reply_markup=inline_kb(rows)
    )


async def confirm_buy(message: Message, tg_id: int, product_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    if not await is_authenticated(tg_id):
        await message.answer(t(lang, "login_required"))
        return
    product = await db.get_product(product_id)
    if not product:
        return
    await message.answer(
        t(lang, "buy_confirm", name=product["name"], price=product["price_tenge"]),
        reply_markup=inline_kb([
            [(t(lang, "buy_yes"), f"buyok:{product_id}"), (t(lang, "buy_no"), "buycancel")]
        ])
    )


async def do_buy(message: Message, tg_id: int, product_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    if not await is_authenticated(tg_id):
        await message.answer(t(lang, "login_required"))
        return
    result = await db.purchase_product(tg_id, product_id)
    if not result["ok"]:
        reason = result["reason"]
        if reason == "not_enough":
            await message.answer(t(lang, "buy_not_enough"))
        elif reason == "no_stock":
            await message.answer(t(lang, "buy_no_stock"))
        else:
            await message.answer(t(lang, "unknown"))
        return
    await message.answer(
        t(lang, "buy_success", name=result["product"]["name"], key=result["key"], balance=result["balance"]),
        parse_mode=ParseMode.HTML
    )


async def start_topup(message: Message, tg_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    if not await is_authenticated(tg_id):
        await message.answer(t(lang, "login_required"))
        return
    requisites = await db.get_setting(REQUISITES_KEY)
    if not requisites:
        await message.answer(t(lang, "topup_no_requisites"))
        return
    st.set_flow(tg_id, {"kind": "topup_amount"})
    await message.answer(t(lang, "topup_ask_amount"))


async def show_admin_panel(message: Message, tg_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    await message.answer(
        t(lang, "admin_title"),
        reply_markup=inline_kb([
            [(t(lang, "admin_add_category"), "adm:cat_add")],
            [(t(lang, "admin_delete_category"), "adm:cat_del")],
            [(t(lang, "admin_add_product"), "adm:prod_add")],
            [(t(lang, "admin_delete_product"), "adm:prod_del")],
            [(t(lang, "admin_add_keys"), "adm:keys")],
            [(t(lang, "admin_edit_price"), "adm:price")],
            [(t(lang, "admin_change_balance"), "adm:bal")],
            [(t(lang, "admin_set_requisites"), "adm:req")],
            [(t(lang, "admin_create_user_login"), "adm:newuser")],
            [(t(lang, "admin_create_admin_login"), "adm:newadmin")],
            [(t(lang, "admin_list_accounts"), "adm:listacc")],
            [(t(lang, "admin_delete_account"), "adm:delacc")],
            [(t(lang, "admin_broadcast"), "adm:broadcast")],
            [(t(lang, "admin_menu_topups"), "adm:topups")],
            [(t(lang, "admin_menu_stats"), "adm:stats")],
            [(t(lang, "to_menu"), "to_menu")],
        ])
    )


async def show_accounts_list(message: Message, tg_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    accs = await db.list_accounts()
    if not accs:
        await message.answer(t(lang, "admin_accounts_empty"))
        return
    lines = [t(lang, "admin_accounts_header")]
    for a in accs:
        if a.get("claimed_by_telegram_id"):
            lines.append(t(lang, "admin_account_row_claimed",
                id=a["id"], role=a["role"], username=a["username"],
                password=a["password"], tg=a["claimed_by_telegram_id"]))
        else:
            lines.append(t(lang, "admin_account_row_free",
                id=a["id"], role=a["role"], username=a["username"], password=a["password"]))
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def show_pending_topups(message: Message, tg_id: int):
    user = await db.get_user(tg_id)
    lang = get_lang(user.get("language") if user else None)
    pending = await db.list_pending_topups()
    if not pending:
        await message.answer(t(lang, "admin_topups_empty"))
        return
    for req in pending:
        target = await db.get_user(req["telegram_id"])
        user_label = f"@{target['username']}" if target and target.get("username") else str(req["telegram_id"])
        caption = t(lang, "admin_topup_card",
            id=req["id"], user=user_label,
            amount=req["amount_tenge"],
            date=str(req["created_at"])[:10])
        btns = inline_kb([[
            (t(lang, "admin_topup_approve"), f"adm:topok:{req['id']}"),
            (t(lang, "admin_topup_reject"), f"adm:topno:{req['id']}")
        ]])
        if req.get("proof_file_id"):
            try:
                await message.answer_photo(req["proof_file_id"], caption=caption, reply_markup=btns)
                continue
            except Exception:
                pass
        note = f"\n📝 {req['note']}" if req.get("note") else ""
        await message.answer(caption + note, reply_markup=btns)


async def approve_topup(message: Message, bot: Bot, admin_id: int, req_id: int):
    admin = await db.get_user(admin_id)
    admin_lang = get_lang(admin.get("language") if admin else None)
    req = await db.get_topup(req_id)
    if not req or req["status"] != "pending":
        await message.answer(t(admin_lang, "admin_topups_empty"))
        return
    await db.adjust_balance(req["telegram_id"], req["amount_tenge"], "topup_approved", meta=f"req={req_id};by={admin_id}")
    await db.mark_topup(req_id, "approved", admin_id)
    await message.answer(t(admin_lang, "admin_topup_user_notified"))
    target = await db.get_user(req["telegram_id"])
    target_lang = get_lang(target.get("language") if target else None)
    try:
        await bot.send_message(req["telegram_id"], t(target_lang, "topup_approved", id=req_id, amount=req["amount_tenge"]))
    except Exception:
        pass


async def reject_topup(message: Message, bot: Bot, admin_id: int, req_id: int):
    admin = await db.get_user(admin_id)
    admin_lang = get_lang(admin.get("language") if admin else None)
    req = await db.get_topup(req_id)
    if not req or req["status"] != "pending":
        await message.answer(t(admin_lang, "admin_topups_empty"))
        return
    await db.mark_topup(req_id, "rejected", admin_id)
    await message.answer(t(admin_lang, "admin_topup_user_notified"))
    target = await db.get_user(req["telegram_id"])
    target_lang = get_lang(target.get("language") if target else None)
    try:
        await bot.send_message(req["telegram_id"], t(target_lang, "topup_rejected", id=req_id, amount=req["amount_tenge"]))
    except Exception:
        pass


async def notify_admins_of_topup(bot: Bot, request_id: int):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🆕 Жаңа толықтыру өтінімі #{request_id}. Админ панель → 📥")
        except Exception:
            pass


# ─── Main entry ───────────────────────────────────────────────────────────────

async def on_startup_webhook(bot: Bot):
    webhook_url = os.environ["WEBHOOK_URL"]
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook set: {webhook_url}")


async def on_shutdown_webhook(bot: Bot):
    await bot.delete_webhook()
    await db.close_pool()


async def on_shutdown_polling(bot: Bot):
    await db.close_pool()


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    webhook_url = os.environ.get("WEBHOOK_URL", "")

    bot = Bot(token=token, default=None)
    dp = Dispatcher()
    dp.include_router(router)

    if webhook_url:
        webhook_path = os.environ.get("WEBHOOK_PATH", "/webhook")
        port = int(os.environ.get("PORT", 8080))
        dp.startup.register(on_startup_webhook)
        dp.shutdown.register(on_shutdown_webhook)
        app = web.Application()
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        handler.register(app, path=webhook_path)
        setup_application(app, dp, bot=bot)
        logger.info(f"Starting in WEBHOOK mode on port {port}")
        web.run_app(app, host="0.0.0.0", port=port)
    else:
        dp.shutdown.register(on_shutdown_polling)
        logger.info("Starting in POLLING mode")
        asyncio.run(dp.start_polling(bot, drop_pending_updates=True))


if __name__ == "__main__":
    main()
