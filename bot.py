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
TELEGRAM_TOKEN = "8775358499:AAEshY_6WpSXhr948B1dLDnuBMlC5zxmIkk"
ADMIN_ID = 1942502806  # set your admin telegram id here
MIN_GBP = 0

DB_FILE = "database.json"

# ====================== WALLETS / PRODUCTS ======================
WALLETS = {
    "BTC": "bc1qegrl4yhpaym0nmkesmy3ncc4a727dupaklz4j0",
    "ETH": "0xfA66D24f9dA4c1fe4b3A3c6625EBBA788f6f41Ea",
    "LTC": "LZH7L6tCgNmCEwzbnPsLqrVRtWuKUG1ekd",
    "USDT TRC20": "TPASTE_YOUR_USDT_TRC20_WALLET_HERE",
}

# Legal digital products only. Product IDs are kept the same so the stock editor and old database shape keep working.
CATEGORIES = ["Barclays", "Lloyds", "Hsbc", "Halifax", "Nationwide", "Santander", "Bank of scotland", "Amex"]

PRODUCTS = {
    "552157": {"name": "552157 - Platinum credit", "£": 25, "cat": "Lloyds", "stock": 16},
    "465941": {"name": "465941 - Business debit", "£": 25, "cat": "Hsbc", "stock": 11},
    "465923": {"name": "465923 - Platinum debit", "£": 25, "cat": "Barclays", "stock": 15},
    "465861": {"name": "465861 - Business debit", "£": 25, "cat": "Barclays", "stock": 9},
    "492915": {"name": "492915 - Platinum credit", "£": 25, "cat": "Barclays", "stock": 7},
    "465860": {"name": "465860 - Business debit", "£": 25, "cat": "Barclays", "stock": 6},
    "465922": {"name": "465922 - Platinum debit", "£": 25, "cat": "Barclays", "stock": 2},
    "459630": {"name": "459630 - Business debit", "£": 15, "cat": "Barclays", "stock": 1},
    "465935": {"name": "465935 - Classic debit", "£": 15, "cat": "Nationwide", "stock": 1},
    "465865": {"name": "465865 - Classic debit", "£": 15, "cat": "Barclays", "stock": 1},
    "535668": {"name": "535668 - Business debit", "£": 25, "cat": "Santander", "stock": 8},
    "446291": {"name": "446291 - Classic debit", "£": 25, "cat": "Halifax", "stock": 8},
    "535666": {"name": "535666 - Standard debit", "£": 25, "cat": "Santander", "stock": 5},
    "454313": {"name": "454313 - Classic debit", "£": 25, "cat": "Nationwide", "stock": 4},
    "446278": {"name": "446278 - Classic debit", "£": 25, "cat": "Halifax", "stock": 3},
    "556314": {"name": "556314 - Classic credit", "£": 25, "cat": "Lloyds", "stock": 2},
    "540440": {"name": "540440 - Gold credit", "£": 15, "cat": "Lloyds", "stock": 2},
    "446238": {"name": "446238 - Classic debit", "£": 20, "cat": "Bank of scotland", "stock": 1},
    "476224": {"name": "476224 - Classic debit", "£": 15, "cat": "Bank of scotland", "stock": 1},
    "446272": {"name": "446272 - Platinum debit", "£": 15, "cat": "Lloyds", "stock": 1},
    "475144": {"name": "475144 - Classic debit", "£": 15, "cat": "Nationwide", "stock": 1},
    "462726": {"name": "462726 - Platinum credit", "£": 25, "cat": "Hsbc", "stock": 1},
    "376015": {"name": "376015 - Globestar", "£": 25, "cat": "Amex", "stock": 1},
    "374692": {"name": "374692 - Globestar", "£": 25, "cat": "Amex", "stock": 1},
    "371784": {"name": "371784 - Globestar", "£": 25, "cat": "Amex", "stock": 1},
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
reviews = []
banned_users = set()
# Optional per-unit stock. Use this when each sold item must deliver unique information.
# Example: {"handheld": ["CODE-1", "CODE-2"]}
product_items: Dict[str, list] = {}

# ====================== PERSISTENCE HELPERS ======================
def load_db():
    global pending_orders, confirmed_orders, stored_users, admin_messages, reviews, banned_users, PRODUCTS, product_items
    if not os.path.exists(DB_FILE):
        db = {
            "banned_users": [],
            "products_stock": {pid: PRODUCTS[pid]["stock"] for pid in PRODUCTS},
            "product_items": {pid: [] for pid in PRODUCTS},
            "pending_orders": {},
            "confirmed_orders": {},
            "users": {},
            "messages": {},
            "reviews": [],
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

    # unique per-unit stock items, if used
    product_items.clear()
    for pid in PRODUCTS:
        product_items[pid] = []
    for pid, items in db.get("product_items", {}).items():
        if pid in PRODUCTS and isinstance(items, list):
            product_items[pid] = [str(x) for x in items]
            # When unique items exist, stock follows the number of remaining entries.
            if product_items[pid]:
                PRODUCTS[pid]["stock"] = len(product_items[pid])

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

    reviews.clear()
    reviews.extend(db.get("reviews", []))


def save_db():
    db = {
        "banned_users": list(banned_users),
        "products_stock": {pid: PRODUCTS[pid]["stock"] for pid in PRODUCTS},
        "product_items": product_items,
        "pending_orders": pending_orders,
        "confirmed_orders": confirmed_orders,
        "users": stored_users,
        "messages": admin_messages,
        "reviews": reviews,
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
            "awaiting_review": False,
            "awaiting_deposit_amount": False,
        }
    # Sync permanent account data back into the active session.
    s = ensure_stored_user(uid)
    user_data[uid]["orders"] = s.get("orders", [])
    if s.get("secret_phrase") and not user_data[uid].get("secret_phrase"):
        user_data[uid]["secret_phrase"] = s.get("secret_phrase")
    return user_data[uid]



def ensure_stored_user(uid: int):
    uid_str = str(uid)
    stored_users.setdefault(uid_str, {})
    u = stored_users[uid_str]
    # Permanent account fields. These stay in database.json and survive sessions/restarts.
    u.setdefault("orders", [])
    u.setdefault("pending_orders", [])
    u.setdefault("purchase_history", [])
    u.setdefault("deposit_history", [])
    u.setdefault("transaction_history", [])
    u.setdefault("balance", 0)
    u.setdefault("total_deposited", 0)
    u.setdefault("total_spent", 0)
    u.setdefault("lifetime_orders", 0)
    u.setdefault("secret_phrase", None)
    return u


def remember_pending_for_user(uid: int, ref: str):
    buyer = ensure_stored_user(uid)
    if ref not in buyer["pending_orders"]:
        buyer["pending_orders"].append(ref)


def remove_pending_for_user(uid: int, ref: str):
    buyer = ensure_stored_user(uid)
    if ref in buyer.get("pending_orders", []):
        buyer["pending_orders"].remove(ref)


def nav_rows(back_callback=None, main=True):
    rows = []
    nav = []
    if back_callback:
        nav.append(InlineKeyboardButton("⬅️ Back", callback_data=back_callback))
    if main:
        nav.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))
    if nav:
        rows.append(nav)
    return rows


def cart_total(cart):
    return sum(PRODUCTS[k]["£"] * v for k, v in cart.items() if k in PRODUCTS)


def items_text(items):
    if not items:
        return "None"
    return "\n".join(f"• {PRODUCTS.get(pid, {}).get('name', pid)} × {qty}" for pid, qty in items.items())


def make_ref(uid: int):
    return hashlib.sha256(f"{uid}{time.time()}".encode()).hexdigest()[:10].upper()


def admin_panel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"Pending Payments ({len(pending_orders)})", callback_data="admin_pending")],[InlineKeyboardButton("✔ Confirmed Orders", callback_data="admin_confirmed")],[InlineKeyboardButton("Stock Manager", callback_data="admin_stock")],[InlineKeyboardButton("Messages", callback_data="admin_messages")],[InlineKeyboardButton("Ban/Unban User", callback_data="admin_ban")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]])


def coin_keyboard(prefix="pay"):
    kb = [[InlineKeyboardButton(c, callback_data=f"{prefix}_{c}")] for c in WALLETS.keys()]
    kb.append([InlineKeyboardButton("Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)




def nav_keyboard(back_callback=None, main=True, extra_rows=None):
    rows = []
    if extra_rows:
        rows.extend(extra_rows)
    nav = []
    if back_callback:
        nav.append(InlineKeyboardButton("⬅️ Back", callback_data=back_callback))
    if main:
        nav.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


def pop_delivery_items(items):
    delivered = {}
    for pid, qty in items.items():
        qty = int(qty)
        if product_items.get(pid):
            delivered[pid] = product_items[pid][:qty]
            del product_items[pid][:qty]
            PRODUCTS[pid]["stock"] = len(product_items[pid])
        else:
            delivered[pid] = []
    return delivered


def delivered_text(od):
    delivered = od.get("delivered_items") or {}
    lines = []
    for pid, qty in od.get("items", {}).items():
        name = PRODUCTS.get(pid, {}).get("name", pid)
        details = delivered.get(pid, [])
        if details:
            for detail in details:
                lines.append(f"• {name}: {detail}")
        else:
            lines.append(f"• {name} × {qty}")
    return "\n".join(lines) if lines else "None"

def can_fulfil(items):
    for pid, qty in items.items():
        available = len(product_items.get(pid, [])) if product_items.get(pid) else PRODUCTS.get(pid, {}).get("stock", 0)
        if available < int(qty):
            return False, PRODUCTS.get(pid, {}).get("name", pid)
    return True, None


def deduct_stock(items):
    for pid, qty in items.items():
        if pid in PRODUCTS:
            PRODUCTS[pid]["stock"] = max(0, PRODUCTS[pid]["stock"] - int(qty))


def complete_purchase(od):
    buyer = ensure_stored_user(int(od["user_id"]))
    ref = od["ref"]
    od["status"] = "confirmed"
    od["confirmed"] = time.time()
    confirmed_orders[ref] = od
    remove_pending_for_user(int(od["user_id"]), ref)
    if ref not in buyer["orders"]:
        buyer["orders"].append(ref)
    buyer["purchase_history"].append({"ref": ref, "amount": od["total_gbp"], "items": od["items"], "time": time.time(), "method": od.get("coin", "Balance")})
    buyer["transaction_history"].append({"ref": ref, "type": "purchase", "amount": -od["total_gbp"], "method": od.get("coin", "Balance"), "time": time.time()})
    buyer["total_spent"] = buyer.get("total_spent", 0) + od["total_gbp"]
    buyer["lifetime_orders"] = buyer.get("lifetime_orders", 0) + 1
    od["delivered_items"] = pop_delivery_items(od.get("items", {}))
    # Normal stock deduction is still used for products without unique per-unit stock entries.
    normal_items = {pid: qty for pid, qty in od.get("items", {}).items() if not od["delivered_items"].get(pid)}
    deduct_stock(normal_items)
    if int(od["user_id"]) in user_data:
        user_data[int(od["user_id"])] ["orders"] = buyer["orders"]
        user_data[int(od["user_id"])] ["cart"] = {}
    save_db()

# ====================== HELPERS ======================
async def check_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in banned_users:
        try:
            if update.message:
                await update.message.reply_text("You are banned from using this bot.")
 o           elif update.callback_query:
                await update.callback_query.answer("You are banned from using this bot.", show_alert=True)
        except Exception:
            pass
        return True
    return False


def main_menu_text():
    return (
     "🎉Welcome To PabloCC Store🎉\n\n"
     "Last Seen: a few hours ago\n"
     "Currency: GBP\n\n"
     "Pm @blackphonez For Any Spoofing/Spamming/Coding Enquiries & Bulk Deals\n\n"
     "Join For Updates: https://t.me/+Gz44fjZeiudmYTJk \n\n"
     "Dedicated 24hr Support Team🕒\n\n"
     "⬇️Select an option below:"
    )


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✔️Products", callback_data="show_categories")],
        [InlineKeyboardButton("🛒Cart", callback_data="menu_cart"),
         InlineKeyboardButton("❤️Wishlist", callback_data="menu_wishlist")],
        [InlineKeyboardButton("💰Balance", callback_data="menu_balance"),
         InlineKeyboardButton("⭐Reviews", callback_data="menu_reviews")],
        [InlineKeyboardButton("📦My Orders", callback_data="menu_orders"),
         InlineKeyboardButton("📜History", callback_data="menu_history")],
        [InlineKeyboardButton("✉️Contact", callback_data="menu_contact"),
         InlineKeyboardButton("🔐PGP Key", callback_data="pgp_key")],
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
        await q.edit_message_text("Your wishlist is empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Shop Now", callback_data="show_categories")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
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
    stored = ensure_stored_user(uid)
    orders = list(stored.get("orders", []))
    pending_refs = [r for r in stored.get("pending_orders", []) if r in pending_orders]
    all_refs = pending_refs + [r for r in orders if r not in pending_refs]
    if not all_refs:
        await q.edit_message_text("You have no orders.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛍 Shop Now", callback_data="show_categories")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return
    text = "YOUR ORDERS:\n\n"
    kb = []
    for ref in all_refs:
        od = pending_orders.get(ref) or confirmed_orders.get(ref) or {}
        text += f"• {ref} — £{od.get('total_gbp','?')} — {od.get('coin','')} — {od.get('status','confirmed')}\n"
        kb.append([InlineKeyboardButton(f"View {ref}", callback_data=f"order_view_{ref}")])
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def view_order_for_user(q, ref):
    uid = q.from_user.id
    user = get_user(uid)
    if str(uid) not in stored_users:
        user_orders = []
    else:
        su = ensure_stored_user(uid)
        user_orders = su.get("orders", []) + su.get("pending_orders", [])
    if ref not in user_orders:
        await q.answer("You don't have permission to view this order.", show_alert=True)
        return
    od = pending_orders.get(ref) or confirmed_orders.get(ref)
    if not od:
        await q.edit_message_text("Order not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return
    text = f"ORDER {ref}\nTotal: £{od.get('total_gbp')}\nCoin: {od.get('coin')}\nItems:\n"
    for pid, qty in od.get("items", {}).items():
        text += f"• {PRODUCTS.get(pid, {}).get('name', pid)} × {qty}\n"
    text += f"\nStatus: {od.get('status','pending')}\n"
    if od.get("delivered_items"):
        text += f"\nDelivered details:\n{delivered_text(od)}\n"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_orders"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))


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
    # Keep the chat cleaner: delete the previous bot message when a different one is being used.
    lm = user.get("last_bot_message")
    if lm and lm.get("message_id") != q.message.message_id:
        try:
            await context.bot.delete_message(chat_id=lm["chat_id"], message_id=lm["message_id"])
        except Exception:
            pass
    user["last_bot_message"] = {"chat_id": q.message.chat_id, "message_id": q.message.message_id}

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
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="show_categories"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
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
            await q.edit_message_text("Your cart is empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Shop Now", callback_data="show_categories")],[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
            return
        total = sum(PRODUCTS[k]["£"] * v for k, v in cart.items())
        txt = "YOUR CART:\n\n" + "\n".join(f"• {PRODUCTS[k]['name']} × {v} = £{PRODUCTS[k]['£'] * v}" for k, v in cart.items())
        txt += f"\n\nTotal: £{total}\n\nReady to checkout?:"
        kb = [[InlineKeyboardButton("💳 Purchase Now", callback_data="purchase_now")],[InlineKeyboardButton("Empty Cart", callback_data="empty_cart")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]]
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "empty_cart":
        user["cart"].clear()
        await q.edit_message_text("Cart cleared.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return

    if data == "purchase_now":
        if not user["cart"]:
            await q.edit_message_text("Your cart is empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
            return
        total_gbp = cart_total(user["cart"])
        buyer = ensure_stored_user(uid)
        kb = [[InlineKeyboardButton("💰 Pay With Balance", callback_data="pay_balance")]]
        for c in WALLETS.keys():
            kb.append([InlineKeyboardButton(c, callback_data=f"pay_{c}")])
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_cart"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        await q.edit_message_text(f"Choose payment method:\n\nPurchase total: £{total_gbp}\nCurrent balance: £{buyer.get('balance', 0)}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "pay_balance":
        total_gbp = cart_total(user["cart"])
        buyer = ensure_stored_user(uid)
        ok, missing = can_fulfil(user["cart"])
        if not ok:
            await q.answer(f"Not enough stock for {missing}", show_alert=True)
            return
        if buyer.get("balance", 0) < total_gbp:
            await q.answer("Insufficient balance.", show_alert=True)
            return
        buyer["balance"] -= total_gbp
        ref = make_ref(uid)
        od = {"user_id": uid, "username": q.from_user.username, "ref": ref, "total_gbp": total_gbp, "coin": "Balance", "items": user["cart"].copy(), "created": time.time(), "status": "confirmed"}
        user["cart"].clear()
        complete_purchase(od)
        await q.edit_message_text(f"✅ Purchase complete.\nReference ID: {ref}\n\nProducts delivered:\n{delivered_text(od)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛍 Shop Now", callback_data="show_categories")], [InlineKeyboardButton("📦 My Orders", callback_data="menu_orders")], [InlineKeyboardButton("⬅️ Back", callback_data="menu_cart"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return

    if data.startswith("pay_"):
        coin = data[4:]
        total_gbp = cart_total(user["cart"])
        addr = WALLETS.get(coin)
        if not user["cart"]:
            await q.answer("Your cart is empty.", show_alert=True)
            return
        if not addr:
            await q.answer(f"No address configured for {coin}", show_alert=True)
            return
        ref = make_ref(uid)
        pending_orders[ref] = {"user_id": uid, "username": q.from_user.username, "ref": ref, "total_gbp": total_gbp, "coin": coin, "items": user["cart"].copy(), "created": time.time(), "status": "awaiting_user_paid", "type": "purchase"}
        remember_pending_for_user(uid, ref)
        save_db()
        msg = (f"ORDER #{ref}\n\n"
               f"Wallet address:\n{addr}\n\n"
               f"Reference ID: {ref}\n"
               f"Purchase total: £{total_gbp}\n"
               f"Payment method: {coin}\n\n"
               "IMPORTANT\n\n"
               "• Only send the selected cryptocurrency to the displayed address.\n\n"
               "• Sending another cryptocurrency or sending to the wrong address may permanently lose your funds.\n\n"
               "• Your order will only be processed after payment has been confirmed.\n\n"
               "After you’ve sent the payment, press “I’ve Paid”.")
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("I’ve Paid", callback_data=f"paid_{ref}")], [InlineKeyboardButton("⬅️ Back", callback_data="purchase_now"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return

    if data.startswith("paid_"):
        ref = data[len("paid_"):]
        od = pending_orders.get(ref)
        if not od or od.get("user_id") != uid:
            await q.answer("Payment not found.", show_alert=True)
            return
        od["status"] = "pending_review"
        save_db()
        try:
            await context.bot.send_message(ADMIN_ID, f"💳 Payment awaiting review\n\nUser: {q.from_user.full_name}\nTelegram ID: {uid}\nReference ID: {ref}\nCoin: {od['coin']}\nAmount: £{od['total_gbp']}\nProducts:\n{items_text(od['items'])}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open Pending Payments", callback_data="admin_pending")]]))
        except Exception:
            pass
        back_to = "menu_balance" if od.get("type") == "deposit" else "purchase_now"
        await q.edit_message_text("✅ Your payment has been submitted and your order will be delivered automatically after confirmation.", reply_markup=nav_keyboard(back_to, extra_rows=[[InlineKeyboardButton("🛍 Shop Now", callback_data="show_categories")]]))
        return

    if data == "admin_open":
        if uid != ADMIN_ID:
            await q.answer("Access denied", show_alert=True)
            return
        await q.edit_message_text("ADMIN PANEL", reply_markup=admin_panel_keyboard())
        return

    # Admin pending list
    if data == "admin_pending":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        if not pending_orders:
            await q.edit_message_text("No pending orders.", reply_markup=nav_keyboard("admin_open"))
            return
        text = "PENDING PAYMENTS:\n\n"
        kb = []
        for ref, od in pending_orders.items():
            text += f"• {ref} — £{od['total_gbp']} — {od['coin']} — User {od['user_id']} — {od.get('status','pending')}\n"
            kb.append([InlineKeyboardButton(f"View {ref}", callback_data=f"admin_view_pending_{ref}")])
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_open"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_view_pending_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        ref = data[len("admin_view_pending_"):]
        od = pending_orders.get(ref)
        if not od:
            await q.edit_message_text("Order not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_pending"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
            return
        products = od.get("items", {})
        order_type = od.get("type", "purchase")
        text = (
            f"PAYMENT {ref}\n"
            f"User: @{od.get('username') or 'No username'}\n"
            f"Telegram ID: {od.get('user_id')}\n"
            f"Reference ID: {ref}\n"
            f"Coin: {od.get('coin')}\n"
            f"Amount: £{od.get('total_gbp')}\n"
            f"Type: {order_type.title()}\n"
            f"Status: {od.get('status', 'pending')}\n\n"
            "PRODUCTS:\n"
        )
        if products:
            for pid, qty in products.items():
                name = PRODUCTS.get(pid, {}).get("name", pid)
                text += f"• {name} × {qty}\n"
        else:
            text += "• Balance deposit only\n"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"admin_confirm_{ref}"), InlineKeyboardButton("❌ Reject", callback_data=f"admin_cancel_{ref}")],
            [InlineKeyboardButton("🗑 Delete", callback_data=f"admin_delete_pending_{ref}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_pending"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ])
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("admin_delete_pending_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        ref = data[len("admin_delete_pending_"):]
        od = pending_orders.pop(ref, None)
        if not od:
            await q.answer("Payment not found.", show_alert=True)
            return
        od["status"] = "deleted"
        remove_pending_for_user(int(od["user_id"]), ref)
        save_db()
        await q.edit_message_text(f"Pending payment {ref} deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_pending"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return

    if data.startswith("admin_confirm_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        ref = data[len("admin_confirm_"):]
        od = pending_orders.pop(ref, None)
        if not od:
            await q.answer("Payment not found.", show_alert=True)
            return
        ok, missing = can_fulfil(od.get("items", {}))
        if not ok:
            pending_orders[ref] = od
            await q.answer(f"Not enough stock for {missing}", show_alert=True)
            save_db()
            return
        if od.get("type") == "deposit":
            buyer = ensure_stored_user(int(od["user_id"]))
            remove_pending_for_user(int(od["user_id"]), ref)
            buyer["balance"] = buyer.get("balance", 0) + od["total_gbp"]
            buyer["total_deposited"] = buyer.get("total_deposited", 0) + od["total_gbp"]
            buyer["deposit_history"].append({"ref": ref, "amount": od["total_gbp"], "coin": od["coin"], "time": time.time()})
            buyer["transaction_history"].append({"ref": ref, "type": "deposit", "amount": od["total_gbp"], "method": od["coin"], "time": time.time()})
            od["status"] = "confirmed"
            confirmed_orders[ref] = od
            save_db()
            try:
                await context.bot.send_message(od["user_id"], f"✅ Deposit approved. £{od['total_gbp']} has been added to your balance.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛍 Shop Now", callback_data="show_categories")], [InlineKeyboardButton("💰 Balance", callback_data="menu_balance")], [InlineKeyboardButton("⬅️ Back", callback_data="menu_history"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
            except Exception:
                pass
        else:
            complete_purchase(od)
            try:
                await context.bot.send_message(od["user_id"], f"✅ Payment approved. Your order has been delivered.\nReference ID: {ref}\n\nProducts:\n{delivered_text(od)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛍 Shop Now", callback_data="show_categories")], [InlineKeyboardButton("📦 My Orders", callback_data="menu_orders")], [InlineKeyboardButton("⬅️ Back", callback_data=f"order_view_{ref}"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
            except Exception:
                pass
        await q.edit_message_text(f"Payment {ref} approved.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_pending"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
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
        remove_pending_for_user(int(od["user_id"]), ref)
        # record canceled in confirmed_orders for history
        confirmed_orders[ref] = od
        save_db()
        try:
            await context.bot.send_message(od["user_id"], f"Your payment/order {ref} has been rejected.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_history"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        except Exception:
            pass
        await q.edit_message_text(f"Payment/order {ref} rejected.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_pending"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return


    if data == "admin_confirmed":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        if not confirmed_orders:
            await q.edit_message_text("No confirmed orders.", reply_markup=nav_keyboard("admin_open"))
            return
        text = "CONFIRMED ORDERS:\n\n"
        kb = []
        for ref, od in confirmed_orders.items():
            text += f"• {ref} — £{od.get('total_gbp','?')} — User {od.get('user_id')}\n"
            kb.append([InlineKeyboardButton(f"View {ref}", callback_data=f"admin_view_confirmed_{ref}")])
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_open"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_view_confirmed_"):
        if uid != ADMIN_ID:
            return
        ref = data[len("admin_view_confirmed_"):]
        od = confirmed_orders.get(ref)
        if not od:
            await q.edit_message_text("Order not found.", reply_markup=nav_keyboard("admin_confirmed"))
            return
        text = f"ORDER {ref}\nUser: {od.get('user_id')}\nTotal: £{od.get('total_gbp')} — {od.get('coin')}\nType: {od.get('type', 'purchase').title()}\nStatus: {od.get('status', 'confirmed')}\n\nITEMS:\n"
        products = od.get("items", {})
        if products:
            for pid, qty in products.items():
                name = PRODUCTS.get(pid, {}).get("name", pid)
                text += f"• {name} × {qty}\n"
        else:
            text += "• Balance deposit only\n"
        shipping = od.get("shipping") or {}
        if shipping:
            text += "\nSHIPPING:\n"
            for k, v in shipping.items():
                text += f"{k}: {v}\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Delete Order", callback_data=f"admin_delete_confirmed_{ref}")],[InlineKeyboardButton("⬅️ Back", callback_data="admin_confirmed"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
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
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_open"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_stock_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        pid = data[len("admin_stock_"):]
        user["awaiting_stock_change"] = pid
        p = PRODUCTS[pid]
        await q.edit_message_text(f"Enter new stock amount for {p['name']} (current: {p['stock']}):", reply_markup=nav_keyboard("admin_stock"))
        return

    if data == "admin_messages":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        if not admin_messages:
            await q.edit_message_text("No messages from users.", reply_markup=nav_keyboard("admin_open"))
            return
        text = "MESSAGES FROM USERS:\n\n"
        kb = []
        for mid, m in admin_messages.items():
            text += f"• From {mid} — {m.get('preview','')}\n"
            kb.append([InlineKeyboardButton("Open "+str(mid), callback_data=f"admin_message_{mid}")])
        kb.append([InlineKeyboardButton("Clear Messages", callback_data="admin_clear_messages")])
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_open"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "admin_clear_messages":
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        admin_messages.clear()
        save_db()
        await q.edit_message_text("All messages cleared.", reply_markup=nav_keyboard("admin_messages"))
        return

    if data.startswith("admin_message_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        mid = data[len("admin_message_"):]
        msg = admin_messages.get(mid)
        if not msg:
            await q.edit_message_text("Message not found.", reply_markup=nav_keyboard("admin_messages"))
            return
        text = f"Message from {mid} (time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(msg.get('time',0)))}):\n\n{msg.get('full','')}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Reply", callback_data=f"admin_reply_{mid}")],[InlineKeyboardButton("⬅️ Back", callback_data="admin_messages"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("admin_reply_"):
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        mid = data[len("admin_reply_"):]
        user["awaiting_admin_reply"] = mid
        await q.edit_message_text(f"Type your reply to user {mid} (send as a chat message):", reply_markup=nav_keyboard(f"admin_message_{mid}"))
        return

    if data == "admin_ban":
        # open ban prompt in chat (admin types target id)
        if uid != ADMIN_ID:
            await q.answer("Forbidden", show_alert=True)
            return
        context.user_data["awaiting_ban"] = True
        await q.edit_message_text("Send numeric Telegram User ID to ban/unban (in chat):", reply_markup=nav_keyboard("admin_open"))
        return

    if data == "menu_balance":
        buyer = ensure_stored_user(uid)
        text = (f"💰 BALANCE\n\nCurrent Balance: £{buyer.get('balance', 0)}\nTotal Deposited: £{buyer.get('total_deposited', 0)}\nTotal Spent: £{buyer.get('total_spent', 0)}\nLifetime Orders: {buyer.get('lifetime_orders', 0)}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add £10", callback_data="deposit_10"), InlineKeyboardButton("Add £25", callback_data="deposit_25")],
            [InlineKeyboardButton("Add £50", callback_data="deposit_50"), InlineKeyboardButton("Add £100", callback_data="deposit_100")],
            [InlineKeyboardButton("✏️ Custom Amount", callback_data="deposit_custom")],
            [InlineKeyboardButton("Main Menu", callback_data="main_menu")]
        ])
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data == "deposit_custom":
        user["awaiting_deposit_amount"] = True
        await q.edit_message_text("Type the amount you want to add to your balance in GBP.\n\nExample: 35", reply_markup=nav_keyboard("menu_balance"))
        return

    if data.startswith("deposit_"):
        amount = int(data[len("deposit_"):])
        await q.edit_message_text(f"Choose crypto for £{amount} balance deposit:", reply_markup=coin_keyboard(prefix=f"deppay_{amount}"))
        return

    if data.startswith("deppay_"):
        parts = data.split("_", 2)
        amount = int(parts[1])
        coin = parts[2]
        addr = WALLETS.get(coin)
        ref = make_ref(uid)
        pending_orders[ref] = {"user_id": uid, "username": q.from_user.username, "ref": ref, "total_gbp": amount, "coin": coin, "items": {}, "created": time.time(), "status": "awaiting_user_paid", "type": "deposit"}
        remember_pending_for_user(uid, ref)
        save_db()
        msg = (f"DEPOSIT #{ref}\n\nWallet address:\n{addr}\n\nReference ID: {ref}\nPurchase total: £{amount}\nPayment method: {coin}\n\nIMPORTANT\n\n• Only send the selected cryptocurrency to the displayed address.\n\n• Sending another cryptocurrency or sending to the wrong address may permanently lose your funds.\n\n• Your balance will only be updated after payment has been confirmed.\n\nAfter you’ve sent the payment, press “I’ve Paid”.")
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("I’ve Paid", callback_data=f"paid_{ref}")], [InlineKeyboardButton("⬅️ Back", callback_data="menu_balance"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return

    if data == "menu_reviews":
        text = "⭐ REVIEWS\n\n"
        if reviews:
            for r in reviews[-10:]:
                text += f"• {r.get('name','User')}: {r.get('text','')}\n"
        else:
            text += "No reviews yet."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Leave Review", callback_data="leave_review")],[InlineKeyboardButton("Main Menu", callback_data="main_menu")]])
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data == "leave_review":
        user["awaiting_review"] = True
        await q.edit_message_text("Type your review and send it in chat:", reply_markup=nav_keyboard("menu_reviews"))
        return

    if data == "menu_history":
        buyer = ensure_stored_user(uid)
        text = "📜 HISTORY\n\nPurchase History:\n"
        text += "\n".join(f"• {x['ref']} — £{x['amount']} — {x.get('method','')}" for x in buyer.get("purchase_history", [])[-10:]) or "None"
        text += "\n\nDeposit History:\n"
        text += "\n".join(f"• {x['ref']} — £{x['amount']} — {x.get('coin','')}" for x in buyer.get("deposit_history", [])[-10:]) or "None"
        text += "\n\nTransaction History:\n"
        text += "\n".join(f"• {x['ref']} — {x['type']} — £{x['amount']}" for x in buyer.get("transaction_history", [])[-10:]) or "None"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
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
        await q.edit_message_text("💬Write your message for the store owner:\n\n just type your message and send it directly in the chat.", reply_markup=nav_keyboard("menu_contact"))
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
            ensure_stored_user(uid)["secret_phrase"] = text
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

    # custom balance deposit amount
    if user.get("awaiting_deposit_amount"):
        user["awaiting_deposit_amount"] = False
        cleaned = text.replace("£", "").strip()
        try:
            amount = int(float(cleaned))
        except Exception:
            await update.message.reply_text("❌ Invalid amount. Please type a number like 25.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", callback_data="deposit_custom"), InlineKeyboardButton("⬅️ Back", callback_data="menu_balance"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
            return
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be above £0.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", callback_data="deposit_custom"), InlineKeyboardButton("⬅️ Back", callback_data="menu_balance"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
            return
        if amount > 10000:
            await update.message.reply_text("❌ Amount is too high. Please enter £10,000 or less.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", callback_data="deposit_custom"), InlineKeyboardButton("⬅️ Back", callback_data="menu_balance"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
            return
        await update.message.reply_text(f"Choose crypto for £{amount} balance deposit:", reply_markup=coin_keyboard(prefix=f"deppay_{amount}"))
        return

    # review handling
    if user.get("awaiting_review"):
        user["awaiting_review"] = False
        reviews.append({"user_id": uid, "name": update.effective_user.first_name or "User", "text": text[:500], "time": time.time()})
        save_db()
        await update.message.reply_text("✅ Review saved.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("View Reviews", callback_data="menu_reviews")],[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
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
        await update.message.reply_text(f"Reply sent to user {mid}.", reply_markup=nav_keyboard("admin_messages"))
        return

    # default fallback
    await update.message.reply_text("Use /start or the menu buttons.")


# START and ADMIN PANEL commands
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_ban(update, context):
        return
    user = get_user(update.effective_user.id)
    ensure_stored_user(update.effective_user.id)
    if user["secret_phrase"] is None:
        user["awaiting_phrase"] = True
        await update.message.reply_text("👋Welcome to PabloCC Store! This appears to be your first time here\n\n 🔑Please set a phrase-key (between 4–60 characters) that will be used for authentication when you're inactive for more than 10 minutes:")
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
    await update.message.reply_text("ADMIN PANEL", reply_markup=admin_panel_keyboard())


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