"""
Configuration — loads all settings from environment variables.
"""
import os

# ─── Telegram ───────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")          # e.g. https://insta-tg-bot.onrender.com
PORT = int(os.getenv("PORT", "8443"))

# ─── Instagram credentials (needed for stories & private profiles) ──
INSTA_USERNAME = os.getenv("INSTA_USERNAME", "")
INSTA_PASSWORD = os.getenv("INSTA_PASSWORD", "")

# ─── Access control ─────────────────────────────────────────
# Comma-separated Telegram user IDs.  Empty = open to everyone.
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = set()
if ALLOWED_USERS_RAW.strip():
    ALLOWED_USERS = {int(uid.strip()) for uid in ALLOWED_USERS_RAW.split(",") if uid.strip()}

# ─── Limits ─────────────────────────────────────────────────
MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024   # 50 MB (Telegram Bot API limit)
MAX_PROFILE_POSTS = int(os.getenv("MAX_PROFILE_POSTS", "50"))   # cap for /profile
DOWNLOAD_DIR = "/tmp/insta_downloads"
