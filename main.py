"""
Молиявий Трекер Бот — To'xtamurod uchun
Telegram bot: /meningbugalterimbot
Claude AI (Anthropic) integratsiyasi bilan
"""
import os
import re
import sqlite3
import json
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─── Muhit sozlamalari ────────────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
OWNER_ID   = int(os.environ.get("OWNER_ID") or os.environ.get("EGASI_ID") or "0")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DB_PATH    = "moliya.db"

# ─── Claude AI клиент ─────────────────────────────────────────────────────────
claude_client = None
if ANTHROPIC_API_KEY:
    try:
        import anthropic
        claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
        pass

# ─── Kategoriyalar ────────────────────────────────────────────────────────────
CATS_EXP = [
    "oziq-ovqat", "transport", "uy", "salomatlik",
    "ta'lim", "kiyim", "ko'ngil-ochar", "aloqa",
    "oila", "jamg'arma", "kredit", "boshqa"
]
CATS_INC = [
    "maosh", "freelance", "ijara", "bonus", "boshqa"
]
ICONS = {
    "oziq-ovqat": "🍽", "transport": "🚗", "uy": "🏠",
    "salomatlik": "💊", "ta'lim": "📚", "kiyim": "👕",
    "ko'ngil-ochar": "🎮", "aloqa": "📱", "oila": "👨‍👩‍👧",
    "jamg'arma": "💰", "kredit": "💳", "boshqa": "📦",
    "maosh": "💼", "freelance": "🖥", "ijara": "🏢",
    "bonus": "🎁"
}

# ─── Kategoriya sinonimlar (НЛП парсер учун) ─────────────────────────────────
EXP_SYNONYMS = {
    "озиқ|овқат|еда|продукт|bozor|бозор|нон|гўшт|мева|сабзавот|ош|non|go'sht|meva|sabzavot": "oziq-ovqat",
    "такси|metro|автобус|транспорт|бензин|машина|taxi|avtobus|benzin": "transport",
    "ижара|коммунал|гaz|газ|электр|уй|uy|ijara|kommunal|elektr": "uy",
    "дори|шифохона|дорихона|дорилар|dori|shifoxona|dorixona|salomatlik|соғлиқ": "salomatlik",
    "курс|китоб|мактаб|университет|ta'lim|kurs|kitob|maktab": "ta'lim",
    "кийим|oyoq kiyim|shoes|palto|kiyim": "kiyim",
    "кафе|ресторан|кино|concert|кино|кўнгил|ko'ngil|cafe|restoran|kino": "ko'ngil-ochar",
    "internet|sim|telefon|aloqa|алоқа|интернет|телефон": "aloqa",
    "oila|bola|familia|болалар|оила": "oila",
    "jamg'arma|сакинг|жамғарма|tejash": "jamg'arma",
    "kredit|кредит|qarz|карз|bank|банк": "kredit",
}
INC_SYNONYMS = {
    "maosh|ойлик|зарплата|salary|оклад": "maosh",
    "freelance|фриланс|заказ|loyiha": "freelance",
    "ijara|ижара|аренда|kirish": "ijara",
    "bonus|мукофот|premium": "bonus",
}

# ─── Главная клавиатура ───────────────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ Харажат"), KeyboardButton("📥 Даромад")],
        [KeyboardButton("🤝 Қарз"), KeyboardButton("📊 Ҳисобот")],
        [KeyboardButton("📋 Рўйхат"), KeyboardButton("⚙️ Созлаш")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# ─── Database ─────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tx (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER, type TEXT, amount REAL,
            currency TEXT DEFAULT 'UZS', cat TEXT,
            method TEXT DEFAULT 'naqd', note TEXT,
            dt TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cfg (
            uid INTEGER, key TEXT, val TEXT,
            PRIMARY KEY(uid, key)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS debt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER, dir TEXT, person TEXT,
            amount REAL, currency TEXT DEFAULT 'UZS',
            note TEXT, dt TEXT, closed INTEGER DEFAULT 0
        )
    """)
    con.commit()
    con.close()

def db_cfg(uid: int, key: str, default=None):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT val FROM cfg WHERE uid=? AND key=?", (uid, key))
    row = cur.fetchone()
    con.close()
    return row[0] if row else default

def set_cfg(uid: int, key: str, val):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO cfg(uid,key,val) VALUES(?,?,?)",
                (uid, key, str(val)))
    con.commit()
    con.close()

def add_tx(uid: int, t: dict):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO tx(uid,type,amount,currency,cat,method,note,dt)
        VALUES(?,?,?,?,?,?,?,?)
    """, (
        uid, t["type"], t["amount"], t.get("currency","UZS"),
        t.get("cat","boshqa"), t.get("method","naqd"),
        t.get("note",""), t.get("dt", datetime.now().strftime("%Y-%m-%d %H:%M"))
    ))
    txid = cur.lastrowid
    con.commit()
    con.close()
    return txid

def get_tx(uid: int, period: str = "oy", type_: str = None):
    now = datetime.now()
    if period == "kun":
        since = now.strftime("%Y-%m-%d")
    elif period == "hafta":
        since = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    elif period == "oy":
        since = now.strftime("%Y-%m") + "-01"
    else:
        since = "2000-01-01"
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    if type_:
        cur.execute(
            "SELECT * FROM tx WHERE uid=? AND type=? AND dt>=? ORDER BY dt DESC",
            (uid, type_, since)
        )
    else:
        cur.execute(
            "SELECT * FROM tx WHERE uid=? AND dt>=? ORDER BY dt DESC",
            (uid, since)
        )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def del_tx(uid: int, txid: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM tx WHERE id=? AND uid=?", (txid, uid))
    affected = cur.rowcount
    con.commit()
    con.close()
    return affected > 0

def add_debt(uid: int, d: dict):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO debt(uid,dir,person,amount,currency,note,dt)
        VALUES(?,?,?,?,?,?,?)
    """, (
        uid, d["dir"], d["person"], d["amount"],
        d.get("currency","UZS"), d.get("note",""),
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    con.commit()
    con.close()

def get_debts(uid: int, closed: int = 0):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM debt WHERE uid=? AND closed=? ORDER BY dt DESC",
                (uid, closed))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

def close_debt(uid: int, debt_id: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("UPDATE debt SET closed=1 WHERE id=? AND uid=?", (debt_id, uid))
    affected = cur.rowcount
    con.commit()
    con.close()
    return affected > 0

# ─── Ёрдамчи функциялар ───────────────────────────────────────────────────────
def kurs(uid: int) -> float:
    """UZS/USD almashuv kursi"""
    return float(db_cfg(uid, "kurs", "12800"))

def fmt_sum(amount: float, currency: str = "UZS") -> str:
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.0f} сўм"

def to_uzs(amount: float, currency: str, uid: int) -> float:
    if currency == "USD":
        return amount * kurs(uid)
    return amount

def guess_category(text: str, type_: str) -> str:
    """Матндан категория аниқлаш"""
    text_low = text.lower()
    syns = EXP_SYNONYMS if type_ == "exp" else INC_SYNONYMS
    for pattern, cat in syns.items():
        if re.search(pattern, text_low):
            return cat
    return "boshqa"

def parse_manual(text: str, uid: int) -> dict | None:
    """
    Матндан транзакция парсинг.
    Намуналар:
      50000 oziq-ovqat karta
      150 USD maosh naqd
      -30000 transport
      +500000 maosh
    """
    text = text.strip()
    # Тур аниқлаш (+ даромад, - ёки оддий = харажат)
    if text.startswith("+"):
        type_ = "inc"
        text = text[1:].strip()
    elif text.startswith("-"):
        type_ = "exp"
        text = text[1:].strip()
    else:
        type_ = None  # кейин катагорияга кўра аниқланади

    # Рақам ажратиш
    m = re.match(r"^([\d\s.,]+)", text)
    if not m:
        return None
    num_str = m.group(1).replace(" ", "").replace(",", ".")
    try:
        amount = float(num_str)
    except ValueError:
        return None
    rest = text[m.end():].strip()

    # Валюта аниқлаш
    currency = "UZS"
    if re.search(r"\busd\b|\$|\bdollar\b|\bdollars\b", rest, re.I):
        currency = "USD"
        rest = re.sub(r"\busd\b|\$|\bdollar\b|\bdollars\b", "", rest, flags=re.I).strip()

    # Тўлов усули аниқлаш
    method = "naqd"
    if re.search(r"\bkarta\b|\bcard\b|\bкарта\b|\bplastik\b", rest, re.I):
        method = "karta"
        rest = re.sub(r"\bkarta\b|\bcard\b|\bкарта\b|\bplastik\b", "", rest, flags=re.I).strip()
    elif re.search(r"\bnaqd\b|\bнақд\b|\bcash\b", rest, re.I):
        method = "naqd"
        rest = re.sub(r"\bnaqd\b|\bнақд\b|\bcash\b", "", rest, flags=re.I).strip()

    # Категория аниқлаш
    cat = "boshqa"
    if type_ == "inc":
        cats_list = CATS_INC
    else:
        cats_list = CATS_EXP
        if type_ is None:
            type_ = "exp"

    for c in cats_list:
        if c.lower() in rest.lower():
            cat = c
            rest = re.sub(re.escape(c), "", rest, flags=re.I).strip()
            break

    if cat == "boshqa" and rest:
        cat = guess_category(rest, type_)

    if type_ is None:
        type_ = "exp"

    return {
        "type": type_,
        "amount": amount,
        "currency": currency,
        "cat": cat,
        "method": method,
        "note": rest.strip(),
        "dt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

async def parse_with_claude(text: str, uid: int) -> dict | None:
    """
    Claude AI yordamida tabiiy til parsing.
    Faqat parse_manual() natija bermagan hollarda ishlatiladi.
    """
    if not claude_client:
        return None

    cats_exp_str = ", ".join(CATS_EXP)
    cats_inc_str = ", ".join(CATS_INC)

    prompt = f"""Sen moliyaviy bot uchun matn parser vazifasini bajarasan.
Foydalanuvchi o'zbek yoki rus tilida moliyaviy tranzaksiya haqida yozdi.

Matn: "{text}"

Quyidagilarni JSON formatida chiqar:
- type: "exp" (xarajat) yoki "inc" (daromad)
- amount: raqam (faqat son)
- currency: "UZS" yoki "USD"
- cat: kategoriya (xarajat uchun: {cats_exp_str}; daromad uchun: {cats_inc_str})
- method: "naqd" yoki "karta"
- note: qisqa izoh (ixtiyoriy)

Faqat JSON qaytargın, boshqa hech narsa yo'q.
Agar matn moliyaviy tranzaksiya emas bo'lsa — null qaytargın.

Misol:
- "kechagi ovqatga 45 ming karta to'ladim" → {{"type":"exp","amount":45000,"currency":"UZS","cat":"oziq-ovqat","method":"karta","note":"kechagi ovqat"}}
- "bugun maoshim tushdi 3.5 million" → {{"type":"inc","amount":3500000,"currency":"UZS","cat":"maosh","method":"naqd","note":""}}
- "taksi 15000" → {{"type":"exp","amount":15000,"currency":"UZS","cat":"transport","method":"naqd","note":""}}
"""

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: claude_client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
        )
        result_text = response.content[0].text.strip()

        # JSON парсинг
        if result_text.lower() == "null" or not result_text:
            return None

        # Блок ичидан JSON аниқлаш
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not json_match:
            return None

        data = json.loads(json_match.group())

        # Текшириш
        if not data.get("amount") or data["amount"] <= 0:
            return None
        if data.get("type") not in ("exp", "inc"):
            return None

        # Категорияни тасдиқлаш
        valid_cats = CATS_EXP if data["type"] == "exp" else CATS_INC
        if data.get("cat") not in valid_cats:
            data["cat"] = "boshqa"

        if data.get("method") not in ("naqd", "karta"):
            data["method"] = "naqd"

        data["currency"] = data.get("currency", "UZS").upper()
        if data["currency"] not in ("UZS", "USD"):
            data["currency"] = "UZS"

        data["dt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        data.setdefault("note", "")

        return data

    except Exception:
        return None

def check_limits(uid: int) -> list[str]:
    """Лимит огоҳлантиришлари"""
    warnings = []
    total_limit = float(db_cfg(uid, "limit_total", "0") or "0")
    txs = get_tx(uid, "oy", "exp")

    # Умумий харажат
    total = sum(to_uzs(t["amount"], t["currency"], uid) for t in txs)
    if total_limit > 0 and total >= total_limit * 0.9:
        pct = int(total / total_limit * 100)
        warnings.append(
            f"⚠️ Умумий лимит: {fmt_sum(total)} / {fmt_sum(total_limit)} ({pct}%)"
        )

    # Категория лимитлари
    limits_json = db_cfg(uid, "cat_limits", "{}")
    try:
        cat_limits = json.loads(limits_json)
    except Exception:
        cat_limits = {}

    for cat, lim in cat_limits.items():
        lim = float(lim)
        if lim <= 0:
            continue
        cat_total = sum(
            to_uzs(t["amount"], t["currency"], uid)
            for t in txs if t["cat"] == cat
        )
        if cat_total >= lim * 0.9:
            icon = ICONS.get(cat, "📦")
            pct = int(cat_total / lim * 100)
            warnings.append(
                f"{icon} {cat}: {fmt_sum(cat_total)} / {fmt_sum(lim)} ({pct}%)"
            )
    return warnings

def build_report(txs: list, label: str, uid: int) -> str:
    """Ҳисобот матни (Markdown)"""
    if not txs:
        return f"*{label}* — маълумот йўқ 📭"

    exp_naqd = exp_karta = inc_naqd = inc_karta = 0.0
    cat_totals: dict[str, float] = {}

    for t in txs:
        amt_uzs = to_uzs(t["amount"], t["currency"], uid)
        if t["type"] == "exp":
            if t["method"] == "karta":
                exp_karta += amt_uzs
            else:
                exp_naqd += amt_uzs
            cat_totals[t["cat"]] = cat_totals.get(t["cat"], 0) + amt_uzs
        else:
            if t["method"] == "karta":
                inc_karta += amt_uzs
            else:
                inc_naqd += amt_uzs

    exp_total = exp_naqd + exp_karta
    inc_total = inc_naqd + inc_karta
    balance = inc_total - exp_total

    lines = [f"*📊 {label} ҲИСОБОТИ*\n"]

    # Даромад
    lines.append("💚 *ДАРОМАД*")
    lines.append(f"  💵 Нақд:  {fmt_sum(inc_naqd)}")
    lines.append(f"  💳 Карта: {fmt_sum(inc_karta)}")
    lines.append(f"  📌 Жами:  {fmt_sum(inc_total)}\n")

    # Харажат
    lines.append("❤️ *ХАРАЖАТ*")
    lines.append(f"  💵 Нақд:  {fmt_sum(exp_naqd)}")
    lines.append(f"  💳 Карта: {fmt_sum(exp_karta)}")
    lines.append(f"  📌 Жами:  {fmt_sum(exp_total)}\n")

    # Баланс
    bal_icon = "📈" if balance >= 0 else "📉"
    lines.append(f"{bal_icon} *БАЛАНС: {fmt_sum(balance)}*\n")

    # Категориялар бўйича
    if cat_totals:
        lines.append("📂 *Харажат категориялари:*")
        for cat, total in sorted(cat_totals.items(), key=lambda x: -x[1]):
            icon = ICONS.get(cat, "📦")
            lines.append(f"  {icon} {cat}: {fmt_sum(total)}")

    return "\n".join(lines)

def owner_only(func):
    """Декоратор: фақат OWNER_ID учун"""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("🚫 Ушбу бот шахсий фойдаланиш учун.")
            return
        return await func(update, ctx)
    return wrapper

# ─── Ҳолат ────────────────────────────────────────────────────────────────────
user_states: dict[int, dict] = {}

def get_state(uid: int) -> dict:
    return user_states.get(uid, {})

def set_state(uid: int, step: str, data: dict = None):
    user_states[uid] = {"step": step, "data": data or {}}

def clear_state(uid: int):
    user_states.pop(uid, None)

# ─── Командалар ────────────────────────────────────────────────────────────────
@owner_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name or "To'xtamurod"
    init_db()
    ai_status = "✅ Claude AI уланган" if claude_client else "⚠️ AI улансиз (regex)"
    await update.message.reply_text(
        f"Assalomu alaykum, *{name}*! 👋\n\n"
        "💰 *Молиявий Трекер Бот* — шахсий молия тизими\n"
        f"🤖 {ai_status}\n\n"
        "Тугмаларни ишлатинг ёки эркин матн ёзинг:\n"
        "`Кечаги овқатга 45 минг картадан`\n"
        "`Бугун маошим тушди 3.5 миллион`\n"
        "`Транспортга 15000 нақд`\n\n"
        "`/help` — барча командалар",
        parse_mode="Markdown",
        reply_markup=MAIN_KB,
    )

@owner_only
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *КОМАНДАЛАР РЎЙХАТИ*\n\n"
        "*🤖 AI орқали (эркин матн):*\n"
        "`Кечаги овқатга 45 минг картадан` — харажат\n"
        "`Бугун маошим тушди 3.5 миллион` — даромад\n"
        "`Такси учун 15000 берди` — харажат\n\n"
        "*Тез формат:*\n"
        "`/x 50000 oziq-ovqat karta` — харажат\n"
        "`/d 1500000 maosh` — даромад\n"
        "`/q berdi Otabek 200000` — қарз бердим\n"
        "`/q oldi Sarvar 100000` — қарз олдим\n\n"
        "*Ҳисоботлар:*\n"
        "`/kun` — бугун\n"
        "`/hafta` — сўнгги 7 кун\n"
        "`/oy` — бу ой\n"
        "`/oxirgi` — охирги 10 та\n"
        "`/qarzlar` — қарзлар рўйхати\n\n"
        "*Созлаш:*\n"
        "`/kurs 12800` — USD курс\n"
        "`/limit 5000000` — ойлик лимит\n"
        "`/ochir 5` — #5 ёзувни ўчириш\n"
        "`/sozlash` — созлаш менюси\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

@owner_only
async def cmd_kun(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txs = get_tx(uid, "kun")
    report = build_report(txs, "БУГУН", uid)
    warns = check_limits(uid)
    if warns:
        report += "\n\n⚠️ *ЛИМИТ ОГОҲЛАНТИРИШИ:*\n" + "\n".join(warns)
    await update.message.reply_text(report, parse_mode="Markdown")

@owner_only
async def cmd_hafta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txs = get_tx(uid, "hafta")
    report = build_report(txs, "СЎНгги 7 КУН", uid)
    await update.message.reply_text(report, parse_mode="Markdown")

@owner_only
async def cmd_oy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txs = get_tx(uid, "oy")
    report = build_report(txs, "БУ ОЙ", uid)
    warns = check_limits(uid)
    if warns:
        report += "\n\n⚠️ *ЛИМИТ ОГОҲЛАНТИРИШИ:*\n" + "\n".join(warns)
    await update.message.reply_text(report, parse_mode="Markdown")

@owner_only
async def cmd_oxirgi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM tx WHERE uid=? ORDER BY dt DESC LIMIT 10", (uid,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    if not rows:
        await update.message.reply_text("Ҳали ёзув йўқ 📭")
        return
    lines = ["*📋 ОХИРГИ 10 TA ЁЗУВ*\n"]
    for t in rows:
        icon = "❤️" if t["type"] == "exp" else "💚"
        cat_icon = ICONS.get(t["cat"], "📦")
        method_icon = "💳" if t["method"] == "karta" else "💵"
        lines.append(
            f"{icon} `#{t['id']}` {cat_icon} {t['cat']} — "
            f"{fmt_sum(t['amount'], t['currency'])} {method_icon}\n"
            f"   📅 {t['dt'][:16]}"
            + (f" — {t['note']}" if t["note"] else "")
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@owner_only
async def cmd_ochir(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Ўчириш учун: `/ochir 5` (5 — ёзув ID)\n"
            "ID ни `/oxirgi` дан кўринг.", parse_mode="Markdown"
        )
        return
    txid = int(args[0])
    ok = del_tx(uid, txid)
    if ok:
        await update.message.reply_text(f"✅ #{txid} ўчирилди.")
    else:
        await update.message.reply_text(f"❌ #{txid} топилмади.")

@owner_only
async def cmd_kurs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = ctx.args
    if not args:
        cur_kurs = db_cfg(uid, "kurs", "12800")
        await update.message.reply_text(
            f"Жорий курс: *1 USD = {cur_kurs} сўм*\n\n"
            "Ўзгартириш: `/kurs 13000`", parse_mode="Markdown"
        )
        return
    try:
        new_kurs = float(args[0])
        set_cfg(uid, "kurs", new_kurs)
        await update.message.reply_text(f"✅ Янги курс: 1 USD = {new_kurs:,.0f} сўм")
    except ValueError:
        await update.message.reply_text("❌ Нотўғри рақам. Намуна: `/kurs 12800`", parse_mode="Markdown")

@owner_only
async def cmd_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = ctx.args
    if not args:
        cur_lim = db_cfg(uid, "limit_total", "0")
        await update.message.reply_text(
            f"Жорий лимит: *{fmt_sum(float(cur_lim))}*\n\n"
            "Ойлик лимит ўрнатиш: `/limit 5000000`\n"
            "Категория лимити: `/limit oziq-ovqat 1000000`",
            parse_mode="Markdown"
        )
        return
    if len(args) == 1 and args[0].replace(".", "").isdigit():
        set_cfg(uid, "limit_total", args[0])
        await update.message.reply_text(f"✅ Ойлик лимит: {fmt_sum(float(args[0]))}")
    elif len(args) == 2:
        cat, amount = args[0], args[1]
        all_cats = CATS_EXP + CATS_INC
        if cat not in all_cats:
            await update.message.reply_text(f"❌ Нотўғри категория: {cat}")
            return
        try:
            lim = float(amount)
            limits_json = db_cfg(uid, "cat_limits", "{}")
            cat_limits = json.loads(limits_json)
            cat_limits[cat] = lim
            set_cfg(uid, "cat_limits", json.dumps(cat_limits))
            await update.message.reply_text(f"✅ {cat} лимити: {fmt_sum(lim)}")
        except (ValueError, json.JSONDecodeError):
            await update.message.reply_text("❌ Нотўғри формат")
    else:
        await update.message.reply_text("Намуна: `/limit 5000000` ёки `/limit oziq-ovqat 1000000`", parse_mode="Markdown")

@owner_only
async def cmd_x(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Тез харажат: /x 50000 oziq-ovqat karta"""
    uid = update.effective_user.id
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        set_state(uid, "add_exp")
        await update.message.reply_text(
            "💸 Харажатни ёзинг:\n"
            "`Сумма Категория [karta/naqd] [Изоҳ]`\n\n"
            "Намуна: `50000 oziq-ovqat karta`\n"
            "Валюта: `150 USD transport`",
            parse_mode="Markdown"
        )
        return
    tx = parse_manual(text, uid)
    if tx:
        tx["type"] = "exp"
        txid = add_tx(uid, tx)
        warns = check_limits(uid)
        msg = (
            f"✅ Харажат #{txid} сақланди\n"
            f"{ICONS.get(tx['cat'],'📦')} {tx['cat']} — "
            f"{fmt_sum(tx['amount'], tx['currency'])} "
            f"({'💳 карта' if tx['method']=='karta' else '💵 нақд'})"
        )
        if warns:
            msg += "\n\n⚠️ " + "\n".join(warns)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "❌ Форматни тушунмадим.\nНамуна: `/x 50000 oziq-ovqat karta`",
            parse_mode="Markdown"
        )

@owner_only
async def cmd_d(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Тез даромад: /d 1500000 maosh"""
    uid = update.effective_user.id
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        set_state(uid, "add_inc")
        await update.message.reply_text(
            "💰 Даромадни ёзинг:\n"
            "`Сумма Категория [karta/naqd] [Изоҳ]`\n\n"
            "Намуна: `1500000 maosh naqd`",
            parse_mode="Markdown"
        )
        return
    tx = parse_manual("+" + text, uid)
    if tx:
        tx["type"] = "inc"
        txid = add_tx(uid, tx)
        await update.message.reply_text(
            f"✅ Даромад #{txid} сақланди\n"
            f"{ICONS.get(tx['cat'],'💰')} {tx['cat']} — "
            f"{fmt_sum(tx['amount'], tx['currency'])} "
            f"({'💳 карта' if tx['method']=='karta' else '💵 нақд'})",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "❌ Форматни тушунмадим.\nНамуна: `/d 1500000 maosh`",
            parse_mode="Markdown"
        )

@owner_only
async def cmd_q(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Қарз: /q berdi Otabek 200000   (Отабекка бердим)
          /q oldi Sarvar 100000    (Сарвардан олдим)
    """
    uid = update.effective_user.id
    args = ctx.args
    if len(args) < 3:
        await update.message.reply_text(
            "🤝 *Қарз командаси:*\n"
            "`/q berdi Ismi Summa` — берди (бериш)\n"
            "`/q oldi Ismi Summa` — олди (олиш)\n\n"
            "Намуна: `/q berdi Otabek 200000`",
            parse_mode="Markdown"
        )
        return
    direction = args[0].lower()
    person = args[1]
    try:
        amount = float(args[2])
    except ValueError:
        await update.message.reply_text("❌ Нотўғри сумма")
        return
    currency = "USD" if len(args) > 3 and args[3].upper() == "USD" else "UZS"
    note = " ".join(args[4:]) if len(args) > 4 else ""

    if direction not in ("berdi", "oldi"):
        await update.message.reply_text("❌ `berdi` ёки `oldi` ёзинг", parse_mode="Markdown")
        return

    dir_label = "berdi" if direction == "berdi" else "oldi"
    add_debt(uid, {"dir": dir_label, "person": person, "amount": amount, "currency": currency, "note": note})
    emoji = "🤲" if direction == "berdi" else "💵"
    act = "берди" if direction == "berdi" else "олди"
    await update.message.reply_text(
        f"{emoji} Қарз сақланди:\n{person} га {act}: {fmt_sum(amount, currency)}",
        parse_mode="Markdown"
    )

@owner_only
async def cmd_qarzlar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    debts = get_debts(uid, 0)
    if not debts:
        await update.message.reply_text("✅ Ҳозир қарзингиз йўқ!")
        return
    lines = ["*🤝 ЖОРИЙ ҚАРЗЛАР*\n"]
    berdi_total = oldi_total = 0
    for d in debts:
        emoji = "🤲" if d["dir"] == "berdi" else "💵"
        act = "берди" if d["dir"] == "berdi" else "олди"
        lines.append(
            f"{emoji} `#{d['id']}` *{d['person']}* — {fmt_sum(d['amount'], d['currency'])} ({act})\n"
            f"   📅 {d['dt'][:10]}" + (f" — {d['note']}" if d["note"] else "")
        )
        if d["dir"] == "berdi":
            berdi_total += to_uzs(d["amount"], d["currency"], uid)
        else:
            oldi_total += to_uzs(d["amount"], d["currency"], uid)

    lines.append(f"\n📊 Жами бердим: {fmt_sum(berdi_total)}")
    lines.append(f"📊 Жами олдим: {fmt_sum(oldi_total)}")
    lines.append("\nЁпиш: `/qyop 5` (5 — қарз ID)", )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@owner_only
async def cmd_qyop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Намуна: `/qyop 5`", parse_mode="Markdown")
        return
    ok = close_debt(uid, int(args[0]))
    if ok:
        await update.message.reply_text(f"✅ Қарз #{args[0]} ёпилди.")
    else:
        await update.message.reply_text(f"❌ #{args[0]} топилмади.")

@owner_only
async def cmd_sozlash(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cur_kurs = db_cfg(uid, "kurs", "12800")
    cur_lim = db_cfg(uid, "limit_total", "0")
    ai_status = "✅ Claude AI" if claude_client else "❌ AI улансиз"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💱 Курсни ўзгартириш", callback_data="sozlash:kurs")],
        [InlineKeyboardButton("🎯 Ойлик лимит", callback_data="sozlash:limit")],
        [InlineKeyboardButton("📂 Категория лимитлари", callback_data="sozlash:catlim")],
        [InlineKeyboardButton("🗑 Барча маълумотни тозалаш", callback_data="sozlash:clear")],
    ])
    await update.message.reply_text(
        f"⚙️ *СОЗЛАШ*\n\n"
        f"💱 Жорий курс: 1 USD = {cur_kurs} сўм\n"
        f"🎯 Ойлик лимит: {fmt_sum(float(cur_lim))}\n"
        f"🤖 AI ҳолати: {ai_status}",
        parse_mode="Markdown",
        reply_markup=kb,
    )

# ─── Inline callback ──────────────────────────────────────────────────────────
@owner_only
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data == "hisobot:kun":
        txs = get_tx(uid, "kun")
        rpt = build_report(txs, "БУГУН", uid)
        await q.edit_message_text(rpt, parse_mode="Markdown")
    elif data == "hisobot:hafta":
        txs = get_tx(uid, "hafta")
        rpt = build_report(txs, "СЎНгги 7 КУН", uid)
        await q.edit_message_text(rpt, parse_mode="Markdown")
    elif data == "hisobot:oy":
        txs = get_tx(uid, "oy")
        rpt = build_report(txs, "БУ ОЙ", uid)
        await q.edit_message_text(rpt, parse_mode="Markdown")
    elif data.startswith("cat_exp:"):
        cat = data.split(":")[1]
        state = get_state(uid)
        state["data"]["cat"] = cat
        set_state(uid, "choose_method_exp", state["data"])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💵 Нақд", callback_data="method:naqd"),
             InlineKeyboardButton("💳 Карта", callback_data="method:karta")],
        ])
        await q.edit_message_text(
            f"✅ Категория: *{ICONS.get(cat,'')} {cat}*\n\nТўлов усулини танланг:",
            parse_mode="Markdown", reply_markup=kb
        )
    elif data.startswith("cat_inc:"):
        cat = data.split(":")[1]
        state = get_state(uid)
        state["data"]["cat"] = cat
        set_state(uid, "choose_method_inc", state["data"])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💵 Нақд", callback_data="method:naqd"),
             InlineKeyboardButton("💳 Карта", callback_data="method:karta")],
        ])
        await q.edit_message_text(
            f"✅ Категория: *{ICONS.get(cat,'')} {cat}*\n\nТўлов усулини танланг:",
            parse_mode="Markdown", reply_markup=kb
        )
    elif data.startswith("method:"):
        method = data.split(":")[1]
        state = get_state(uid)
        d = state.get("data", {})
        d["method"] = method
        step = state.get("step", "")
        type_ = "exp" if "exp" in step else "inc"
        d["type"] = type_
        txid = add_tx(uid, d)
        clear_state(uid)
        warns = check_limits(uid) if type_ == "exp" else []
        icon = ICONS.get(d.get("cat","boshqa"), "📦")
        msg = (
            f"✅ Сақланди #{txid}\n"
            f"{icon} {d.get('cat','boshqa')} — "
            f"{fmt_sum(d.get('amount',0), d.get('currency','UZS'))} "
            f"({'💳' if method=='karta' else '💵'})"
        )
        if warns:
            msg += "\n\n⚠️ " + "\n".join(warns)
        await q.edit_message_text(msg, parse_mode="Markdown")
    elif data.startswith("sozlash:"):
        action = data.split(":")[1]
        if action == "kurs":
            set_state(uid, "input_kurs")
            await q.edit_message_text(
                "💱 Янги курсни ёзинг:\nНамуна: `12800`", parse_mode="Markdown"
            )
        elif action == "limit":
            set_state(uid, "input_limit")
            await q.edit_message_text(
                "🎯 Ойлик лимитни ёзинг (сўмда):\nНамуна: `5000000`", parse_mode="Markdown"
            )
        elif action == "catlim":
            lines = ["📂 *Категория лимитлари ўрнатиш:*\n"]
            lines.append("Командани ёзинг:")
            lines.append("`/limit oziq-ovqat 1000000`")
            lines.append("\nМавжуд категориялар:")
            lines.append(", ".join(CATS_EXP))
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown")
        elif action == "clear":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Ҳа, ўчир", callback_data="sozlash:clear_yes"),
                 InlineKeyboardButton("❌ Бекор", callback_data="sozlash:cancel")],
            ])
            await q.edit_message_text(
                "⚠️ *Барча маълумотлар ўчирилади!*\nИшончингиз комилми?",
                parse_mode="Markdown", reply_markup=kb
            )
        elif action == "clear_yes":
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("DELETE FROM tx WHERE uid=?", (uid,))
            cur.execute("DELETE FROM debt WHERE uid=?", (uid,))
            con.commit()
            con.close()
            await q.edit_message_text("✅ Барча маълумотлар ўчирилди.")
        elif action == "cancel":
            await q.edit_message_text("❌ Бекор қилинди.")

# ─── Матн ────────────────────────────────────────────────────────────────────
@owner_only
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    state = get_state(uid)
    step = state.get("step")

    # Тугмалар
    if text == "➕ Харажат":
        set_state(uid, "input_amount_exp")
        await update.message.reply_text(
            "💸 Харажатни эркин ёзинг:\n\n"
            "Намуналар:\n"
            "`Бозордан нон олдим 25000`\n"
            "`Такси учун 12000 карта`\n"
            "`50000 oziq-ovqat karta`",
            parse_mode="Markdown"
        )
        return
    elif text == "📥 Даромад":
        set_state(uid, "input_amount_inc")
        await update.message.reply_text(
            "💰 Даромадни эркин ёзинг:\n\n"
            "Намуналар:\n"
            "`Бугун маошим тушди 3.5 миллион`\n"
            "`Фриланс иш учун 500 доллар`\n"
            "`+1500000 maosh naqd`",
            parse_mode="Markdown"
        )
        return
    elif text == "🤝 Қарз":
        await update.message.reply_text(
            "🤝 *Қарз командаси:*\n\n"
            "`/q berdi Ismi Summa` — берди\n"
            "`/q oldi Ismi Summa` — олди\n"
            "`/qarzlar` — рўйхат\n"
            "`/qyop 5` — ёпиш (ID)",
            parse_mode="Markdown"
        )
        return
    elif text == "📊 Ҳисобот":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Бугун", callback_data="hisobot:kun"),
             InlineKeyboardButton("📆 Ҳафта", callback_data="hisobot:hafta"),
             InlineKeyboardButton("🗓 Ой", callback_data="hisobot:oy")],
        ])
        await update.message.reply_text("Давр танланг:", reply_markup=kb)
        return
    elif text == "📋 Рўйхат":
        await cmd_oxirgi(update, ctx)
        return
    elif text == "⚙️ Созлаш":
        await cmd_sozlash(update, ctx)
        return

    # Ҳолат машинаси
    if step == "input_kurs":
        try:
            new_kurs = float(text.replace(",", "."))
            set_cfg(uid, "kurs", new_kurs)
            clear_state(uid)
            await update.message.reply_text(f"✅ Курс янгиланди: 1 USD = {new_kurs:,.0f} сўм")
        except ValueError:
            await update.message.reply_text("❌ Рақам ёзинг, намуна: `12800`", parse_mode="Markdown")
        return
    elif step == "input_limit":
        try:
            lim = float(text.replace(",", ".").replace(" ", ""))
            set_cfg(uid, "limit_total", lim)
            clear_state(uid)
            await update.message.reply_text(f"✅ Лимит: {fmt_sum(lim)}")
        except ValueError:
            await update.message.reply_text("❌ Рақам ёзинг")
        return
    elif step in ("input_amount_exp", "input_amount_inc", "add_exp", "add_inc"):
        # Аввал regex парсинг
        prefix = "+" if step in ("input_amount_inc", "add_inc") else ""
        tx = parse_manual(prefix + text, uid)

        # Regex ишламаса — Claude AI ишлатиш
        if not tx or tx.get("amount", 0) <= 0:
            if claude_client:
                wait_msg = await update.message.reply_text("🤖 AI таҳлил қилмоқда...")
                tx = await parse_with_claude(text, uid)
                # Тур аниқлаш (харажат/даромад тугмасига қараб)
                if tx and step in ("input_amount_inc", "add_inc"):
                    tx["type"] = "inc"
                elif tx and step in ("input_amount_exp", "add_exp"):
                    tx["type"] = "exp"
                try:
                    await wait_msg.delete()
                except Exception:
                    pass

        if tx and tx.get("amount", 0) > 0:
            # Категория аниқланмаган бўлса, инлайн танлов
            type_ = tx.get("type", "exp")
            if tx.get("cat") == "boshqa":
                cats = CATS_EXP if type_ == "exp" else CATS_INC
                set_state(uid, f"choose_cat_{type_}", {**tx})
                rows = []
                for i in range(0, len(cats), 3):
                    row = [InlineKeyboardButton(
                        f"{ICONS.get(c,'')} {c}", callback_data=f"cat_{type_}:{c}"
                    ) for c in cats[i:i+3]]
                    rows.append(row)
                await update.message.reply_text(
                    f"Категорияни танланг ({fmt_sum(tx['amount'], tx['currency'])}):",
                    reply_markup=InlineKeyboardMarkup(rows)
                )
            else:
                txid = add_tx(uid, tx)
                clear_state(uid)
                warns = check_limits(uid) if type_ == "exp" else []
                icon = ICONS.get(tx["cat"], "📦")
                type_label = "Харажат" if type_ == "exp" else "Даромад"
                msg = (
                    f"✅ {type_label} #{txid} сақланди\n"
                    f"{icon} {tx['cat']} — "
                    f"{fmt_sum(tx['amount'], tx['currency'])} "
                    f"({'💳 карта' if tx['method']=='karta' else '💵 нақд'})"
                )
                if tx.get("note"):
                    msg += f"\n📝 {tx['note']}"
                if warns:
                    msg += "\n\n⚠️ " + "\n".join(warns)
                await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "❓ Тушунмадим. Намуна:\n"
                "`Бозордан нон олдим 25000`\n"
                "`50000 oziq-ovqat karta`\n"
                "ёки `/help` кўринг.", parse_mode="Markdown"
            )
        return

    # Бўш ҳолатда — автоматик парсинг (regex + Claude AI)
    tx = parse_manual(text, uid)

    if not tx or tx.get("amount", 0) <= 0:
        if claude_client:
            wait_msg = await update.message.reply_text("🤖 AI таҳлил қилмоқда...")
            tx = await parse_with_claude(text, uid)
            try:
                await wait_msg.delete()
            except Exception:
                pass

    if tx and tx.get("amount", 0) > 0:
        txid = add_tx(uid, tx)
        warns = check_limits(uid) if tx["type"] == "exp" else []
        icon = ICONS.get(tx["cat"], "📦")
        type_label = "Харажат" if tx["type"] == "exp" else "Даромад"
        msg = (
            f"✅ {type_label} #{txid}\n"
            f"{icon} {tx['cat']} — "
            f"{fmt_sum(tx['amount'], tx['currency'])} "
            f"({'💳 карта' if tx['method']=='karta' else '💵 нақд'})"
        )
        if tx.get("note"):
            msg += f"\n📝 {tx['note']}"
        if warns:
            msg += "\n\n⚠️ " + "\n".join(warns)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "❓ Тушунмадим.\n\n"
            "Эркин матн:\n"
            "`Кечаги овқатга 45 минг картадан`\n"
            "`Бугун маошим тушди 3.5 миллион`\n\n"
            "Тез формат:\n"
            "`50000 oziq-ovqat karta`\n"
            "`+1500000 maosh`\n\n"
            "Ёрдам: `/help`",
            parse_mode="Markdown"
        )

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    # Replit ни ухлатмаслик
    try:
        from keep_alive import keep_alive
        keep_alive()
    except Exception:
        pass

    init_db()
    ai_info = "Claude AI УЛАНГАН ✅" if claude_client else "AI улансиз (regex парсер) ⚠️"
    print(f"🤖 Молиявий Трекер Бот ишлаяпти... [{ai_info}]")

    app = Application.builder().token(BOT_TOKEN).build()

    # Командалар
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("kun", cmd_kun))
    app.add_handler(CommandHandler("hafta", cmd_hafta))
    app.add_handler(CommandHandler("oy", cmd_oy))
    app.add_handler(CommandHandler("oxirgi", cmd_oxirgi))
    app.add_handler(CommandHandler("ochir", cmd_ochir))
    app.add_handler(CommandHandler("kurs", cmd_kurs))
    app.add_handler(CommandHandler("limit", cmd_limit))
    app.add_handler(CommandHandler("sozlash", cmd_sozlash))
    app.add_handler(CommandHandler("x", cmd_x))
    app.add_handler(CommandHandler("d", cmd_d))
    app.add_handler(CommandHandler("q", cmd_q))
    app.add_handler(CommandHandler("qarzlar", cmd_qarzlar))
    app.add_handler(CommandHandler("qyop", cmd_qyop))

    # Callback ва матн
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
