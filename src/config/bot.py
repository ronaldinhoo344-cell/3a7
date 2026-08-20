# =============================================================
#   BOT.PY - بوت البنك في ملف واحد (كامل)
#   التثبيت:  pip install -r requirements.txt
#   التشغيل:  python bot.py
#   التوكن:   ملف bot.env بجانب هذا الملف
# =============================================================
import asyncio
import io
import os
import random
import time
import threading
import traceback
from datetime import datetime

import aiosqlite
import arabic_reshaper
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, View
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFilter, ImageFont
# ================== py ==================


def _load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = value


_load_env("bot.env")
_load_env("../bot.env")

TOKEN = os.getenv("DISCORD_TOKEN", "")

PREFIX = "-"
CURRENCY = "💰"

DAILY_AMOUNT = 500
WORK_MIN = 100
WORK_MAX = 300
BEG_MIN = 1
BEG_MAX = 60
GAMBLE_MULTIPLIER = 2
GAMBLE_DIVISOR = 10
GAMBLE_MIN_CHANCE = 5
GAMBLE_EDGE = 0.95
ROB_CHANCE = 0.50
ROB_STEAL_PERCENT = 0.20
ROB_FAIL_FINE_PERCENT = 0.15

TRANSFER_FEE = 0.05
DEPOSIT_INTEREST_RATE = 0.001
INTEREST_INTERVAL_HOURS = 1

LOAN_INTEREST = 0.10
LOAN_MAX_MULTIPLIER = 5

COLOR = 0x2ECC71

SHOP_ITEMS = [
    {"id": "vip", "name": "عضو VIP", "price": 10000, "type": "role", "role_id": 0, "desc": "رتبة VIP بالسيرفر", "emoji": "👑"},
    {"id": "lottery", "name": "تذكرة يانصيب", "price": 500, "type": "item", "desc": "شغّلها بـ -يانصيب (فرصة 10% تربح 10 أضعاف)", "emoji": "🎟️"},
    {"id": "boost", "name": "مضاعف راتب", "price": 2000, "type": "item", "desc": "الراتب اليومي القادم x2", "emoji": "⚡"},
]

# ================== py ==================
def parse_amount(s):
    try:
        return int(str(s).replace(",", "").replace("،", "").strip())
    except (ValueError, AttributeError):
        return 0

# ================== py ==================

DB_PATH = "bank.db"


async def get_connection():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db():
    conn = await get_connection()
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            wallet INTEGER DEFAULT 0,
            bank INTEGER DEFAULT 0,
            loan INTEGER DEFAULT 0,
            last_daily TEXT
        )"""
    )
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item_id TEXT,
            quantity INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, item_id)
        )"""
    )
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS guilds (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER
        )"""
    )
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS marriages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1 INTEGER NOT NULL,
            user2 INTEGER NOT NULL,
            mahr INTEGER DEFAULT 0,
            married_at TEXT NOT NULL
        )"""
    )
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS divorce_blocks (
            user1 INTEGER NOT NULL,
            user2 INTEGER NOT NULL,
            blocked_at TEXT NOT NULL,
            PRIMARY KEY (user1, user2)
        )"""
    )
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            amount INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            by_admin INTEGER NOT NULL
        )"""
    )
    await conn.commit()
    await conn.close()


async def get_user(conn, user_id):
    await conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    await conn.commit()
    cur = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return await cur.fetchone()


async def update_wallet(conn, user_id, delta):
    await conn.execute(
        "UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (delta, user_id)
    )
    await conn.commit()


async def update_bank(conn, user_id, delta):
    await conn.execute(
        "UPDATE users SET bank = bank + ? WHERE user_id = ?", (delta, user_id)
    )
    await conn.commit()


async def add_item(conn, user_id, item_id, qty=1):
    await conn.execute(
        """INSERT INTO inventory (user_id, item_id, quantity) VALUES (?, ?, ?)
           ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + ?""",
        (user_id, item_id, qty, qty),
    )
    await conn.commit()


async def remove_item(conn, user_id, item_id, qty=1):
    await conn.execute(
        "UPDATE inventory SET quantity = quantity - ? WHERE user_id = ? AND item_id = ?",
        (qty, user_id, item_id),
    )
    await conn.execute(
        "DELETE FROM inventory WHERE user_id = ? AND item_id = ? AND quantity <= 0",
        (user_id, item_id),
    )
    await conn.commit()


async def get_inventory(conn, user_id):
    cur = await conn.execute(
        "SELECT * FROM inventory WHERE user_id = ?", (user_id,)
    )
    return await cur.fetchall()


async def get_guild_channel(conn, guild_id):
    cur = await conn.execute(
        "SELECT channel_id FROM guilds WHERE guild_id = ?", (guild_id,)
    )
    row = await cur.fetchone()
    return row["channel_id"] if row else None


async def get_marriage(conn, user_id):
    cur = await conn.execute(
        "SELECT * FROM marriages WHERE user1 = ? OR user2 = ?", (user_id, user_id)
    )
    return await cur.fetchone()


async def create_marriage(conn, user1, user2, mahr):
    cur = await conn.execute(
        "INSERT INTO marriages (user1, user2, mahr, married_at) VALUES (?, ?, ?, ?)",
        (user1, user2, mahr, datetime.utcnow().strftime("%Y-%m-%d %H:%M")),
    )
    await conn.commit()
    return cur.lastrowid


async def delete_marriage(conn, user_id):
    await conn.execute(
        "DELETE FROM marriages WHERE user1 = ? OR user2 = ?", (user_id, user_id)
    )
    await conn.commit()


async def add_divorce_block(conn, user1, user2):
    a, b = sorted((user1, user2))
    await conn.execute(
        "INSERT OR IGNORE INTO divorce_blocks (user1, user2, blocked_at) VALUES (?, ?, ?)",
        (a, b, datetime.utcnow().strftime("%Y-%m-%d %H:%M")),
    )
    await conn.commit()


async def is_divorce_blocked(conn, user1, user2):
    a, b = sorted((user1, user2))
    cur = await conn.execute(
        "SELECT 1 FROM divorce_blocks WHERE user1 = ? AND user2 = ?", (a, b)
    )
    return await cur.fetchone() is not None


async def remove_divorce_block(conn, user1, user2):
    a, b = sorted((user1, user2))
    await conn.execute(
        "DELETE FROM divorce_blocks WHERE user1 = ? AND user2 = ?", (a, b)
    )
    await conn.commit()


async def reset_user_numbers(conn, user_id):
    await conn.execute(
        "UPDATE users SET wallet = 0, bank = 0, loan = 0 WHERE user_id = ?", (user_id,)
    )
    await conn.commit()


async def add_violation(conn, user_id, reason, amount, by_admin):
    await conn.execute(
        "INSERT INTO violations (user_id, reason, amount, created_at, by_admin) VALUES (?, ?, ?, ?, ?)",
        (user_id, reason, amount, datetime.utcnow().strftime("%Y-%m-%d %H:%M"), by_admin),
    )
    await conn.commit()


async def get_violations(conn, user_id, limit=30):
    cur = await conn.execute(
        "SELECT * FROM violations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    return await cur.fetchall()


async def clear_violations(conn, user_id):
    await conn.execute("DELETE FROM violations WHERE user_id = ?", (user_id,))
    await conn.commit()

# ================== py ==================


CACHE = {}
LAST_RESTORE = {}


def remember(msg, embed=None, file_bytes=None, filename=None, text=None):
    CACHE[msg.id] = {
        "ch": msg.channel.id,
        "embed": embed,
        "bytes": file_bytes,
        "name": filename,
        "text": text,
        "t": time.time(),
    }


def cache_from_msg(msg, embed=None, file=None, text=None):
    if not (embed or file):
        return
    fb = None
    if file:
        try:
            file.fp.seek(0)
            fb = file.fp.read()
        except Exception:
            fb = None
    remember(msg, embed, fb, file.filename if file else None, text)


async def safe_send(ctx, embed=None, file=None, text=None, view=None):
    msg = await ctx.reply(content=text, embed=embed, file=file, view=view)
    cache_from_msg(msg, embed, file, text)
    return msg


def find_cached(message_id):
    return CACHE.get(message_id)


async def restore(message):
    info = find_cached(message.id)
    if not info:
        return False
    now = time.time()
    if now - info["t"] > 600:
        return False
    ch = message.channel
    last = LAST_RESTORE.get(info["ch"], 0)
    if now - last < 15:
        return False
    LAST_RESTORE[info["ch"]] = now
    try:
        file = None
        if info["bytes"]:
            file = discord.File(BytesIO(info["bytes"]), info["name"] or "card.png")
        await ch.send(content=info["text"], embed=info["embed"], file=file)
        return True
    except Exception:
        return False

# ================== py ==================



SCALE = 2


def S(v):
    return int(v * SCALE)


FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/trado.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

FONT_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/tahomabd.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansArabic-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

FONT_EMOJI_CANDIDATES = [
    "C:/Windows/Fonts/seguiemj.ttf",
    "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
    "/usr/share/fonts/truetype/symbola/Symbola.ttf",
]

_PREFIX = os.environ.get("PREFIX", "")
if _PREFIX:
    FONT_CANDIDATES += [
        f"{_PREFIX}/share/fonts/arabic.ttf",
        f"{_PREFIX}/share/fonts/noto/NotoSansArabic-Regular.ttf",
        f"{_PREFIX}/share/fonts/noto/NotoSansArabic-Regular.otf",
        f"{_PREFIX}/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    ]
    FONT_BOLD_CANDIDATES += [
        f"{_PREFIX}/share/fonts/arabic-bold.ttf",
        f"{_PREFIX}/share/fonts/noto/NotoSansArabic-Bold.ttf",
        f"{_PREFIX}/share/fonts/noto/NotoSansArabic-Bold.otf",
        f"{_PREFIX}/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    ]

GOLD = (255, 215, 0)
GOLD_D = (200, 160, 0)
WHITE = (255, 255, 255)
SOFT = (180, 195, 215)
BG_TOP = (28, 42, 66)
BG_BOT = (9, 13, 21)


def ar(text):
    return get_display(arabic_reshaper.reshape(text))


def load_font(size, bold=False):
    for path in (FONT_BOLD_CANDIDATES if bold else FONT_CANDIDATES):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def emoji_font(size):
    for path in FONT_EMOJI_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return load_font(size)


def vertical_gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=color)
    return img


def rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return mask


def draw_glow_text(img, xy, text, font, fill=WHITE, glow_color=(255, 255, 255), radius=10, alpha=150):
    x, y = int(xy[0]), int(xy[1])
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    pad = radius * 3
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    dl.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=glow_color + (alpha,))
    glow = layer.filter(ImageFilter.GaussianBlur(radius))
    img.paste(glow, (x - pad, y - pad), glow)
    d.text((x, y), text, font=font, fill=fill)


def extract_colors(image_bytes, k=3):
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        img = img.resize((120, 120))
        q = img.quantize(colors=k)
        palette = q.getpalette()
        counts = {}
        for p in q.getdata():
            counts[p] = counts.get(p, 0) + 1
        top = sorted(counts, key=counts.get, reverse=True)[:k]
        return [tuple(palette[i * 3:i * 3 + 3]) for i in top]
    except Exception:
        return [(28, 42, 66), (9, 13, 21)]


def make_coin(path="assets/coin.png"):
    size = S(256)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([S(8), S(8), size - S(8), size - S(8)], fill=(255, 200, 30), outline=(180, 130, 0), width=S(10))
    d.ellipse([S(34), S(34), size - S(34), size - S(34)], fill=(255, 220, 70), outline=(220, 170, 20), width=S(6))
    f = emoji_font(S(120))
    box = d.textbbox((0, 0), "💰", font=f)
    x = (size - (box[2] - box[0])) / 2 - box[0]
    y = (size - (box[3] - box[1])) / 2 - box[1]
    d.text((x, y), "💰", font=f, fill=(0, 0, 0, 0), embedded_color=True)
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    img.save(path)


def make_banner(path, title, subtitle, c1, c2, filename_emoji="💳"):
    w, h = S(1000), S(300)
    img = vertical_gradient(w, h, c1, c2)
    d = ImageDraw.Draw(img)
    d.line([(0, S(90)), (w, S(90))], fill=GOLD, width=S(4))
    d.line([(0, S(230)), (w, S(230))], fill=GOLD, width=S(4))
    f_title = load_font(S(72), bold=True)
    f_sub = load_font(S(36))
    f_emo = emoji_font(S(72))
    tw = d.textbbox((0, 0), ar(title), font=f_title)
    x = (w - (tw[2] - tw[0])) / 2 - tw[0]
    d.text((x, S(112)), ar(title), font=f_title, fill=GOLD)
    ebox = d.textbbox((0, 0), filename_emoji, font=f_emo)
    ex = (w - (ebox[2] - ebox[0])) / 2 - ebox[0]
    d.text((ex, S(20)), filename_emoji, font=f_emo, fill=WHITE, embedded_color=True)
    sw = d.textbbox((0, 0), ar(subtitle), font=f_sub)
    sx = (w - (sw[2] - sw[0])) / 2 - sw[0]
    d.text((sx, S(240)), ar(subtitle), font=f_sub, fill=SOFT)
    img.save(path)


PURPLE_TOP = (58, 24, 102)
PURPLE_BOT = (15, 7, 33)
GOLD_LINE = (190, 150, 40)
GOLD_DIM = (120, 88, 20)


def render_card(name, avatar_bytes, wallet, bank, loan=0, total=None, icon_bytes=None, colors=None):
    W, H = S(850), S(440)
    base_img = vertical_gradient(W, H, PURPLE_TOP, PURPLE_BOT).convert("RGBA")
    mask = rounded_mask((W, H), S(30))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.paste(base_img, (0, 0), mask)
    d = ImageDraw.Draw(img)

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W // 2 - S(360), S(60), W // 2 + S(360), H + S(80)], fill=(255, 215, 0, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(S(55)))
    img.paste(glow, (0, 0), glow)

    d.rounded_rectangle([S(10), S(10), W - S(10), H - S(10)], radius=S(28), outline=GOLD, width=S(4))
    d.rounded_rectangle([S(20), S(20), W - S(20), H - S(20)], radius=S(22), outline=GOLD_DIM, width=S(2))

    yline = S(66)
    d.line([(S(52), yline), (W // 2 - S(48), yline)], fill=GOLD_LINE, width=S(2))
    d.line([(W // 2 + S(48), yline), (W - S(52), yline)], fill=GOLD_LINE, width=S(2))
    r = S(7)
    d.polygon([(W // 2, yline - r), (W // 2 + r, yline), (W // 2, yline + r), (W // 2 - r, yline)], fill=GOLD)

    if icon_bytes:
        try:
            lsize = S(110)
            logo = Image.open(BytesIO(icon_bytes)).convert("RGBA").resize((lsize, lsize))
            lx, ly = W - S(52) - lsize, S(118)
            img.paste(logo, (lx, ly), rounded_mask((lsize, lsize), lsize // 2))
            d.ellipse([lx - S(4), ly - S(4), lx + lsize + S(4), ly + lsize + S(4)], outline=GOLD, width=S(4))
        except Exception:
            pass

    f_name = load_font(S(46), bold=True)
    f_sub = load_font(S(24))
    f_big = load_font(S(52), bold=True)
    f_mid = load_font(S(28), bold=True)
    f_small = load_font(S(20))

    tx = S(240)
    max_w = W - S(240) - S(170)
    while len(name) > 1 and d.textlength(ar(name), font=f_name) > max_w:
        name = name[:-1]
    if len(name) <= 1:
        name = "؟"
    d.text((tx, S(98)), ar(name), font=f_name, fill=WHITE)
    d.text((tx, S(156)), ar("بطاقة البنك المصرفي"), font=f_sub, fill=GOLD)
    d.text((tx, S(196)), ar("الرصيد المتوفر"), font=f_sub, fill=SOFT)
    draw_glow_text(img, (tx, S(222)), f"{wallet + bank:,}", font=f_big, fill=GOLD, glow_color=(255, 230, 130), radius=S(10))

    if avatar_bytes:
        try:
            av_size = S(150)
            av = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((av_size, av_size))
            ax, ay = S(52), S(118)
            img.paste(av, (ax, ay), rounded_mask((av_size, av_size), av_size // 2))
            d.ellipse([ax - S(5), ay - S(5), ax + av_size + S(5), ay + av_size + S(5)], outline=GOLD, width=S(5))
            d.ellipse([ax - S(12), ay - S(12), ax + av_size + S(12), ay + av_size + S(12)], outline=GOLD_DIM, width=S(2))
        except Exception:
            pass

    def stat_box(x, title, amount):
        d.rounded_rectangle(
            [x, S(300), x + S(330), S(388)], radius=S(16), fill=(0, 0, 0, 70), outline=GOLD_LINE, width=S(2)
        )
        d.text((x + S(20), S(312)), ar(title), font=f_sub, fill=SOFT)
        draw_glow_text(img, (x + S(20), S(342)), amount, font=f_mid, fill=WHITE, radius=S(6))

    stat_box(S(52), "المحفظة", f"{wallet:,}")
    stat_box(S(414), "البنك", f"{bank:,}")

    if total is None:
        total = wallet + bank
    total_txt = ar(f"الإجمالي: {total:,}")
    tb = d.textbbox((0, 0), total_txt, font=f_small)
    d.text((W // 2 - (tb[2] - tb[0]) / 2 - tb[0], S(398)), total_txt, font=f_small, fill=GOLD)

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def render_marriage_card(name1, name2, avatar1_bytes, avatar2_bytes, mahr, date_str):
    W, H = S(850), S(500)
    top = (102, 34, 78)
    bot = (26, 10, 34)
    base_img = vertical_gradient(W, H, top, bot).convert("RGBA")
    mask = rounded_mask((W, H), S(30))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.paste(base_img, (0, 0), mask)
    d = ImageDraw.Draw(img)

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W // 2 - S(340), S(40), W // 2 + S(340), H + S(60)], fill=(255, 110, 160, 42))
    glow = glow.filter(ImageFilter.GaussianBlur(S(55)))
    img.paste(glow, (0, 0), glow)

    d.rounded_rectangle([S(10), S(10), W - S(10), H - S(10)], radius=S(28), outline=GOLD, width=S(4))
    d.rounded_rectangle([S(20), S(20), W - S(20), H - S(20)], radius=S(22), outline=GOLD_DIM, width=S(2))

    yline = S(64)
    d.line([(S(52), yline), (W // 2 - S(48), yline)], fill=GOLD_LINE, width=S(2))
    d.line([(W // 2 + S(48), yline), (W - S(52), yline)], fill=GOLD_LINE, width=S(2))
    r = S(7)
    d.polygon([(W // 2, yline - r), (W // 2 + r, yline), (W // 2, yline + r), (W // 2 - r, yline)], fill=GOLD)

    f_title = load_font(S(46), bold=True)
    f_name = load_font(S(30), bold=True)
    f_info = load_font(S(24))
    f_emo = emoji_font(S(84))

    title = ar("💍 عقد الزواج 💍")
    tb = d.textbbox((0, 0), title, font=f_title)
    draw_glow_text(
        img,
        (W // 2 - (tb[2] - tb[0]) / 2 - tb[0], S(88)),
        title,
        font=f_title,
        fill=GOLD,
        glow_color=(255, 200, 220),
        radius=S(9),
    )

    av_size = S(170)
    if avatar1_bytes:
        try:
            av = Image.open(BytesIO(avatar1_bytes)).convert("RGBA").resize((av_size, av_size))
            ax, ay = S(120), S(180)
            img.paste(av, (ax, ay), rounded_mask((av_size, av_size), av_size // 2))
            d.ellipse([ax - S(5), ay - S(5), ax + av_size + S(5), ay + av_size + S(5)], outline=GOLD, width=S(5))
            d.ellipse([ax - S(12), ay - S(12), ax + av_size + S(12), ay + av_size + S(12)], outline=GOLD_DIM, width=S(2))
        except Exception:
            pass
    if avatar2_bytes:
        try:
            av = Image.open(BytesIO(avatar2_bytes)).convert("RGBA").resize((av_size, av_size))
            ax, ay = W - S(120) - av_size, S(180)
            img.paste(av, (ax, ay), rounded_mask((av_size, av_size), av_size // 2))
            d.ellipse([ax - S(5), ay - S(5), ax + av_size + S(5), ay + av_size + S(5)], outline=GOLD, width=S(5))
            d.ellipse([ax - S(12), ay - S(12), ax + av_size + S(12), ay + av_size + S(12)], outline=GOLD_DIM, width=S(2))
        except Exception:
            pass

    heart_x = W // 2
    heart_y = S(262)
    hb = d.textbbox((0, 0), "❤️", font=f_emo)
    d.text(
        (heart_x - (hb[2] - hb[0]) / 2 - hb[0], heart_y - (hb[3] - hb[1]) / 2 - hb[1]),
        "❤️",
        font=f_emo,
        fill=WHITE,
        embedded_color=True,
    )

    def side_text(text, font, y, cx, fill):
        b = d.textbbox((0, 0), ar(text), font=font)
        d.text((cx - (b[2] - b[0]) / 2 - b[0], y), ar(text), font=font, fill=fill)

    def trunc(name, max_w, font):
        while len(name) > 1 and d.textlength(ar(name), font=font) > max_w:
            name = name[:-1]
        return name if name else "؟"

    f_name1 = load_font(S(28), bold=True)
    side_text(trunc(name1, S(280), f_name1), f_name1, S(372), S(205), WHITE)
    side_text(trunc(name2, S(280), f_name1), f_name1, S(372), W - S(205), WHITE)

    d.rounded_rectangle([S(80), S(424), W - S(80), S(474)], radius=S(16), fill=(0, 0, 0, 70), outline=GOLD_LINE, width=S(2))
    info = f"المهر: {CURRENCY} {mahr:,}   •   تاريخ الزواج: {date_str}"
    ib = d.textbbox((0, 0), ar(info), font=f_info)
    d.text(
        (W // 2 - (ib[2] - ib[0]) / 2 - ib[0], S(434)),
        ar(info),
        font=f_info,
        fill=SOFT,
    )

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def render_leaderboard(entries, icon_bytes=None, colors=None):
    top, bot = (colors[:2] if colors else (BG_TOP, BG_BOT))
    W = S(1000)
    HEADER = S(168)
    ROW = S(96)
    H = HEADER + len(entries) * ROW + S(16)
    img = vertical_gradient(W, H, top, bot).convert("RGBA")
    d = ImageDraw.Draw(img)

    if icon_bytes:
        try:
            logo = Image.open(BytesIO(icon_bytes)).convert("RGBA")
            lsize = S(96)
            logo = logo.resize((lsize, lsize))
            img.paste(logo, (S(48), S(34)), rounded_mask((lsize, lsize), lsize // 2))
            d.ellipse([S(44), S(30), S(44) + lsize + S(4), S(30) + lsize + S(4)], outline=GOLD, width=S(4))
        except Exception:
            pass

    ft = load_font(S(60), bold=True)
    fst = load_font(S(30))
    title = ar("أغنى الأعضاء")
    tb = d.textbbox((0, 0), title, font=ft)
    d.text(((W - (tb[2] - tb[0])) / 2 - tb[0], S(42)), title, font=ft, fill=GOLD)
    sub = ar("لوحة الشرف والأثرياء")
    sb = d.textbbox((0, 0), sub, font=fst)
    d.text(((W - (sb[2] - sb[0])) / 2 - sb[0], S(118)), sub, font=fst, fill=SOFT)
    d.line([(S(40), S(158)), (W - S(40), S(158))], fill=GOLD, width=S(3))

    RANK_COLORS = [(255, 215, 0), (200, 205, 210), (205, 127, 50), (70, 85, 105)]
    f_name = load_font(S(30), bold=True)
    f_sub = load_font(S(21))
    f_total = load_font(S(34), bold=True)

    for i, e in enumerate(entries):
        y = HEADER + i * ROW + S(8)
        row_bg = (26, 40, 63) if i % 2 == 0 else (20, 31, 49)
        outline = GOLD if i == 0 else (45, 60, 85)
        d.rounded_rectangle([S(30), y, W - S(30), y + ROW - S(10)], radius=S(16), fill=row_bg, outline=outline, width=S(2))

        cx, cy = S(72), y + ROW // 2 - S(5)
        color = RANK_COLORS[i] if i < 4 else RANK_COLORS[3]
        d.ellipse([cx - S(27), cy - S(27), cx + S(27), cy + S(27)], fill=color)
        fr = load_font(S(32), bold=True)
        num = str(i + 1)
        nb = d.textbbox((0, 0), num, font=fr)
        d.text((cx - (nb[2] - nb[0]) / 2 - nb[0], cy - (nb[3] - nb[1]) / 2 - nb[1]), num, font=fr, fill=(20, 20, 25))

        ax = S(130)
        if e["avatar"]:
            av = Image.open(BytesIO(e["avatar"])).convert("RGBA")
            av = av.resize((S(64), S(64)))
            img.paste(av, (ax, cy - S(32)), rounded_mask((S(64), S(64)), S(32)))
            d.ellipse([ax - S(2), cy - S(34), ax + S(66), cy + S(34)], outline=GOLD if i == 0 else (60, 75, 95), width=S(2))
        else:
            d.ellipse([ax - S(2), cy - S(34), ax + S(66), cy + S(34)], outline=(60, 75, 95), width=S(2))
            d.text((ax + S(12), cy - S(18)), "؟", font=load_font(S(30), bold=True), fill=SOFT)

        name = e["name"]
        if len(name) > 24:
            name = name[:24] + "…"
        nx = ax + S(90)
        d.text((nx, cy - S(28)), ar(name), font=f_name, fill=WHITE)
        d.text((nx, cy + S(4)), f"محفظة {e['wallet']:,}  •  بنك {e['bank']:,}", font=f_sub, fill=SOFT)

        total_txt = f"{e['total']:,}"
        tb = d.textbbox((0, 0), total_txt, font=f_total)
        d.text((W - S(60) - (tb[2] - tb[0]) - tb[0], cy - (tb[3] - tb[1]) / 2 - tb[1]), total_txt, font=f_total, fill=GOLD)

    buf = BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


RED_TOP = (96, 14, 16)
RED_BOT = (26, 4, 6)


def render_violations_card(name, avatar_bytes, violations, total_fine):
    W = S(850)
    HEADER = S(250)
    ROW = S(120)
    FOOTER = S(84)
    H = HEADER + len(violations) * ROW + FOOTER

    img = vertical_gradient(W, H, RED_TOP, RED_BOT).convert("RGBA")
    mask = rounded_mask((W, H), S(30))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.paste(img, (0, 0), mask)
    d = ImageDraw.Draw(canvas)

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W // 2 - S(360), S(10), W // 2 + S(360), H + S(30)], fill=(255, 60, 60, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(S(60)))
    canvas.paste(glow, (0, 0), glow)

    d.rounded_rectangle([S(10), S(10), W - S(10), H - S(10)], radius=S(28), outline=GOLD, width=S(4))
    d.rounded_rectangle([S(20), S(20), W - S(20), H - S(20)], radius=S(22), outline=GOLD_DIM, width=S(2))

    yline = S(74)
    d.line([(S(52), yline), (W // 2 - S(48), yline)], fill=GOLD_LINE, width=S(2))
    d.line([(W // 2 + S(48), yline), (W - S(52), yline)], fill=GOLD_LINE, width=S(2))
    r = S(7)
    d.polygon([(W // 2, yline - r), (W // 2 + r, yline), (W // 2, yline + r), (W // 2 - r, yline)], fill=GOLD)

    f_title = load_font(S(44), bold=True)
    title = ar("🚨 نظام المخالفات 🚨")
    tb = d.textbbox((0, 0), title, font=f_title)
    draw_glow_text(
        canvas,
        ((W - (tb[2] - tb[0])) / 2 - tb[0], S(92)),
        title,
        font=f_title,
        fill=(255, 95, 95),
        glow_color=(255, 120, 120),
        radius=S(9),
    )

    av_size = S(120)
    if avatar_bytes:
        try:
            av = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((av_size, av_size))
            ax, ay = S(56), S(118)
            canvas.paste(av, (ax, ay), rounded_mask((av_size, av_size), av_size // 2))
            d.ellipse([ax - S(5), ay - S(5), ax + av_size + S(5), ay + av_size + S(5)], outline=GOLD, width=S(5))
            d.ellipse([ax - S(12), ay - S(12), ax + av_size + S(12), ay + av_size + S(12)], outline=GOLD_DIM, width=S(2))
        except Exception:
            pass

    f_name = load_font(S(38), bold=True)
    f_sub = load_font(S(24))
    f_amount = load_font(S(30), bold=True)
    f_row_name = load_font(S(30), bold=True)
    f_row_date = load_font(S(21))

    tx = S(56) + av_size + S(34)
    name_w = W - tx - S(40)
    disp_name = name
    while len(disp_name) > 1 and d.textlength(ar(disp_name), font=f_name) > name_w:
        disp_name = disp_name[:-1]
    if len(disp_name) <= 1:
        disp_name = "؟"
    d.text((tx, S(124)), ar(disp_name), font=f_name, fill=WHITE)
    d.text((tx, S(182)), ar(f"عدد المخالفات: {len(violations)}"), font=f_sub, fill=SOFT)
    draw_glow_text(
        canvas,
        (tx, S(212)),
        ar(f"إجمالي الغرامات: {total_fine:,} {CURRENCY}"),
        font=f_sub,
        fill=GOLD,
        glow_color=(255, 220, 130),
        radius=S(6),
    )

    if not violations:
        f_empty = load_font(S(32), bold=True)
        empty = ar("✅ ما فيه مخالفات — مواطن ملتزم!")
        eb = d.textbbox((0, 0), empty, font=f_empty)
        draw_glow_text(
            canvas,
            ((W - (eb[2] - eb[0])) / 2 - eb[0], HEADER + S(30)),
            empty,
            font=f_empty,
            fill=(120, 255, 150),
            glow_color=(90, 255, 130),
            radius=S(8),
        )

    for i, v in enumerate(violations):
        y = HEADER + i * ROW + S(6)
        row_bg = (66, 10, 12) if i % 2 == 0 else (52, 8, 10)
        d.rounded_rectangle(
            [S(36), y, W - S(36), y + ROW - S(12)], radius=S(18), fill=row_bg, outline=(200, 60, 60), width=S(2)
        )

        cx, cy = S(78), y + ROW // 2 - S(6)
        d.ellipse([cx - S(26), cy - S(26), cx + S(26), cy + S(26)], fill=(215, 45, 45))
        fr = load_font(S(30), bold=True)
        num = str(i + 1)
        nb = d.textbbox((0, 0), num, font=fr)
        d.text(
            (cx - (nb[2] - nb[0]) / 2 - nb[0], cy - (nb[3] - nb[1]) / 2 - nb[1]),
            num,
            font=fr,
            fill=WHITE,
        )

        reason = v["reason"]
        max_w = W - S(130) - S(230)
        while len(reason) > 1 and d.textlength(ar(reason), font=f_row_name) > max_w:
            reason = reason[:-1]
        d.text((S(128), cy - S(28)), ar(reason), font=f_row_name, fill=WHITE)
        d.text((S(128), cy + S(8)), v["created_at"], font=f_row_date, fill=SOFT)

        if v["amount"] > 0:
            amt = f"-{v['amount']:,}"
            ab = d.textbbox((0, 0), amt, font=f_amount)
            draw_glow_text(
                canvas,
                (W - S(60) - (ab[2] - ab[0]) - ab[0], cy - (ab[3] - ab[1]) / 2 - ab[1]),
                amt,
                font=f_amount,
                fill=(255, 85, 85),
                glow_color=(255, 60, 60),
                radius=S(6),
            )
        else:
            no = ar("بدون غرامة")
            nob = d.textbbox((0, 0), no, font=f_row_date)
            d.text(
                (W - S(60) - (nob[2] - nob[0]) - nob[0], cy - (nob[3] - nob[1]) / 2 - nob[1]),
                no,
                font=f_row_date,
                fill=SOFT,
            )

    f_foot = load_font(S(24), bold=True)
    foot = ar("🚔 مكتب المخالفات — التزم بالقانون داخل السيرفر")
    fb = d.textbbox((0, 0), foot, font=f_foot)
    draw_glow_text(
        canvas,
        ((W - (fb[2] - fb[0])) / 2 - fb[0], H - FOOTER + S(22)),
        foot,
        font=f_foot,
        fill=GOLD,
        glow_color=(255, 200, 100),
        radius=S(6),
    )

    buf = BytesIO()
    canvas.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def render_rob_image(success, avatar_bytes, title_text, sub_text, footer_text):
    W, H = S(850), S(500)
    if success:
        top_c, bot_c = (14, 95, 55), (4, 30, 18)
    else:
        top_c, bot_c = (140, 18, 34), (48, 6, 14)
    img = vertical_gradient(W, H, top_c, bot_c).convert("RGBA")
    mask = rounded_mask((W, H), S(26))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.paste(img, (0, 0), mask)
    d = ImageDraw.Draw(canvas)

    bar_h = S(70)
    n = 14
    seg = W // n
    bar_colors = [(225, 48, 48), (48, 88, 225)]
    for i in range(n):
        d.rectangle([i * seg, 0, (i + 1) * seg, bar_h], fill=bar_colors[i % 2])

    f_emo = emoji_font(S(104))
    emoji = "🎉" if success else "🚨"
    bbox = d.textbbox((0, 0), emoji, font=f_emo)
    d.text(((W - (bbox[2] - bbox[0])) / 2 - bbox[0], S(92)), emoji, font=f_emo, fill=WHITE, embedded_color=True)

    f_title = load_font(S(46), bold=True)
    tb = d.textbbox((0, 0), ar(title_text), font=f_title)
    draw_glow_text(
        canvas,
        ((W - (tb[2] - tb[0])) / 2 - tb[0], S(212)),
        ar(title_text),
        font=f_title,
        fill=GOLD if success else (255, 95, 95),
        glow_color=(255, 255, 255),
        radius=S(8),
    )

    if avatar_bytes:
        try:
            av = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
            av = av.resize((S(150), S(150)))
            ax = (W - S(150)) // 2
            canvas.paste(av, (ax, S(270)), rounded_mask((S(150), S(150)), S(75)))
            d.ellipse([ax - S(4), S(270) - S(4), ax + S(150) + S(4), S(270) + S(150) + S(4)], outline=WHITE, width=S(4))
        except Exception:
            pass

    f_sub = load_font(S(30), bold=True)
    sb = d.textbbox((0, 0), ar(sub_text), font=f_sub)
    draw_glow_text(
        canvas,
        ((W - (sb[2] - sb[0])) / 2 - sb[0], S(438)),
        ar(sub_text),
        font=f_sub,
        fill=WHITE,
        glow_color=(255, 255, 255),
        radius=S(6),
    )

    f_foot = load_font(S(24))
    fb = d.textbbox((0, 0), ar(footer_text), font=f_foot)
    d.text(((W - (fb[2] - fb[0])) / 2 - fb[0], S(480)), ar(footer_text), font=f_foot, fill=SOFT)

    buf = BytesIO()
    canvas.save(buf, "PNG")
    buf.seek(0)
    return buf

# ================== cogs/bank.py ==================



class Bank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="رصيد")
    async def balance(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        conn = await get_connection()
        user = await get_user(conn, member.id)
        await conn.close()
        total = user["wallet"] + user["bank"]

        avatar_bytes = None
        guild_icon = None
        try:
            async with aiohttp.ClientSession() as session:
                if ctx.guild.icon:
                    async with session.get(str(ctx.guild.icon.with_size(256).url)) as resp:
                        guild_icon = await resp.read()
                async with session.get(str(member.display_avatar.with_size(128).url)) as resp:
                    avatar_bytes = await resp.read()
        except Exception:
            pass

        colors = extract_colors(guild_icon) if guild_icon else None
        card = render_card(
            member.display_name, avatar_bytes, user["wallet"], user["bank"], user["loan"], total,
            icon_bytes=guild_icon, colors=colors,
        )
        embed = discord.Embed(title=f"💳 بطاقة {member.display_name}", color=COLOR)
        embed.set_image(url="attachment://card.png")
        if user["loan"] > 0:
            embed.add_field(
                name="القرض",
                value=f"{CURRENCY} {user['loan']:,} (سدّده بـ -سداد)",
                inline=False,
            )
        await safe_send(ctx, embed=embed, file=discord.File(card, "card.png"))

    @commands.command(name="ايداع")
    async def deposit(self, ctx, amount: str):
        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        amt = user["wallet"] if amount.lower() == "all" else parse_amount(amount)
        if amt <= 0:
            await conn.close()
            await ctx.reply("❌ المبلغ غير صحيح")
            return
        if user["wallet"] < amt:
            await conn.close()
            await ctx.reply(f"❌ محفظتك ما تكفي، عندك {CURRENCY} {user['wallet']:,}")
            return
        await update_wallet(conn, ctx.author.id, -amt)
        await update_bank(conn, ctx.author.id, amt)
        await conn.close()
        await ctx.reply(f"✅ تم إيداع {CURRENCY} {amt:,} في البنك")

    @commands.command(name="سحب")
    async def withdraw(self, ctx, amount: str):
        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        amt = user["bank"] if amount.lower() == "all" else parse_amount(amount)
        if amt <= 0:
            await conn.close()
            await ctx.reply("❌ المبلغ غير صحيح")
            return
        if user["bank"] < amt:
            await conn.close()
            await ctx.reply(f"❌ رصيد بنكك ما يكفي، عندك {CURRENCY} {user['bank']:,}")
            return
        await update_bank(conn, ctx.author.id, -amt)
        await update_wallet(conn, ctx.author.id, amt)
        await conn.close()
        await ctx.reply(f"✅ تم سحب {CURRENCY} {amt:,} من البنك")

    @commands.command(name="اعطي")
    async def give(self, ctx, member: discord.Member, amount: str):
        amt = parse_amount(amount)
        if amt <= 0:
            await ctx.reply("❌ المبلغ غير صحيح")
            return

        is_admin = ctx.author.guild_permissions.administrator or any(
            "admin" in r.name.lower() or "ادمين" in r.name.lower() or "ادمن" in r.name.lower()
            for r in ctx.author.roles
        )

        if member.id == ctx.author.id and not is_admin:
            await ctx.reply("❌ ما تقدر تعطي نفسك 😄")
            return

        conn = await get_connection()

        if is_admin:
            await update_wallet(conn, member.id, amt)
            await conn.close()
            await ctx.reply(f"👑 (آدمن) أعطيت {CURRENCY} {amt:,} إلى {member.mention}")
            return

        user = await get_user(conn, ctx.author.id)
        fee = int(amt * TRANSFER_FEE)
        total = amt + fee
        if user["wallet"] < total:
            await conn.close()
            await ctx.reply(f"❌ محفظتك ما تكفي (تحتاج {CURRENCY} {total:,} مع الرسوم)")
            return
        await update_wallet(conn, ctx.author.id, -total)
        await update_wallet(conn, member.id, amt)
        await conn.close()
        await ctx.reply(
            f"✅ حولت {CURRENCY} {amt:,} إلى {member.mention} (رسوم {CURRENCY} {fee:,})"
        )

    @commands.command(name="اعادة رقم")
    async def reset_number(self, ctx, member: discord.Member = None):
        if not ctx.author.guild_permissions.administrator:
            await ctx.reply("❌ هذا الأمر للإدارة فقط 👑")
            return
        if member is None:
            await ctx.reply("❌ حدد الشخص: `-اعادة رقم @شخص`")
            return
        if member.bot:
            await ctx.reply("❌ هذا بوت 🤖")
            return
        conn = await get_connection()
        await reset_user_numbers(conn, member.id)
        await conn.close()
        await ctx.reply(
            f"🧹 تمت إعادة رقم {member.mention} إلى **0**\n"
            f"(المحفظة والبنك والقرض كلها تصفّرت)"
        )

    @commands.command(name="ريسيت")
    async def reset_money(self, ctx, member: discord.Member = None):
        if not ctx.author.guild_permissions.administrator:
            await ctx.reply("❌ هذا الأمر للإدارة فقط 👑")
            return
        if member is None:
            await ctx.reply("❌ حدد الشخص: `-ريسيت @شخص`")
            return
        if member.bot:
            await ctx.reply("❌ هذا بوت 🤖")
            return
        conn = await get_connection()
        await reset_user_numbers(conn, member.id)
        await conn.close()
        await ctx.reply(
            f"🧹 **تم ريسيت فلوس {member.mention}**\n"
            f"المحفظة والبنك والقرض رجعت كلها إلى **0** ✅"
        )


async def setup(bot):
    await bot.add_cog(Bank(bot))

# ================== cogs/economy.py ==================



WORK_JOBS = ["مطعم 🍔", "شركة برمجة 💻", "مستشفى 🏥", "مدرسة 📚", "مصنع 🏭", "مزرعة 🌾"]


def rob_luck_chance(wallet):
    if wallet > 100000:
        return 0.005
    if wallet > 50000:
        return 0.01
    if wallet > 25000:
        return 0.05
    if wallet > 10000:
        return 0.10
    if wallet > 5000:
        return 0.20
    if wallet > 2500:
        return 0.25
    return 0.30


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="راتب")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def daily(self, ctx):
        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        amount = DAILY_AMOUNT
        used_boost = False
        inv = await get_inventory(conn, ctx.author.id)
        boost = next((i for i in inv if i["item_id"] == "boost"), None)
        if boost and boost["quantity"] > 0:
            amount *= 2
            used_boost = True
            await remove_item(conn, ctx.author.id, "boost", 1)
        await update_wallet(conn, ctx.author.id, amount)
        await conn.close()
        embed = discord.Embed(
            title="🎉 راتبك اليومي",
            description=f"حصلت على {CURRENCY} {amount:,}",
            color=COLOR,
        )
        embed.set_image(url="attachment://daily_banner.png")
        if used_boost:
            embed.set_footer(text="⚡ استخدمت مضاعف الراتب x2")
        await ctx.reply(embed=embed, file=discord.File("assets/daily_banner.png", "daily_banner.png"))

    @commands.command(name="عمل")
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def work(self, ctx):
        amount = random.randint(WORK_MIN, WORK_MAX)
        job = random.choice(WORK_JOBS)
        conn = await get_connection()
        await update_wallet(conn, ctx.author.id, amount)
        await conn.close()
        await ctx.reply(f"💼 اشتغلت في {job} وحصلت على {CURRENCY} {amount:,}")

    @commands.command(name="شحاذة")
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def beg(self, ctx):
        if random.random() < 0.4:
            await ctx.reply("😔 محد أعطاك، الناس قساة هاليوم")
            return
        amount = random.randint(BEG_MIN, BEG_MAX)
        conn = await get_connection()
        await update_wallet(conn, ctx.author.id, amount)
        await conn.close()
        await ctx.reply(f"🙏 واحد كريم عطاك {CURRENCY} {amount:,}")

    @commands.command(name="مقامرة")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def gamble(self, ctx, amount: str):
        amt = parse_amount(amount)
        if amt <= 0:
            await ctx.reply("❌ المبلغ غير صحيح")
            return
        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        if user["wallet"] < amt:
            await conn.close()
            await ctx.reply(f"❌ محفظتك ما تكفي، عندك {CURRENCY} {user['wallet']:,}")
            return

        chance = min(95, max(GAMBLE_MIN_CHANCE, int(100 - amt / GAMBLE_DIVISOR)))
        multiplier = max(0.1, ((100 - chance) / chance) * GAMBLE_EDGE)
        roll = random.randint(1, 100)
        if roll <= chance:
            profit = max(1, int(amt * multiplier))
            await update_wallet(conn, ctx.author.id, profit)
            await conn.close()
            await ctx.reply(
                f"🎲 راهنت {CURRENCY} {amt:,} وحظك كان **{chance}%** ونجحت!\n"
                f"ربحت {CURRENCY} {profit:,} 🤑"
            )
        else:
            await update_wallet(conn, ctx.author.id, -amt)
            await conn.close()
            await ctx.reply(
                f"🎲 راهنت {CURRENCY} {amt:,} وحظك كان **{chance}%** وخسرت 😢"
            )

    @commands.command(name="سرقة")
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def rob(self, ctx, member: discord.Member):
        if member.id == ctx.author.id:
            await ctx.reply("❌ تسرق نفسك؟! 😂")
            return
        conn = await get_connection()
        target = await get_user(conn, member.id)
        if target["wallet"] <= 0:
            await conn.close()
            await ctx.reply("😒 هذا مسكين ماعنده ولا عملة بالمحفظة")
            return

        chance = rob_luck_chance(target["wallet"])
        avatar_bytes = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(ctx.author.display_avatar.with_size(128).url)) as resp:
                    avatar_bytes = await resp.read()
        except Exception:
            pass

        if random.random() < chance:
            steal = int(target["wallet"] * ROB_STEAL_PERCENT)
            await update_wallet(conn, member.id, -steal)
            await update_wallet(conn, ctx.author.id, steal)
            img = render_rob_image(
                True,
                avatar_bytes,
                "عملية سطو ناجحة",
                f"سرقت {CURRENCY} {steal:,} من {member.display_name}",
                f"نسبة نجاحك كانت {chance * 100:.1f}%",
            )
            embed = discord.Embed(
                title="🎉 سطو ناجح!",
                description=f"سرقت {CURRENCY} {steal:,} من {member.mention} (حظك {chance * 100:.1f}%)",
                color=COLOR,
            )
            embed.set_image(url="attachment://rob.png")
            await safe_send(ctx, embed=embed, file=discord.File(img, "rob.png"))
        else:
            user = await get_user(conn, ctx.author.id)
            fine = int(user["wallet"] * ROB_FAIL_FINE_PERCENT)
            await update_wallet(conn, ctx.author.id, -fine)
            img = render_rob_image(
                False,
                avatar_bytes,
                "تحذير شرطة البنك",
                f"انقبضت عليك ودفعت غرامة {CURRENCY} {fine:,}",
                f"نسبة نجاحك كانت {chance * 100:.1f}%",
            )
            embed = discord.Embed(
                title="🚨 الشرطة قبضت عليك!",
                description=f"دفعت غرامة {CURRENCY} {fine:,} (حظك {chance * 100:.1f}%)",
                color=COLOR,
            )
            embed.set_image(url="attachment://rob.png")
            await safe_send(ctx, embed=embed, file=discord.File(img, "rob.png"))
        await conn.close()


async def setup(bot):
    await bot.add_cog(Economy(bot))

# ================== cogs/loans.py ==================



@tasks.loop(hours=INTEREST_INTERVAL_HOURS)
async def interest_task():
    conn = await get_connection()
    rate = DEPOSIT_INTEREST_RATE
    await conn.execute(
        "UPDATE users SET bank = bank + CAST(bank * ? AS INTEGER) WHERE bank > 0",
        (rate,),
    )
    await conn.commit()
    await conn.close()


class Loans(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="قرض")
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def loan(self, ctx, amount: str):
        amt = parse_amount(amount)
        if amt <= 0:
            await ctx.reply("❌ المبلغ غير صحيح")
            return
        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        if user["loan"] > 0:
            await conn.close()
            await ctx.reply(
                f"❌ عندك قرض مفتوح {CURRENCY} {user['loan']:,}، سدّده أول بـ -سداد"
            )
            return
        max_loan = user["wallet"] * LOAN_MAX_MULTIPLIER
        if amt > max_loan:
            await conn.close()
            await ctx.reply(f"❌ الحد الأقصى لقرضك هو {CURRENCY} {max_loan:,}")
            return
        await conn.execute(
            "UPDATE users SET loan = ?, wallet = wallet + ? WHERE user_id = ?",
            (amt, amt, ctx.author.id),
        )
        await conn.commit()
        await conn.close()
        await ctx.reply(
            f"🏦 أخذت قرض {CURRENCY} {amt:,} وفائدة {LOAN_INTEREST * 100:.0f}% عند السداد"
        )

    @commands.command(name="سداد")
    async def repay(self, ctx, amount: str):
        amt = parse_amount(amount)
        if amt <= 0:
            await ctx.reply("❌ المبلغ غير صحيح")
            return
        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        if user["loan"] <= 0:
            await conn.close()
            await ctx.reply("✅ ما عندك قروض مفتوحة")
            return
        if user["wallet"] < amt:
            await conn.close()
            await ctx.reply(f"❌ محفظتك ما تكفي، عندك {CURRENCY} {user['wallet']:,}")
            return
        paid = int(amt / (1 + LOAN_INTEREST))
        remaining = user["loan"] - paid
        if remaining < 0:
            paid = user["loan"]
            amt = int(paid * (1 + LOAN_INTEREST))
            remaining = 0
        await update_wallet(conn, ctx.author.id, -amt)
        await conn.execute(
            "UPDATE users SET loan = ? WHERE user_id = ?", (remaining, ctx.author.id)
        )
        await conn.commit()
        await conn.close()
        if remaining == 0:
            await ctx.reply(f"🎉 مبروك! سددت كل قرضك ({CURRENCY} {paid:,})")
        else:
            await ctx.reply(
                f"✅ سددت {CURRENCY} {paid:,} من القرض، باقي {CURRENCY} {remaining:,}"
            )

    @commands.command(name="قروضي")
    async def loan_status(self, ctx):
        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        await conn.close()
        if user["loan"] <= 0:
            await ctx.reply("✅ ما عندك قروض مفتوحة")
            return
        total_owed = int(user["loan"] * (1 + LOAN_INTEREST))
        embed = discord.Embed(
            title="🏦 قروضك",
            color=COLOR,
            description=f"قرضك الحالي: **{CURRENCY} {user['loan']:,}**\nالإجمالي المستحق مع الفائدة: **{CURRENCY} {total_owed:,}**",
        )
        embed.set_thumbnail(url="attachment://bank_banner.png")
        await ctx.reply(embed=embed, file=discord.File("assets/bank_banner.png", "bank_banner.png"))


async def setup(bot):
    await bot.add_cog(Loans(bot))

# ================== cogs/shop.py ==================




def find_item(key):
    for item in SHOP_ITEMS:
        if key == item["id"] or key == item["name"]:
            return item
    return None


class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="متجر")
    async def shop(self, ctx):
        embed = discord.Embed(title="🛒 المتجر", color=COLOR)
        for item in SHOP_ITEMS:
            embed.add_field(
                name=f"{item['emoji']} {item['name']} — {CURRENCY} {item['price']:,}",
                value=item["desc"],
                inline=False,
            )
        embed.set_image(url="attachment://shop_banner.png")
        embed.set_footer(text="للشراء استخدم: -شراء <اسم السلعة>")
        await ctx.reply(embed=embed, file=discord.File("assets/shop_banner.png", "shop_banner.png"))

    @commands.command(name="شراء")
    async def buy(self, ctx, *, item_name: str):
        item = find_item(item_name.strip())
        if not item:
            await ctx.reply("❌ السلعة غير موجودة، شوف -متجر")
            return
        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        if user["wallet"] < item["price"]:
            await conn.close()
            await ctx.reply(f"❌ محفظتك ما تكفي، تحتاج {CURRENCY} {item['price']:,}")
            return
        await update_wallet(conn, ctx.author.id, -item["price"])
        if item["type"] == "role":
            role = None
            if item.get("role_id"):
                role = ctx.guild.get_role(item["role_id"])
            if role is None:
                role = discord.get(ctx.guild.roles, name=item["name"])
            if role:
                await ctx.author.add_roles(role)
                await conn.close()
                await ctx.reply(f"✅ شريت {item['name']} وحصلت على الرتبة {role.mention}")
                return
            await add_item(conn, ctx.author.id, item["id"])
            await conn.close()
            await ctx.reply(
                f"⚠️ ما لقيت رتبة بالاسم «{item['name']}» في السيرفر، خزّنّا لك في مخزنك"
            )
            return
        await add_item(conn, ctx.author.id, item["id"])
        await conn.close()
        await ctx.reply(f"✅ شريت {item['name']}، شوف -مخزني")

    @commands.command(name="مخزني")
    async def inventory(self, ctx):
        conn = await get_connection()
        inv = await get_inventory(conn, ctx.author.id)
        await conn.close()
        embed = discord.Embed(title=f"📦 مخزن {ctx.author.display_name}", color=COLOR)
        if not inv:
            embed.description = "المخزن فاضي، اشتري من -متجر"
        for row in inv:
            item = find_item(row["item_id"])
            name = item["name"] if item else row["item_id"]
            embed.add_field(name=name, value=f"الكمية: {row['quantity']}", inline=True)
        await ctx.reply(embed=embed)

    @commands.command(name="يانصيب")
    async def lottery(self, ctx):
        conn = await get_connection()
        inv = await get_inventory(conn, ctx.author.id)
        ticket = next((i for i in inv if i["item_id"] == "lottery"), None)
        if not ticket or ticket["quantity"] <= 0:
            await conn.close()
            await ctx.reply("❌ ما عندك تذاكر يانصيب، اشترِ من -متجر")
            return
        await remove_item(conn, ctx.author.id, "lottery", 1)
        if random.random() < 0.1:
            prize = 500 * 10
            await update_wallet(conn, ctx.author.id, prize)
            await ctx.reply(f"🎉 مبروك!! فزت باليانصيب وجبت {CURRENCY} {prize:,}!")
        else:
            await ctx.reply("😢 خسرت التذكرة، جرب مرة ثانية")
        await conn.close()


async def setup(bot):
    await bot.add_cog(Shop(bot))

# ================== cogs/leaderboard.py ==================


MEDALS = ["🥇", "🥈", "🥉"]


class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="توب")
    async def leaderboard(self, ctx):
        conn = await get_connection()
        cur = await conn.execute(
            "SELECT user_id, wallet, bank FROM users ORDER BY (wallet + bank) DESC LIMIT 10"
        )
        rows = await cur.fetchall()
        await conn.close()

        if not rows:
            embed = discord.Embed(title="🏆 أغنى الأعضاء", color=COLOR, description="ما فيه بيانات بعد")
            await ctx.reply(embed=embed, file=discord.File("assets/lb_banner.png", "lb_banner.png"))
            return

        entries = []
        guild_icon = None
        async with aiohttp.ClientSession() as session:
            if ctx.guild.icon:
                try:
                    async with session.get(str(ctx.guild.icon.with_size(256).url)) as resp:
                        guild_icon = await resp.read()
                except Exception:
                    guild_icon = None
            for row in rows:
                total = row["wallet"] + row["bank"]
                member = ctx.guild.get_member(row["user_id"])
                name = member.display_name if member else f"معرف {row['user_id']}"
                avatar = None
                if member:
                    try:
                        async with session.get(str(member.display_avatar.with_size(128).url)) as resp:
                            avatar = await resp.read()
                    except Exception:
                        avatar = None
                entries.append(
                    {"name": name, "avatar": avatar, "wallet": row["wallet"], "bank": row["bank"], "total": total}
                )

        colors = extract_colors(guild_icon) if guild_icon else None
        board = render_leaderboard(entries, icon_bytes=guild_icon, colors=colors)
        embed = discord.Embed(title="🏆 أغنى الأعضاء", color=COLOR)
        embed.set_image(url="attachment://leaderboard.png")
        await safe_send(ctx, embed=embed, file=discord.File(board, "leaderboard.png"))

    @commands.command(name="مساعدة")
    async def help_cmd(self, ctx):
        embed = discord.Embed(title="📖 أوامر البنك", color=COLOR)
        groups = {
            "🏦 البنك": "رصيد، ايداع، سحب، اعطي، قرض، سداد، قروضي",
            "💼 الاقتصاد": "راتب، عمل، شحاذة، مقامرة، سرقة",
            "💍 الزواج": "زواج، طلاق، طلاق 3، خلع، تصالح",
            "🛒 المتجر": "متجر، شراء، مخزني، يانصيب",
            "🚔 المخالفات": "مخالفة، مخالفات، مخالفاتي، مسح مخالفات",
            "🏆 أخرى": "توب، مساعدة",
        }
        for title, cmds in groups.items():
            embed.add_field(name=title, value=f"`-{cmds}`", inline=False)
        embed.set_footer(text=f"البادئة: {PREFIX} — مثال: -اعطي @شخص 100")
        await ctx.reply(embed=embed)


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))

# ================== cogs/guilds.py ==================



class Guilds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="قناة")
    async def channel_info(self, ctx):
        conn = await get_connection()
        cid = await get_guild_channel(conn, ctx.guild.id)
        await conn.close()
        if cid:
            ch = ctx.guild.get_channel(cid)
            desc = ch.mention if ch else f"`{cid}`"
            await ctx.reply(
                f"📢 قناة البنك الحالية: {desc}\n\nلتغييرها استخدم `/setchannel`"
            )
        else:
            await ctx.reply(
                "📢 ما فيه قناة معيّنة بعد.\nاستخدم `/setchannel` لاختيار قناة البنك."
            )


async def setup(bot):
    await bot.add_cog(Guilds(bot))

# ================== cogs/marriage.py ==================




async def fetch_avatar(member):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(member.display_avatar.with_size(256).url)) as resp:
                return await resp.read()
    except Exception:
        return None


class ProposalView(View):
    def __init__(self, proposer, target, mahr):
        super().__init__(timeout=300)
        self.proposer = proposer
        self.target = target
        self.mahr = mahr
        self.done = False

    async def disable(self, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="✅ أقبل", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("❌ هذا الطلب مو لك!", ephemeral=True)
            return
        if self.done:
            return
        self.done = True
        conn = await get_connection()
        try:
            if await get_marriage(conn, self.proposer.id) or await get_marriage(conn, self.target.id):
                await self.disable(interaction)
                await interaction.followup.send("❌ أحد الطرفين متزوج بالفعل", ephemeral=True)
                return
            user = await get_user(conn, self.proposer.id)
            if user["wallet"] < self.mahr:
                await self.disable(interaction)
                await interaction.followup.send(
                    f"❌ {self.proposer.mention} ما عنده المهر الكافي ({CURRENCY} {self.mahr:,})",
                    ephemeral=True,
                )
                return
            await update_wallet(conn, self.proposer.id, -self.mahr)
            await update_wallet(conn, self.target.id, self.mahr)
            await create_marriage(conn, self.proposer.id, self.target.id, self.mahr)
        finally:
            await conn.close()
        await self.disable(interaction)
        await self.send_card(interaction)

    @discord.ui.button(label="❌ أرفض", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("❌ هذا الطلب مو لك!", ephemeral=True)
            return
        if self.done:
            return
        self.done = True
        await self.disable(interaction)
        await interaction.followup.send(f"💔 {self.target.mention} رفض طلب الزواج 😢", ephemeral=False)

    async def send_card(self, interaction):
        av1 = await fetch_avatar(self.proposer)
        av2 = await fetch_avatar(self.target)
        date = ""
        conn = await get_connection()
        try:
            m = await get_marriage(conn, self.proposer.id)
            if m:
                date = m["married_at"]
        finally:
            await conn.close()
        card = render_marriage_card(
            self.proposer.display_name, self.target.display_name, av1, av2, self.mahr, date
        )
        embed = discord.Embed(
            title="💍 مبروك الزواج!",
            description=f"{self.proposer.mention} 💕 {self.target.mention}",
            color=0xF06292,
        )
        embed.set_image(url="attachment://marriage.png")
        sent = await interaction.followup.send(
            embed=embed, file=discord.File(card, "marriage.png"), ephemeral=False
        )
        cache_from_msg(sent, embed, discord.File(card, "marriage.png"))
        try:
            await sent.edit(view=DivorceMenuView(interaction.client, self.proposer, self.target))
        except Exception:
            pass

    async def on_timeout(self):
        if not self.done:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class DivorceView(View):
    def __init__(self, initiator, spouse, conn):
        super().__init__(timeout=300)
        self.initiator = initiator
        self.spouse = spouse
        self.conn = conn
        self.done = False

    async def disable(self, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="✅ أوافق", style=discord.ButtonStyle.success)
    async def agree(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.spouse.id:
            await interaction.response.send_message("❌ هذا الطلب مو لك!", ephemeral=True)
            return
        if self.done:
            return
        self.done = True
        await delete_marriage(self.conn, self.initiator.id)
        await self.conn.close()
        await self.disable(interaction)
        await interaction.followup.send(
            f"🕊️ تم الطلاق بين {self.initiator.mention} و {self.spouse.mention} — الحب انتهى، البنك باقي 💔",
            ephemeral=False,
        )

    @discord.ui.button(label="❌ أرفض", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.spouse.id:
            await interaction.response.send_message("❌ هذا الطلب مو لك!", ephemeral=True)
            return
        if self.done:
            return
        self.done = True
        await self.disable(interaction)
        await interaction.followup.send(
            f"💕 {self.spouse.mention} رفض الطلاق — الحب انتصر!",
            ephemeral=False,
        )

    async def on_timeout(self):
        if not self.done:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class ReconcileView(View):
    def __init__(self, initiator, spouse):
        super().__init__(timeout=300)
        self.initiator = initiator
        self.spouse = spouse
        self.done = False

    async def disable(self, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🤝 أقبل التصالح", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.spouse.id:
            await interaction.response.send_message("❌ هذا الطلب مو لك!", ephemeral=True)
            return
        if self.done:
            return
        self.done = True
        conn = await get_connection()
        try:
            if not await is_divorce_blocked(conn, self.initiator.id, self.spouse.id):
                await conn.close()
                await self.disable(interaction)
                await interaction.followup.send("❌ ما فيه منع زواج بينكم أصلاً", ephemeral=True)
                return
            await remove_divorce_block(conn, self.initiator.id, self.spouse.id)
        finally:
            await conn.close()
        await self.disable(interaction)
        await interaction.followup.send(
            f"🤝🤝🤝 **تم التصالح!**\n\n"
            f"{self.initiator.mention} و {self.spouse.mention} تصالحوا — "
            f"الخلاف انتهى وفتح باب الزواج من جديد 💕\n"
            f"(المنع اللي من الطلاق بثلاث تم رفعه ✅)"
        )

    @discord.ui.button(label="❌ أرفض التصالح", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.spouse.id:
            await interaction.response.send_message("❌ هذا الطلب مو لك!", ephemeral=True)
            return
        if self.done:
            return
        self.done = True
        await self.disable(interaction)
        await interaction.followup.send(
            f"💔 {self.spouse.mention} رفض التصالح — الزواج بينكم يبقى ممنوع ⛔",
            ephemeral=False,
        )

    async def on_timeout(self):
        if not self.done:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class DivorceMenuView(View):
    def __init__(self, bot, member1, member2):
        super().__init__(timeout=600)
        self.bot = bot
        self.m1 = member1
        self.m2 = member2

    def is_couple(self, user_id):
        return user_id in (self.m1.id, self.m2.id)

    async def fail(self, interaction):
        await interaction.response.send_message("❌ هذا مو زواجك!", ephemeral=True)

    async def get_marriage_row(self, user_id):
        conn = await get_connection()
        row = await get_marriage(conn, user_id)
        return conn, row

    @discord.ui.button(label="🕊️ طلاق", style=discord.ButtonStyle.danger)
    async def normal_divorce(self, interaction: discord.Interaction, button: Button):
        if not self.is_couple(interaction.user.id):
            return await self.fail(interaction)
        conn, row = await self.get_marriage_row(interaction.user.id)
        if not row:
            await conn.close()
            return await interaction.response.send_message("❌ مو متزوجين أصلاً", ephemeral=True)
        partner_id = row["user2"] if row["user1"] == interaction.user.id else row["user1"]
        partner = interaction.guild.get_member(partner_id)
        if partner is None:
            await delete_marriage(conn, interaction.user.id)
            await conn.close()
            return await interaction.response.send_message(
                "✅ شريكك مش موجود في السيرفر، انفصلت تلقائياً", ephemeral=True
            )
        embed = discord.Embed(
            title="🕊️ طلب طلاق",
            description=f"{interaction.user.mention} يريد الطلاق منك، هل توافق؟",
            color=0xE74C3C,
        )
        view = DivorceView(interaction.user, partner, conn)
        await interaction.response.defer()
        sent = await interaction.followup.send(embed=embed, view=view)
        view.message = sent

    @discord.ui.button(label="🩸 خلع", style=discord.ButtonStyle.danger)
    async def khul_divorce(self, interaction: discord.Interaction, button: Button):
        if not self.is_couple(interaction.user.id):
            return await self.fail(interaction)
        conn, row = await self.get_marriage_row(interaction.user.id)
        if not row:
            await conn.close()
            return await interaction.response.send_message("❌ مو متزوجين أصلاً", ephemeral=True)
        partner_id = row["user2"] if row["user1"] == interaction.user.id else row["user1"]
        await conn.close()
        await interaction.response.send_message(
            f"🩸 {interaction.user.mention} طلبت الخلع!\n"
            f"لتأكيد الخلع اكتب **`خلع`** مرتين في الشات الآن"
        )

        def check(msg):
            return (
                msg.author.id == interaction.user.id
                and msg.channel.id == interaction.channel.id
                and "خلع" in msg.content
            )

        for i in range(2):
            try:
                await self.bot.wait_for("message", check=check, timeout=30)
                await interaction.channel.send(f"✅ {i + 1}/2 — تم تأكيد الخلع!")
            except asyncio.TimeoutError:
                await interaction.channel.send("⏳ ما كتبت الخلع بالوقت، ألغيت العملية")
                return

        conn, row = await self.get_marriage_row(interaction.user.id)
        if not row:
            await conn.close()
            await interaction.channel.send("❌ مو متزوجين أصلاً 😅")
            return
        await delete_marriage(conn, interaction.user.id)
        await conn.close()
        await interaction.channel.send(
            f"🩸🩸🩸 **تم الخلع!**\n\n"
            f"{interaction.user.mention} نطقت الخلع مرتين... وصار ينزل **دماء** 🩸💔\n"
            f"المرأة طلبت الخلع وتحررت — انتهى الزواج بينها وبين <@{partner_id}>"
        )

    @discord.ui.button(label="🔥 طلاق بثلاث", style=discord.ButtonStyle.danger)
    async def triple_divorce(self, interaction: discord.Interaction, button: Button):
        if not self.is_couple(interaction.user.id):
            return await self.fail(interaction)
        conn, row = await self.get_marriage_row(interaction.user.id)
        if not row:
            await conn.close()
            return await interaction.response.send_message("❌ مو متزوجين أصلاً", ephemeral=True)
        partner_id = row["user2"] if row["user1"] == interaction.user.id else row["user1"]
        await conn.close()
        await interaction.response.send_message(
            f"🔥🔥 {interaction.user.mention} يريد الطلاق **بثلاث**!\n"
            f"لتأكيد الطلاق بثلاث اكتب **`طلاق`** ثلاث مرات في الشات الآن"
        )

        def check(msg):
            return (
                msg.author.id == interaction.user.id
                and msg.channel.id == interaction.channel.id
                and "طلاق" in msg.content
            )

        for i in range(3):
            try:
                await self.bot.wait_for("message", check=check, timeout=30)
                await interaction.channel.send(f"✅ {i + 1}/3 — طلقة!")
            except asyncio.TimeoutError:
                await interaction.channel.send("⏳ ما أكدت الطلاق بالوقت، ألغيت العملية")
                return

        conn, row = await self.get_marriage_row(interaction.user.id)
        if not row:
            await conn.close()
            await interaction.channel.send("❌ مو متزوجين أصلاً 😅")
            return
        await delete_marriage(conn, interaction.user.id)
        await add_divorce_block(conn, interaction.user.id, partner_id)
        await conn.close()
        await interaction.channel.send(
            f"🔥🔥🔥 **تم الطلاق بثلاث!**\n\n"
            f"قال: طلقتك، طلقتك، طلقتك... 💔\n"
            f"الزواج بين {interaction.user.mention} و <@{partner_id}> انتهى — "
            f"**ممنوع الزواج بينهم** إلا بعد تصالح (`-تصالح @شخص`) 🤝"
        )


class Marriage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="زواج")
    async def marry(self, ctx, member: discord.Member = None):
        if member is None:
            conn = await get_connection()
            row = await get_marriage(conn, ctx.author.id)
            if not row:
                await conn.close()
                await ctx.reply("❌ انت مو متزوج! استخدم `-زواج @شخص` وتزوج 💍")
                return
            partner_id = row["user2"] if row["user1"] == ctx.author.id else row["user1"]
            partner = ctx.guild.get_member(partner_id)
            if partner is None:
                await conn.close()
                await ctx.reply("❌ الشريك مو في السيرفر حالياً")
                return
            av1 = await fetch_avatar(ctx.author)
            av2 = await fetch_avatar(partner)
            await conn.close()
            card = render_marriage_card(
                ctx.author.display_name,
                partner.display_name,
                av1,
                av2,
                row["mahr"],
                row["married_at"],
            )
            embed = discord.Embed(
                title="💍 بطاقة الزواج",
                description=f"{ctx.author.mention} 💕 {partner.mention}",
                color=0xF06292,
            )
            embed.set_image(url="attachment://marriage.png")
            await safe_send(
                ctx,
                embed=embed,
                file=discord.File(card, "marriage.png"),
                view=DivorceMenuView(ctx.bot, ctx.author, partner),
            )
            return

        if member.id == ctx.author.id:
            await ctx.reply("❌ ما تقدر تتزوج نفسك 😄")
            return
        if member.bot:
            await ctx.reply("❌ ما تقدر تتزوج بوت 🤖")
            return

        conn = await get_connection()
        if await get_marriage(conn, ctx.author.id):
            await conn.close()
            await ctx.reply("❌ انت متزوج بالفعل! (للطلاق: `-طلاق` أو `-طلاق 3` أو `-خلع`)")
            return
        if await get_marriage(conn, member.id):
            await conn.close()
            await ctx.reply(f"❌ {member.mention} متزوج بالفعل!")
            return
        if await is_divorce_blocked(conn, ctx.author.id, member.id):
            await conn.close()
            await ctx.reply(
                f"❌ الزواج بينكم **ممنوع** 🔥 — فيكم طلاق بثلاث!\n"
                f"الحل: `-تصالح @شخص` 🤝"
            )
            return
        await conn.close()

        await ctx.reply(
            f"💍 طلب زواج لـ {member.mention}!\n"
            f"اكتب المهر الآن (مثال: `5000` أو `50k`)، أو `إلغاء` للتراجع"
        )

        def check(msg):
            return msg.author.id == ctx.author.id and msg.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.reply("⏳ انتهى الوقت، ألغيت طلب الزواج")
            return

        if msg.content.strip().lower() in ("إلغاء", "الغاء", "cancel"):
            await ctx.reply("❌ ألغيت طلب الزواج")
            return

        mahr = parse_amount(msg.content)
        if mahr < 100:
            await ctx.reply("❌ المهر غير صحيح (الحد الأدنى 100)")
            return

        conn = await get_connection()
        user = await get_user(conn, ctx.author.id)
        await conn.close()
        if user["wallet"] < mahr:
            await ctx.reply(f"❌ محفظتك ما تكفي، تحتاج {CURRENCY} {mahr:,}")
            return

        embed = discord.Embed(
            title="💍 طلب زواج!",
            description=(
                f"{ctx.author.mention} يطلب زواجك!\n"
                f"المهر: {CURRENCY} **{mahr:,}**\n"
                f"هل تقبل؟"
            ),
            color=0xF06292,
        )
        view = ProposalView(ctx.author, member, mahr)
        sent = await ctx.send(embed=embed, view=view)
        view.message = sent

        try:
            await member.send(
                f"💍 {ctx.author.display_name} يطلب زواجك بمهر {CURRENCY} {mahr:,}! "
                f"رد على الرسالة في السيرفر بقبول أو رفض"
            )
        except Exception:
            pass

    @commands.command(name="طلاق")
    async def divorce(self, ctx, times: str = None):
        conn = await get_connection()
        row = await get_marriage(conn, ctx.author.id)
        if not row:
            await conn.close()
            await ctx.reply("❌ انت مو متزوج أصلاً 😅")
            return
        partner_id = row["user2"] if row["user1"] == ctx.author.id else row["user1"]

        if times == "3":
            await conn.close()
            await ctx.reply(
                f"🔥🔥 {ctx.author.mention} يريد الطلاق **بثلاث**!\n"
                f"لتأكيد الطلاق بثلاث اكتب **`طلاق`** ثلاث مرات في الشات الآن"
            )

            def check(msg):
                return (
                    msg.author.id == ctx.author.id
                    and msg.channel.id == ctx.channel.id
                    and "طلاق" in msg.content
                )

            for i in range(3):
                try:
                    await self.bot.wait_for("message", check=check, timeout=30)
                    await ctx.send(f"✅ {i + 1}/3 — طلقة!")
                except asyncio.TimeoutError:
                    await ctx.send("⏳ ما أكدت الطلاق بالوقت، ألغيت العملية")
                    return

            conn = await get_connection()
            try:
                if not await get_marriage(conn, ctx.author.id):
                    await ctx.send("❌ مو متزوجين أصلاً 😅")
                    return
                await delete_marriage(conn, ctx.author.id)
                await add_divorce_block(conn, ctx.author.id, partner_id)
            finally:
                await conn.close()
            await ctx.send(
                f"🔥🔥🔥 **تم الطلاق بثلاث!**\n\n"
                f"قال: طلقتك، طلقتك، طلقتك... 💔\n"
                f"الزواج بين {ctx.author.mention} و <@{partner_id}> انتهى — "
                f"**ممنوع الزواج بينهم** إلا بعد تصالح (`-تصالح @شخص`) 🤝"
            )
            return

        partner = ctx.guild.get_member(partner_id)
        if partner is None:
            await delete_marriage(conn, ctx.author.id)
            await conn.close()
            await ctx.reply("✅ شريكك مش موجود في السيرفر، انفصلت تلقائياً")
            return

        embed = discord.Embed(
            title="🕊️ طلب طلاق",
            description=f"{ctx.author.mention} يريد الطلاق منك، هل توافق؟",
            color=0xE74C3C,
        )
        view = DivorceView(ctx.author, partner, conn)
        sent = await ctx.send(embed=embed, view=view)
        view.message = sent
        try:
            await partner.send(f"🕊️ {ctx.author.display_name} يريد الطلاق منك، وافق أو ارفض في السيرفر")
        except Exception:
            pass

    @commands.command(name="خلع")
    async def khul(self, ctx):
        conn = await get_connection()
        row = await get_marriage(conn, ctx.author.id)
        if not row:
            await conn.close()
            await ctx.reply("❌ انت مو متزوج أصلاً 😅")
            return
        partner_id = row["user2"] if row["user1"] == ctx.author.id else row["user1"]
        await conn.close()

        await ctx.reply(
            f"🩸 {ctx.author.mention} طلبت الخلع من زوجها!\n"
            f"لتأكيد الخلع اكتب **`خلع`** مرتين في الشات الآن"
        )

        def check(msg):
            return (
                msg.author.id == ctx.author.id
                and msg.channel.id == ctx.channel.id
                and "خلع" in msg.content
            )

        for i in range(2):
            try:
                await self.bot.wait_for("message", check=check, timeout=30)
                await ctx.send(f"✅ {i + 1}/2 — تم تأكيد الخلع، بقي تأكيد واحد!")
            except asyncio.TimeoutError:
                await ctx.reply("⏳ ما كتبت الخلع بالوقت، ألغيت العملية")
                return

        conn = await get_connection()
        try:
            if not await get_marriage(conn, ctx.author.id):
                await conn.close()
                await ctx.reply("❌ مو متزوجين أصلاً 😅")
                return
            await delete_marriage(conn, ctx.author.id)
        finally:
            await conn.close()

        await ctx.send(
            f"🩸🩸🩸 **تم الخلع!**\n\n"
            f"{ctx.author.mention} نطقت الخلع مرتين... وصار ينزل **دماء** 🩸💔\n"
            f"المرأة طلبت الخلع وتحررت — انتهى الزواج بينها وبين <@{partner_id}>"
        )

    @commands.command(name="تصالح")
    async def reconcile(self, ctx, member: discord.Member = None):
        if member is None:
            await ctx.reply("❌ حدد الشخص: `-تصالح @شخص`")
            return
        if member.id == ctx.author.id:
            await ctx.reply("❌ ما فيه تصالح مع نفسك 😄")
            return
        conn = await get_connection()
        if not await is_divorce_blocked(conn, ctx.author.id, member.id):
            await conn.close()
            await ctx.reply(
                f"❌ ما فيه منع زواج بينك وبين {member.mention} — ما تحتاجون تصالح 😅"
            )
            return
        await conn.close()

        embed = discord.Embed(
            title="🤝 طلب تصالح!",
            description=(
                f"{ctx.author.mention} يريد التصالح معك بعد الطلاق بثلاث 💔\n"
                f"هل تقبل ويفتح باب الزواج بينكم من جديد؟"
            ),
            color=0x2ECC71,
        )
        view = ReconcileView(ctx.author, member)
        sent = await ctx.send(embed=embed, view=view)
        view.message = sent


async def setup(bot):
    await bot.add_cog(Marriage(bot))

# ================== cogs/violations.py ==================



async def fetch_avatar(member):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(member.display_avatar.with_size(256).url)) as resp:
                return await resp.read()
    except Exception:
        return None


class Violations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="مخالفة")
    async def issue(self, ctx, member: discord.Member = None, *args):
        if not ctx.author.guild_permissions.administrator:
            await ctx.reply("❌ هذا الأمر للإدارة فقط 👑")
            return
        if member is None:
            await ctx.reply("❌ حدد الشخص: `-مخالفة @شخص [المبلغ] السبب`")
            return
        if member.bot:
            await ctx.reply("❌ هذا بوت 🤖")
            return

        amount = 0
        reason_parts = list(args)
        if reason_parts:
            parsed = parse_amount(reason_parts[0])
            if parsed > 0:
                amount = parsed
                reason_parts = reason_parts[1:]
        reason = " ".join(reason_parts).strip() or "مخالفة غير محددة"

        conn = await get_connection()
        await add_violation(conn, member.id, reason, amount, ctx.author.id)
        deducted = 0
        if amount > 0:
            user = await get_user(conn, member.id)
            deducted = min(user["wallet"], amount)
            await update_wallet(conn, member.id, -deducted)
        await conn.close()

        msg = (
            f"🚨 **تم تسجيل مخالفة على {member.mention}!**\n"
            f"السبب: **{reason}**\n"
        )
        if amount > 0:
            msg += f"الغرامة: {CURRENCY} **{amount:,}** — خصم من محفظته {CURRENCY} {deducted:,}\n"
        else:
            msg += "الغرامة: بدون خصم (تحذير)\n"
        msg += f"👮 سجلها: {ctx.author.mention}"
        await ctx.reply(msg)

    @commands.command(name="مخالفات")
    async def view(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        conn = await get_connection()
        violations = await get_violations(conn, member.id)
        await conn.close()
        total_fine = sum(v["amount"] for v in violations)
        avatar = await fetch_avatar(member)
        card = render_violations_card(
            member.display_name, avatar, violations, total_fine
        )
        embed = discord.Embed(
            title=f"🚨 سجل مخالفات {member.display_name}",
            color=0xE74C3C,
        )
        embed.set_image(url="attachment://violations.png")
        await safe_send(ctx, embed=embed, file=discord.File(card, "violations.png"))

    @commands.command(name="مخالفاتي")
    async def my_violations(self, ctx):
        conn = await get_connection()
        violations = await get_violations(conn, ctx.author.id)
        await conn.close()
        total_fine = sum(v["amount"] for v in violations)
        avatar = await fetch_avatar(ctx.author)
        card = render_violations_card(
            ctx.author.display_name, avatar, violations, total_fine
        )
        embed = discord.Embed(
            title=f"🚨 مخالفاتك يا {ctx.author.display_name}",
            color=0xE74C3C,
        )
        embed.set_image(url="attachment://violations.png")
        await safe_send(ctx, embed=embed, file=discord.File(card, "violations.png"))

    @commands.command(name="مسح مخالفات")
    async def clear(self, ctx, member: discord.Member = None):
        if not ctx.author.guild_permissions.administrator:
            await ctx.reply("❌ هذا الأمر للإدارة فقط 👑")
            return
        if member is None:
            await ctx.reply("❌ حدد الشخص: `-مسح مخالفات @شخص`")
            return
        conn = await get_connection()
        await clear_violations(conn, member.id)
        await conn.close()
        await ctx.reply(f"🧹 تم مسح كل مخالفات {member.mention} — سجل نظيف ✅")


async def setup(bot):
    await bot.add_cog(Violations(bot))

# ================== main.py ==================



intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

COGS = ["bank", "economy", "loans", "shop", "leaderboard", "guilds", "marriage", "violations"]

SLASH_COMMANDS = {"setchannel"}


@bot.tree.command(name="setchannel", description="تعيين قناة البنك")
@app_commands.describe(channel="القناة (اختياري — بدونها تستخدم القناة الحالية)")
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if interaction.guild is None:
        await interaction.response.send_message("❌ استخدم الأمر داخل السيرفر", ephemeral=True)
        return
    channel = channel or interaction.channel
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO guilds (guild_id, channel_id) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
        (interaction.guild.id, channel.id),
    )
    await conn.commit()
    await conn.close()
    embed = discord.Embed(
        title="✅ تم تعيين قناة البنك",
        description=f"القناة: {channel.mention}",
        color=COLOR,
    )
    embed.set_image(url="attachment://bank_banner.png")
    await interaction.response.send_message(
        embed=embed, file=discord.File("assets/bank_banner.png", "bank_banner.png")
    )


async def load_cogs():
    await bot.add_cog(Bank(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Loans(bot))
    await bot.add_cog(Shop(bot))
    await bot.add_cog(Leaderboard(bot))
    await bot.add_cog(Guilds(bot))
    await bot.add_cog(Marriage(bot))
    await bot.add_cog(Violations(bot))


@bot.event
async def on_ready():
    print(f"✅ تم تسجيل الدخول: {bot.user} (ID: {bot.user.id})")
    for cmd in list(bot.tree.get_commands(guild=None)):
        if cmd.name not in SLASH_COMMANDS:
            bot.tree.remove_command(cmd.name, guild=None)
    for guild in bot.guilds:
        for cmd in list(bot.tree.get_commands(guild=guild)):
            if cmd.name not in SLASH_COMMANDS:
                bot.tree.remove_command(cmd.name, guild=guild)
    await bot.tree.sync()
    print("🗑️ تم حذف السيلاش القديمة (مع إبقاء أوامرنا)")
    await init_db()
    print("🗄️ قاعدة البيانات جاهزة")
    guilds = [f"{g.name} ({g.id})" for g in bot.guilds]
    print(f"🛡️ المتصل بـ {len(guilds)} سيرفر: {', '.join(guilds) if guilds else 'لا شيء!'}")

    if not interest_task.is_running():
        interest_task.start()
        print("💸 تم تشغيل نظام الفوائد على الودائع")
    if not heartbeat.is_running():
        heartbeat.start()
    print("✅ البوت جاهز!")


@tasks.loop(seconds=30)
async def heartbeat():
    print("[HEARTBEAT] alive")


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.content:
        print(f"[MSG] {message.author} ({message.guild.name if message.guild else 'DM'}): {message.content[:80]}")
    if message.guild and message.content.startswith(PREFIX):
        cmd = message.content[len(PREFIX):].strip().split()[0].lower() if message.content.strip() else ""
        if cmd and cmd != "رصيد":
            conn = await get_connection()
            try:
                bank_channel = await get_guild_channel(conn, message.guild.id)
            finally:
                await conn.close()
            if bank_channel and message.channel.id != bank_channel:
                await message.reply(
                    f"🔒 هذي الأوامر تسخدمها في قناة البنك فقط <#{bank_channel}>\n"
                    f"أما `-رصيد` فيشتغل في أي شانيل ✅",
                    delete_after=8,
                )
                return
    await bot.process_commands(message)


@bot.event
async def on_message_delete(message):
    if not message.guild or message.author is None:
        return
    try:
        if message.author.id == bot.user.id:

            restored = await restore(message)
            print(
                f"{'🛡️ أعد البوت رسالته المحذوفة' if restored else '🗑️ انحذفت رسالة بوت بدون حفظ'} "
                f"في {message.guild.name}/{message.channel.name}"
            )
        elif message.content and message.content.startswith(PREFIX):
            print(f"⚠️ انحذفت رسالة عضو في {message.guild.name}: {message.author} -> {message.content[:60]}")
    except Exception:
        pass


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        secs = int(error.retry_after)
        msg = "ثانية" if secs < 60 else f"{round(secs / 60, 1)} دقيقة"
        await ctx.reply(f"⏳ الأمر في تبريد، انتظر {msg}", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("❌ استخدم الأمر بشكل صحيح، جرّب `-مساعدة`", delete_after=10)
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("❌ المدخل غير صحيح", delete_after=10)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply("❌ ما لقيت العضو المطلوب", delete_after=10)
    else:

        print(f"⚠️ خطأ: {type(error).__name__}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)


async def main():
    if not TOKEN:
        print("❌ ما لقيت التوكن! تأكد أن ملف bot.env موجود بجانب المجلد وفيه DISCORD_TOKEN=...")
        return
    print("keep_alive مدمج - غير مفعل في نسخة الملف الواحد")
    await load_cogs()
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
