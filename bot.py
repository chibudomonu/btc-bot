# bot.py - Combined, persistent Telegram shop bot
import json
import os
import time
import hashlib
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ====================== CONFIG ======================
TELEGRAM_TOKEN = "8775358499:AAGgmIyh3qiX2VIHhtb5JkJjtFiXvh51T4A"
ADMIN_ID = 1942502806  # set your admin telegram id here
MIN_GBP = 0

DB_FILE = "database.json"

# ====================== WALLETS / PRODUCTS ======================
WALLETS = {
    "BTC": "bc1qegrl4yhpaym0nmkesmy3ncc4a727dupaklz4j0",
    "ETH": "0xfA66D24f9dA4c1fe4b3A3c6625EBBA788f6f41Ea",
    "LTC": "LZH7L6tCgNmCEwzbnPsLqrVRtWuKUG1ekd",
    "XRP": "ra1sP3JvJ4ZLxkr8dej96LSx1QXwXQwzCc",
    "USDT": "0xfA66D24f9dA4c1fe4b3A3c6625EBBA788f6f41Ea",
    "MATIC": "0xfA66D24f9dA4c1fe4b3A3c6625EBBA788f6f41Ea",
}

# You allowed changing products/categories — choose any sensible ones.
CATEGORIES = ["Barclays", "Lloyds", "Hsbc", "Santander", "Halifax", "Nationwide", "Bank of scotland", "Amex"]

PRODUCTS = {
    "handheld": {"name": "465923 - Platinum credit", "£": 25, "cat": "Barclays", "stock": 15},
    "stungun": {"name": "492915 - Platinum credit", "£": 25, "cat": "Barclays", "stock": 7},
    "szombie": {"name": "465861 - Business debit", "£": 25, "cat": "Barclays", "stock": 9},
    "ozombie": {"name": "465860 - Business debit", "£": 25, "cat": "Barclays", "stock": 6},
    "rambo": {"name": "465922 - Platinum debit", "£": 15, "cat": "Barclays", "stock": 2},
    "bstilleto": {"name": "459630 - Business debit", "£": 10, "cat": "Barclays", "stock": 1},
    "nstilleto": {"name": "465865 - Classic debit", "£": 10, "cat": "Barclays", "stock": 1},
    "tosnopro": {"name": "492918-SE7 6QB-£25", "£": 25, "cat": "🧑🏻‍💻Spammed", "stock": 50},
    "toswiithpro": {"name": "492918-SE7 6QB-£25", "£": 25, "cat": "🧑🏻‍💻Spammed", "stock": 50},
    "wockhardt": {"name": "492918-SE7 6QB-£25", "£": 25, "cat": "🧑🏻‍💻Spammed", "stock": 50},
    "tris": {"name": "492918-SE7 6QB-£25", "£": 25, "cat": "🧑🏻‍💻Spammed", "stock": 50},
}

# PGP key placeholder — paste your key here later (triple single-quotes to avoid nested triple-quote issues)
PGP_KEY = '''-----BEGIN PGP PUBLIC KEY-----
(add your key here)
-----END PGP PUBLIC KEY-----'''

# ================ IN-MEMORY USER DB / ORDERS ================
user_data: Dict[int, Dict[str, Any]] = {}
pending_orders: Dict[str, Dict[str, Any]] = {}
confirmed_orders: Dict[str, Dict[str, Any]] = {}
# persistent users mapping: user_id -> {"orders": [refs], ...}
stored_users: Dict[str, Any] = {}
# admin_messages: mapping user_id_str -> {"full": text, "preview": str, "time": ts, "replied": bool, "reply": str}
admin_messages: Dict[str, Dict[str, Any]] = {}
banned_users = set()

# ====================== PERSISTENCE HELPERS ======================
def load_db():
    global pending_orders, confirmed_orders, stored_users, admin_messages, banned_users, PRODUCTS
    if not os.path.exists(DB_FILE):
        db = {
            "banned_users": [],
            "products_stock": {pid: PRODUCTS[pid]["stock"] for pid in PRODUCTS},
            "pending_orders": {},
            "confirmed_orders": {},
            "users": {},
            "messages": {},
        }
        with open(DB_FILE, "w") as f:
            json.dump(db, f, indent=2)
        return

    with open(DB_FILE, "r") as f:
        db = json.load(f)

    # bans
    banned_users.clear()
    for uid in db.get("banned_users", []):
        try:
            banned_users.add(int(uid))
        except Exception:
            pass

    # products stock
    prod_stock = db.get("products_stock", {})
    for pid, stock in prod_stock.items():
        if pid in PRODUCTS:
            try:
                PRODUCTS[pid]["stock"] = int(stock)
            except Exception:
                pass

    # pending and confirmed orders
    pending_orders.clear()
    confirmed_orders.clear()
    for k, v in db.get("pending_orders", {}).items():
        pending_orders[k] = v
    for k, v in db.get("confirmed_orders", {}).items():
        confirmed_orders[k] = v

    # users
    stored_users.clear()
    for k, v in db.get("users", {}).items():
        stored_users[k] = v

    # admin messages
    admin_messages.clear()
    for k, v in db.get("messages", {}).items():
        admin_messages[k] = v


def save_db():
    db = {
        "banned_users": list(banned_users),
        "products_stock": {pid: PRODUCTS[pid]["stock"] for pid in PRODUCTS},
        "pending_orders": pending_orders,
        "confirmed_orders": confirmed_orders,
        "users": stored_users,
        "messages": admin_messages,
    }
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)


# ====================== USER HELPERS ======================
def get_user(uid: int):
    if uid not in user_data:
        user_data[uid] = {
            "cart": {},
            "wishlist": {},
            "orders": [],
            "secret_phrase": None,
            "awaiting_phrase": False,
            "awaiting_address": False,
            "awaiting_inpost_full": False,
            "temp_delivery": {},
            "temp_qty": {},
            "awaiting_manual_qty": None,
            "last_active": time.time(),
            "last_bot_message": None,
            "awaiting_contact": False,
            "awaiting_admin_reply": None,
            "awaiting_stock_change": None,
        }
    # sync confirmed orders into the user's view
    s = stored_users.get(str(uid), {})
    user_data[uid]["orders"] = s.get("orders", [])
    return user_data[uid]


# ====================== HELPERS ======================
async def check_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in banned_users:
        try:
            if update.message:
                await update.message.reply_text("You are banned from using this bot.")
            elif update.callback_query:
                await update.callback_query.answer("You are banned from using this bot.", show_alert=True)
        except Exception:
            pass
        return True
    return False


def main_menu_text():
    return (
        "🎉WELCOME TO PABLOCC STORE🎉\n\n"
        "Last seen: a few hours ago\n"
        "Currency: GBP\n"
        "• Send extra for fees or payment will be lost no refund🙅‍♂️\n\n"
        "Pm for any spoofing/spamming/coding enquiries @pabloscc\n\n"
        "Join for updates - https://t.me/+Gz44fjZeiudmYTJk\n\n"
        "24/7 Support and fast response times\n\n"
        "⬇️Select an option below:"
    )


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✔️Products", callback_data="show_categories")],
        [InlineKeyboardButton("🛒Cart", callback_data="menu_cart"),
         InlineKeyboardButton("❤️Wishlist", callback_data="menu_wishlist")],
        [InlineKeyboardButton("📦My Orders", callback_data="menu_orders"),
         InlineKeyboardButton("✉️Contact", callback_data="menu_contact")],
        [InlineKeyboardButton("🔐PGP Key", callback_data="pgp_key")],
    ])


# UI builders
def build_item_page_text_and_kb(pid, user):
    p = PRODUCTS[pid]
    temp = user["temp_qty"]
    qty = temp.get("qty", 1) if temp.get("pid") == pid else 1
    qty = max(1, min(qty, p["stock"]))
    text = f"{p['name']}\nPrice: £{p['£']}\nStock: {p['stock']} left\n\nQuantity selected: {qty}"
    kb = [
        [InlineKeyboardButton(f"Quantity: {qty} | Stock: {p['stock']}", callback_data="none")],
        [
            InlineKeyboardButton("-1", callback_data=f"qty_dec_{pid}"),
            InlineKeyboardButton("Manually Enter Qty", callback_data=f"qty_manual_{pid}"),
            InlineKeyboardButton("+1", callback_data=f"qty_inc_{pid}")
        ],
        [InlineKeyboardButton("Add to Cart", callback_data=f"qty_add_{pid}")],
        [InlineKeyboardButton("Add to Wishlist", callback_data=f"wishlist_add_{pid}")],
        [
            InlineKeyboardButton("Back", callback_data=f"cat_{p['cat']}"),
            InlineKeyboardButton("Main Menu", callback_data="main_menu")
        ]
    ]
    if p["stock"] == 0:
        kb[2] = [InlineKeyboardButton("OUT OF STOCK", callback_data="none")]
    return text, InlineKeyboardMarkup(kb)


async def edit_item_page_by_message(context, chat_id, message_id, pid, uid):
    user = get_user(uid)
    text, kb = build_item_page_text_and_kb(pid, user)
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=kb)
    except Exception:
        await context.bot.send_message(chat_id, text, reply_markup=kb)


# UI pages
async def show_categories(q):
    kb = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in CATEGORIES]
    kb.append([InlineKeyboardButton("Main Menu", callback_data="main_menu")])
    await q.edit_message_text("Select a category:", reply_markup=InlineKeyboardMarkup(kb))


async def show_item_page(q, pid):
    p = PRODUCTS[pid]
    uid = q.from_user.id
    user = get_user(uid)
    text, kb = build_item_page_text_and_kb(pid, user)
    try:
        await q.edit_message_text(text, reply_markup=kb)
        try:
            msg = q.message
            user["last_bot_message"] = {"chat_id": msg.chat.id, "message_id": msg.message_id}
        except Exception:
            user["last_bot_message"] = None
    except Exception:
        sent = await q.message.reply_text(text, reply_markup=kb)
        user["last_bot_message"] = {"chat_id": sent.chat.id, "message_id": sent.message_id}


async def show_wishlist(q):
    user = get_user(q.from_user.id)
    if not user["wishlist"]:
        await q.edit_message_text("Your wishlist is empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Shop Now", callback_data="show_categories")], [InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))
        return
    text = "YOUR WISHLIST\n\n"
    kb = []
    for pid, qty in user["wishlist"].items():
        p = PRODUCTS[pid]
        text += f"• {p['name']} × {qty} — £{p['£'] * qty}\n"
        kb.append([InlineKeyboardButton(f"Add ×{qty} to Cart", callback_data=f"wishlist_to_cart_{pid}")])
        kb.append([InlineKeyboardButton("Remove", callback_data=f"wishlist_remove_{pid}")])
    kb.append([InlineKeyboardButton("Main Menu", callback_data="main_menu")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


# show user's own orders (confirmed)
async def show_user_orders(q):
    uid = q.from_user.id
    user = get_user(uid)
    orders = user.get("orders", [])
    if not orders:
        await q.edit_message_text("You have no orders.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))
        return
    text = "YOUR ORDERS (confirmed):\n\n"
    kb = []
    for ref in orders:
        od = confirmed_orders.get(ref) or pending_orders.get(ref) or {}
        text += f"• {ref} — £{od.get('total_gbp','?')} — {od.get('coin','')}\n"
        kb.append([InlineKeyboardButton(f"View {ref}", callback_data=f"order_view_{ref}")])
    kb.append([InlineKeyboardButton("Main Menu", callback_data="main_menu")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def view_order_for_user(q, ref):
    uid = q.from_user.id
    user = get_user(uid)
    if str(uid) not in stored_users:
        user_orders = []
    else:
        user_orders = stored_users[str(uid)].get("orders", [])
    if ref not in user_orders:
        await q.answer("You don't have permission to view this order.", show_alert=True)
        return
    od = confirmed_orders.get(ref) or pending_orders.get(ref)
    if not od:
        await q.edit_message_text("Order not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))
        return
    text = f"ORDER {ref}\nTotal: £{od.get('total_gbp')}\nCoin: {od.get('coin')}\nItems:\n"
    for pid, qty in od.get("items", {}).items():
        text += f"• {PRODUCTS.get(pid, {}).get('name', pid)} × {qty}\n"
    text += f"\nStatus: {od.get('status','pending')}\n"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))


# BUTTON HANDLER
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    user = get_user(uid)

    if await check_ban(update, context):
        return

    if user.get("awaiting_phrase"):
        await q.answer("Please send your secret phrase in chat to continue.", show_alert=True)
        return

    now = time.time()
    last = user.get("last_active", 0)
    if user.get("secret_phrase") and (now - last > 600):
        user["awaiting_phrase"] = True
        try:
            await context.bot.send_message(uid, "Session expired due to 10 minutes of inactivity. Send your secret phrase to continue:")
        except Exception:
            await q.answer("Session expired — check chat for phrase prompt.", show_alert=True)
        return

    user["last_active"] = now
    await q.answer()
    data = q.data

    if data == "main_menu":
        await q.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard())
        return

    if data == "show_categories":
        await show_categories(q)
        return

    if data.startswith("cat_"):
        cat = data[4:]
        items = [pid for pid, p in PRODUCTS.items() if p["cat"] == cat]
        text = f"{cat.upper()}:\n\n"
        kb = []
        for pid in items:
            p = PRODUCTS[pid]
            text += f"• {p['name']} — £{p['£']}\n"
            kb.append([InlineKeyboardButton(p["name"], callback_data=f"item_{pid}")])
        kb.append([InlineKeyboardButton("Back", callback_data="show_categories"), InlineKeyboardButton("Main Menu", callback_data="main_menu")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("item_"):
        pid = data[5:]
        await show_item_page(q, pid)
        return

    if data.startswith("wishlist_add_"):
        pid = data[13:]
        p = PRODUCTS[pid]
        temp = user["temp_qty"]
        qty = temp.get("qty", 1) if temp.get("pid") == pid else 1
        qty = max(1, min(qty, p["stock"]))
        user["wishlist"][pid] = qty
        kb = [[InlineKeyboardButton("❤️ View Wishlist", callback_data="menu_wishlist")],[InlineKeyboardButton("⬅️ Back", callback_data=f"item_{pid}")],[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
        await q.edit_message_text(f"✔️ Added {p['name']} ×{qty} to your wishlist!", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "menu_wishlist":
        await show_wishlist(q)
        return

    if data.startswith("wishlist_remove_"):
        pid = data[16:]
        user["wishlist"].pop(pid, None)
        await q.answer("Removed ✔")
        await show_wishlist(q)
        return

    if data.startswith("wishlist_to_cart_"):
        pid = data[17:]
        qty = user["wishlist"].get(pid, 0)
        if qty == 0 or PRODUCTS[pid]["stock"] < qty:
            await q.answer("Not enough stock!", show_alert=True)
            return
        user["cart"][pid] = user["cart"].get(pid, 0) + qty
        del user["wishlist"][pid]
        kb = [[InlineKeyboardButton("🛒 Go To Cart", callback_data="menu_cart")],[InlineKeyboardButton("❤️ Back to Wishlist", callback_data="menu_wishlist")],[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
        await q.edit_message_text(f"✔️ Moved {PRODUCTS[pid]['name']} ×{qty} to your cart!", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("qty_inc_"):
        pid = data[8:]
        cur = user["temp_qty"].get("qty", 1)
        if user["temp_qty"].get("pid") != pid:
            cur = 1
        new_qty = min(cur + 1, PRODUCTS[pid]["stock"])
        user["temp_qty"] = {"pid": pid, "qty": new_qty}
        await show_item_page(q, pid)
        return

    if data.startswith("qty_dec_"):
        pid = data[8:]
        cur = user["temp_qty"].get("qty", 1)
        if user["temp_qty"].get("pid") != pid:
            cur = 1
        new_qty = max(1, cur - 1)
        user["temp_qty"] = {"pid": pid, "qty": new_qty}
        await show_item_page(q, pid)
        return

    if data.startswith("qty_manual_"):
        pid = data[11:]
        user["awaiting_manual_qty"] = pid
        p = PRODUCTS[pid]
        prompt_text = f"Enter quantity for {p['name']} (1–{p['stock']}):\n\nType the number in chat."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"item_{pid}")]])
        lm = user.get("last_bot_message")
        if lm:
            try:
                await context.bot.edit_message_text(chat_id=lm["chat_id"], message_id=lm["message_id"], text=prompt_text, reply_markup=kb)
            except Exception:
                await q.edit_message_text(prompt_text, reply_markup=kb)
        else:
            await q.edit_message_text(prompt_text, reply_markup=kb)
        return

    if data.startswith("qty_add_"):
        pid = data[8:]
        qty = user["temp_qty"].get("qty", 1)
        if user["temp_qty"].get("pid") != pid:
            qty = 1
        if qty > PRODUCTS[pid]["stock"]:
            await q.answer("Not enough stock!", show_alert=True)
            return
        user["cart"][pid] = user["cart"].get(pid, 0) + qty
        user["temp_qty"] = {}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("View Cart", callback_data="menu_cart")],[InlineKeyboardButton("Continue Shopping", callback_data="show_categories")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]])
        await q.edit_message_text(f"Added {qty} × {PRODUCTS[pid]['name']} to cart!", reply_markup=kb)
        return

    if data == "menu_cart":
        cart = user["cart"]
        if not cart:
            await q.edit_message_text("Your cart is empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Shop Now", callback_data="show_categories")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))
            return
        total = sum(PRODUCTS[k]["£"] * v for k, v in cart.items())
        txt = "YOUR CART:\n\n" + "\n".join(f"• {PRODUCTS[k]['name']} × {v} = £{PRODUCTS[k]['£'] * v}" for k, v in cart.items())
        txt += f"\n\nTotal: £{total}\n\nChoose delivery:"
        kb = [[InlineKeyboardButton("InPost Locker (Free)", callback_data="delivery_inpost")],[InlineKeyboardButton("Home Delivery", callback_data="delivery_home")],[InlineKeyboardButton("Empty Cart", callback_data="empty_cart")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "empty_cart":
        user["cart"].clear()
        await q.edit_message_text("Cart cleared.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))
        return

    if data == "delivery_inpost":
        user["awaiting_inpost_full"] = True
        user["temp_delivery"]["method"] = "InPost (Free)"
        await q.edit_message_text("Enter InPost delivery info in one message:\n\nFormat:\nFull Name | Email | Phone | Locker Address\n\nExample:\nJohn Smith | john@gmail.com | 07123456789 | Tesco soho - SE6 7BH", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_cart")]]))
        return

    if data == "delivery_home":
        user["awaiting_address"] = True
        user["temp_delivery"]["method"] = "Home Delivery"
        await q.edit_message_text("Enter Home delivery info in one message:\n\nFormat:\nFull Name | Email | Phone | Adrress | City | Postcode\n\nExample:\nJohn Smith | john@gmail.com | 07123456789 | 1 happy street | soho | SE6 7BH", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_cart")]]))
        return

    if data.startswith("pay_"):
        coin = data[4:].upper()
        base_total = sum(PRODUCTS[k]["£"] * v for k, v in user["cart"].items())
        extra = user["temp_delivery"].get("extra", 0)
        total_gbp = base_total + extra
        addr = WALLETS.get(coin)
        if not addr:
            await q.answer(f"No address configured for {coin}", show_alert=True)
            return
        try:
            await q.answer(f"{coin} address:\n{addr}", show_alert=True)
        except Exception:
            pass
        ref = hashlib.sha256(f"{uid}{time.time()}".encode()).hexdigest()[:10].upper()
        msg = (f"ORDER #{ref}\nTotal: £{total_gbp} ({coin})\n\nSend {coin} to:\n{addr}\n\nReference: {ref}\n\nAfter sending, wait for payment confirmation.")
        pending_orders[ref] = {"user_id": uid, "ref": ref, "total_gbp": total_gbp, "coin": coin, "items": user["cart"].copy(), "created": time.time(), "shipping": user["temp_delivery"].copy(), "status": "pending"}
        save_db()
        try:
            await context.bot.send_message(ADMIN_ID, f"NEW ORDER #{ref}\nUser: {uid}\nTotal: £{total_gbp}\nCoin: {coin}\n\nShipping Info:\n{pending_orders[ref]['shipping']}")
        except Exception:
            pass
        user["cart"].clear()
        user["temp_delivery"] = {}
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))
        return

    if data == "admin_open":
        if uid != ADMIN_ID:
            await q.answer("Access denied", show_alert=True)
            return
        kb = [[InlineKeyboardButton(f"Pending Orders ({len(pending_orders)})", callback_data="admin_pending")],[InlineKeyboardButton("✔ Confirmed Orders", callback_data="admin_confirmed")],[InlineKeyboardButton("Stock Manager", callback_data="admin_stock")],[InlineKeyboardButton("Messages", callback_data="admin_messages")],[InlineKeyboardButton("Ban/Unban User", callback_data="admin_ban")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]
        await q.edit_message_text("ADMIN PANEL", reply_markup=InlineKeyboardMarkup(kb))
        return

    # Admin pending list
    if data == "admin_pending":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        if not pending_orders:
            await q.edit_message_text("No pending orders.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_open")]]))
            return
        text = "PENDING ORDERS:\n\n"
        kb = []
        for ref, od in pending_orders.items():
            text += f"• {ref} — £{od['total_gbp']} — {od['coin']} — User {od['user_id']}\n"
            kb.append([InlineKeyboardButton(f"View {ref}", callback_data=f"admin_view_pending_{ref}")])
        kb.append([InlineKeyboardButton("Back", callback_data="admin_open")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_view_pending_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        ref = data[len("admin_view_pending_"):]
        od = pending_orders.get(ref)
        if not od:
            await q.edit_message_text("Order not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_pending")]]))
            return
        text = f"ORDER {ref}\nUser: {od['user_id']}\nTotal: £{od['total_gbp']} — {od['coin']}\n\nITEMS:\n"
        for pid, qty in od["items"].items():
            name = PRODUCTS.get(pid, {}).get("name", pid)
            text += f"• {name} × {qty}\n"
        text += "\nSHIPPING:\n"
        for k, v in od["shipping"].items():
            text += f"{k}: {v}\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✔ Confirm", callback_data=f"admin_confirm_{ref}")],[InlineKeyboardButton("✖ Cancel", callback_data=f"admin_cancel_{ref}")],[InlineKeyboardButton("Back", callback_data="admin_pending")]])
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("admin_confirm_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        ref = data[len("admin_confirm_"):]
        od = pending_orders.pop(ref, None)
        if not od:
            await q.answer("Order not found.", show_alert=True)
            return
        od["status"] = "confirmed"
        confirmed_orders[ref] = od
        # add to persistent user orders
        uid_str = str(od["user_id"])
        stored_users.setdefault(uid_str, {})
        stored_users[uid_str].setdefault("orders", [])
        if ref not in stored_users[uid_str]["orders"]:
            stored_users[uid_str]["orders"].append(ref)
        # sync in-memory if user present
        if int(uid_str) in user_data:
            user_data[int(uid_str)]["orders"] = stored_users[uid_str]["orders"]
        save_db()
        try:
            await context.bot.send_message(od["user_id"], "payment confirmed - order being processed")
        except Exception:
            pass
        await q.edit_message_text(f"Order {ref} marked as CONFIRMED.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_pending")]]))
        return

    if data.startswith("admin_cancel_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        ref = data[len("admin_cancel_"):]
        od = pending_orders.pop(ref, None)
        if not od:
            await q.answer("Order not found.", show_alert=True)
            return
        od["status"] = "canceled"
        # record canceled in confirmed_orders for history
        confirmed_orders[ref] = od
        save_db()
        try:
            await context.bot.send_message(od["user_id"], f"Your order {ref} has been CANCELLED.")
        except Exception:
            pass
        await q.edit_message_text(f"Order {ref} CANCELLED.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_pending")]]))
        return


    if data == "admin_confirmed":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        if not confirmed_orders:
            await q.edit_message_text("No confirmed orders.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_open")]]))
            return
        text = "CONFIRMED ORDERS:\n\n"
        kb = []
        for ref, od in confirmed_orders.items():
            text += f"• {ref} — £{od.get('total_gbp','?')} — User {od.get('user_id')}\n"
            kb.append([InlineKeyboardButton(f"View {ref}", callback_data=f"admin_view_confirmed_{ref}")])
        kb.append([InlineKeyboardButton("Back", callback_data="admin_open")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_view_confirmed_"):
        if uid != ADMIN_ID:
            return
        ref = data[len("admin_view_confirmed_"):]
        od = confirmed_orders.get(ref)
        if not od:
            await q.edit_message_text("Order not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_confirmed")]]))
            return
        text = f"ORDER {ref}\nUser: {od['user_id']}\nTotal: £{od['total_gbp']} — {od['coin']}\n\nITEMS:\n"
        for pid, qty in od["items"].items():
            name = PRODUCTS.get(pid, {}).get("name", pid)
            text += f"• {name} × {qty}\n"
        text += "\nSHIPPING:\n"
        for k, v in od["shipping"].items():
            text += f"{k}: {v}\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Delete Order", callback_data=f"admin_delete_confirmed_{ref}")],[InlineKeyboardButton("Back", callback_data="admin_confirmed")]])
        await q.edit_message_text(text, reply_markup=kb)
        return
    # -------- ADMIN: Delete Confirmed Order --------
    if data.startswith("admin_delete_confirmed_"):
        if uid != ADMIN_ID:
            return

        ref = data[len("admin_delete_confirmed_"):]
        od = confirmed_orders.get(ref)

        if not od:
            await q.edit_message_text(
                "Order not found.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back", callback_data="admin_confirmed")]
                ])
            )
            return

        # delete from confirmed orders
        confirmed_orders.pop(ref, None)

        # delete from user's stored orders
        user_id = od["user_id"]
        uid_str = str(user_id)

        if uid_str in stored_users:
            user_orders = stored_users[uid_str].get("orders", [])
            if ref in user_orders:
                user_orders.remove(ref)

        save_db()

        await q.edit_message_text(
            f"Order {ref} has been permanently deleted.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data="admin_confirmed")]
            ])
        )
        return

    if data == "admin_stock":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        text = "STOCK MANAGER:\n\n"
        kb = []
        for pid, p in PRODUCTS.items():
            text += f"{p['name']}: {p['stock']}\n"
            kb.append([InlineKeyboardButton(p["name"], callback_data=f"admin_stock_{pid}")])
        kb.append([InlineKeyboardButton("Back", callback_data="admin_open")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_stock_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        pid = data[len("admin_stock_"):]
        user["awaiting_stock_change"] = pid
        p = PRODUCTS[pid]
        await q.edit_message_text(f"Enter new stock amount for {p['name']} (current: {p['stock']}):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_stock")]]))
        return

    if data == "admin_messages":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        if not admin_messages:
            await q.edit_message_text("No messages from users.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_open")]]))
            return
        text = "MESSAGES FROM USERS:\n\n"
        kb = []
        for mid, m in admin_messages.items():
            text += f"• From {mid} — {m.get('preview','')}\n"
            kb.append([InlineKeyboardButton("Open "+str(mid), callback_data=f"admin_message_{mid}")])
        kb.append([InlineKeyboardButton("Clear Messages", callback_data="admin_clear_messages")])
        kb.append([InlineKeyboardButton("Back", callback_data="admin_open")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "admin_clear_messages":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        admin_messages.clear()
        save_db()
        await q.edit_message_text("All messages cleared.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_messages")]]))
        return

    if data.startswith("admin_message_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        mid = data[len("admin_message_"):]
        msg = admin_messages.get(mid)
        if not msg:
            await q.edit_message_text("Message not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_messages")]]))
            return
        text = f"Message from {mid} (time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(msg.get('time',0)))}):\n\n{msg.get('full','')}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Reply", callback_data=f"admin_reply_{mid}")],[InlineKeyboardButton("Back", callback_data="admin_messages")]])
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("admin_reply_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        mid = data[len("admin_reply_"):]
        user["awaiting_admin_reply"] = mid
        await q.edit_message_text(f"Type your reply to user {mid} (send as a chat message):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"admin_message_{mid}")]]))
        return

    if data == "admin_ban":
        # open ban prompt in chat (admin types target id)
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        context.user_data["awaiting_ban"] = True
        await q.edit_message_text("Send numeric Telegram User ID to ban/unban (in chat):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_open")]]))
        return

    if data == "pgp_key":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="main_menu")]])
        await q.edit_message_text(f"PGP PUBLIC KEY (🔑PGP KEY\n\n Here is our PGP keyfor secure communication:\n\n{PGP_KEY}", reply_markup=kb)
        return

    if data == "menu_contact":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Write a new message", callback_data="contact_write")],[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        await q.edit_message_text("Messages are one-time read only\n\n you have no new messages from the store.\n\n Tap 'Write a new message' to start a conversation.", reply_markup=kb)
        return

    if data == "contact_write":
        user["awaiting_contact"] = True
        await q.edit_message_text("💬Write your message for the store owner:\n\n just type your message and send it directly in the chat.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_contact")]]))
        return

    if data == "menu_orders":
        await show_user_orders(q)
        return

    if data.startswith("order_view_"):
        ref = data[len("order_view_"):]
        await view_order_for_user(q, ref)
        return

    await q.answer()


# MESSAGE HANDLER
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_ban(update, context):
        return
    uid = update.effective_user.id
    user = get_user(uid)
    text = update.message.text.strip()

    # phrase handling
    if user.get("awaiting_phrase"):
        if user.get("secret_phrase") is None:
            if not (4 <= len(text) <= 60):
                await update.message.reply_text("Secret phrase must be 4–60 characters. Try again.")
                return
            user["secret_phrase"] = text
            user["awaiting_phrase"] = False
            user["last_active"] = time.time()
            save_db()
            await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard())
            return
        else:
            if text != user["secret_phrase"]:
                await update.message.reply_text("Incorrect phrase. Try again:")
                return
            user["awaiting_phrase"] = False
            user["last_active"] = time.time()
            save_db()
            await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard())
            return

    # auto-lock
    now = time.time()
    if user.get("secret_phrase") and (now - user.get("last_active", 0) > 600):
        user["awaiting_phrase"] = True
        await update.message.reply_text("Session expired due to inactivity. Send your secret phrase to continue:")
        return
    user["last_active"] = now

    # admin stock change via chat
    if uid == ADMIN_ID and user.get("awaiting_stock_change"):
        pid = user.get("awaiting_stock_change")
        if not text.isdigit():
            await update.message.reply_text("Send a number.")
            return
        PRODUCTS[pid]["stock"] = int(text)
        user["awaiting_stock_change"] = None
        save_db()
        await update.message.reply_text(f"Stock updated for {PRODUCTS[pid]['name']}.")
        return

    # admin ban/unban via chat (triggered by admin panel)
    if uid == ADMIN_ID and context.user_data.get("awaiting_ban"):
        if not text.isdigit():
            await update.message.reply_text("Send a valid numeric User ID.")
            return
        target = int(text)
        if target in banned_users:
            banned_users.remove(target)
            await update.message.reply_text(f"Unbanned {target}.")
        else:
            banned_users.add(target)
            await update.message.reply_text(f"Banned {target}.")
        save_db()
        context.user_data.pop("awaiting_ban", None)
        return

    # manual qty entry
    if user.get("awaiting_manual_qty"):
        pid = user["awaiting_manual_qty"]
        user["awaiting_manual_qty"] = None
        if not text.isdigit():
            await update.message.reply_text("❌ Invalid number.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"item_{pid}")]]))
            return
        qty = int(text)
        max_qty = PRODUCTS[pid]["stock"]
        if not (1 <= qty <= max_qty):
            await update.message.reply_text(f"❌ Quantity must be 1–{max_qty}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"item_{pid}")]]))
            return
        user["temp_qty"] = {"pid": pid, "qty": qty}
        lm = user.get("last_bot_message")
        if lm:
            await edit_item_page_by_message(context, lm["chat_id"], lm["message_id"], pid, uid)
            await update.message.reply_text(f"Quantity updated to {qty} ✔️", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Return", callback_data=f"item_{pid}")]]))
        else:
            text_out, kb = build_item_page_text_and_kb(pid, user)
            sent = await update.message.reply_text(text_out, reply_markup=kb)
            user["last_bot_message"] = {"chat_id": sent.chat.id, "message_id": sent.message_id}
        return

    # inpost handler
    if user.get("awaiting_inpost_full"):
        user["awaiting_inpost_full"] = False
        user["temp_delivery"]["info"] = text
        try:
            await context.bot.send_message(ADMIN_ID, f"INPOST SHIPPING INFO FROM USER {uid}:\n{text}")
        except Exception:
            pass
        base_total = sum(PRODUCTS[k]["£"] * v for k, v in user["cart"].items())
        kb = [[InlineKeyboardButton(c, callback_data=f"pay_{c}")] for c in WALLETS.keys()]
        kb.append([InlineKeyboardButton("Main Menu", callback_data="main_menu")])
        await update.message.reply_text(f"InPost details saved.\nTotal: £{base_total}\n\nChoose payment method:", reply_markup=InlineKeyboardMarkup(kb))
        return

    # home delivery
    if user.get("awaiting_address"):
        user["awaiting_address"] = False
        user["temp_delivery"]["address"] = text
        try:
            await context.bot.send_message(ADMIN_ID, f"HOME DELIVERY ADDRESS FROM USER {uid}:\n{text}")
        except Exception:
            pass
        await update.message.reply_text("Select delivery speed:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next Day (£10)", callback_data="method_nextday")],[InlineKeyboardButton("2-3 Day (Free)", callback_data="method_standard")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]))
        return

    # contact message handling
    if user.get("awaiting_contact"):
        user["awaiting_contact"] = False
        admin_messages[str(uid)] = {"full": text, "preview": text[:60], "time": time.time(), "replied": False, "reply": None}
        save_db()
        # send to admin privately (no extra bot chat message beyond confirmation menu)
        try:
            await context.bot.send_message(ADMIN_ID, f"📩 New message from {uid}:\n\n{text}")
        except Exception:
            pass
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back to Contact", callback_data="menu_contact"), InlineKeyboardButton("Main Menu", callback_data="main_menu")]])
        await update.message.reply_text("✅Your message has been sent to the store owner.", reply_markup=kb)
        return

    # admin replying in-chat (when admin clicked Reply and then typed)
    if user.get("awaiting_admin_reply"):
        mid = user["awaiting_admin_reply"]
        user["awaiting_admin_reply"] = None
        try:
            target = int(mid)
            admin_messages.setdefault(str(target), {}).update({"replied": True, "reply": text})
            # ensure stored_users key exists (keeps persistence consistent)
            stored_users.setdefault(str(target), {}).setdefault("orders", stored_users.get(str(target), {}).get("orders", []))
            save_db()
            await context.bot.send_message(target, f"💬 Reply from store:\n\n{text}")
        except Exception:
            pass
        await update.message.reply_text(f"Reply sent to user {mid}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_messages")]]))
        return

    # default fallback
    await update.message.reply_text("Use /start or the menu buttons.")


# START and ADMIN PANEL commands
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_ban(update, context):
        return
    user = get_user(update.effective_user.id)
    if user["secret_phrase"] is None:
        user["awaiting_phrase"] = True
        await update.message.reply_text("👋Welcome to GALORE BOT! This appears to be your first time here\n\n 🔑Please set a phrase-key (between 4–60 characters) that will be used for authentication when you're inactive for more than 10 minutes:")
        return
    now = time.time()
    if user.get("secret_phrase") and (now - user.get("last_active", 0) > 600):
        user["awaiting_phrase"] = True
        await update.message.reply_text("❌Please enter your 4–60 character phrase key:")
        return
    user["last_active"] = time.time()
    await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard())


async def admin_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Access denied.")
        return
    kb = [[InlineKeyboardButton(f"Pending Orders ({len(pending_orders)})", callback_data="admin_pending")],[InlineKeyboardButton("✔ Confirmed Orders", callback_data="admin_confirmed")],[InlineKeyboardButton("Stock Manager", callback_data="admin_stock")],[InlineKeyboardButton("Messages", callback_data="admin_messages")],[InlineKeyboardButton("Ban/Unban User", callback_data="admin_ban")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]
    await update.message.reply_text("ADMIN PANEL", reply_markup=InlineKeyboardMarkup(kb))


# Admin convenience reply command: /reply <user_id> <text>
async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Forbidden.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /reply <user_id> <message text>")
        return
    try:
        target = int(args[0])
    except Exception:
        await update.message.reply_text("Invalid user id.")
        return
    reply_text = " ".join(args[1:])
    try:
        admin_messages.setdefault(str(target), {}).update({"replied": True, "reply": reply_text})
        save_db()
        await context.bot.send_message(target, f"💬 Reply from store:\n\n{reply_text}")
    except Exception as e:
        await update.message.reply_text(f"Failed to send message: {e}")
        return
    await update.message.reply_text("Reply sent.")


def main():
    load_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    # command handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_panel_cmd))
    app.add_handler(CommandHandler("reply", reply_command))
    # callback + message handlers
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()