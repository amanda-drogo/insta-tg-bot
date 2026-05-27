"""
Instagram Downloader Telegram Bot
──────────────────────────────────
Send any Instagram link (or a bunch pasted together) and the bot
downloads and sends the content right back.

Runs in webhook mode on Render (free tier) with a health-check endpoint
for UptimeRobot.
"""
import logging
import os

from aiohttp import web
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import (
    BOT_TOKEN,
    WEBHOOK_URL,
    PORT,
    INSTA_USERNAME,
    INSTA_PASSWORD,
    ALLOWED_USERS,
    MAX_PROFILE_POSTS,
    MAX_TELEGRAM_FILE_SIZE,
)
from url_parser import (
    extract_instagram_urls,
    classify_url,
    extract_shortcode,
    extract_username,
    extract_story_info,
    URLType,
)
from downloader import InstaDownloader, compress_video, DownloadResult

# ─── Logging ────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")

# ─── Downloader singleton ───────────────────────────────────

downloader = InstaDownloader(INSTA_USERNAME, INSTA_PASSWORD)

# ─── Access control ─────────────────────────────────────────


def _is_allowed(user_id: int) -> bool:
    """Return True if the user is authorized (or if no restriction is set)."""
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


# ─── Sending helpers ────────────────────────────────────────


async def _send_media(update: Update, result: DownloadResult):
    """Send all files from a DownloadResult, then clean up."""
    try:
        for mf in result.files:
            file_size = os.path.getsize(mf.path)

            if mf.media_type == "video":
                # Compress if too big
                final_path = compress_video(mf.path)
                final_size = os.path.getsize(final_path)

                if final_size > MAX_TELEGRAM_FILE_SIZE:
                    await update.message.reply_text(
                        f"⚠️ Video is too large ({final_size // (1024*1024)} MB) even after compression. "
                        "Telegram limits files to 50 MB."
                    )
                    continue

                with open(final_path, "rb") as f:
                    await update.message.reply_video(
                        video=f,
                        read_timeout=120,
                        write_timeout=120,
                        supports_streaming=True,
                    )
            else:
                if file_size > MAX_TELEGRAM_FILE_SIZE:
                    # Send large photo as document
                    with open(mf.path, "rb") as f:
                        await update.message.reply_document(document=f)
                else:
                    with open(mf.path, "rb") as f:
                        await update.message.reply_photo(photo=f)
    finally:
        result.cleanup()


# ─── Command handlers ───────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return

    text = (
        "🎬 *Instagram Downloader Bot*\n\n"
        "Send me any Instagram link and I'll download it\\!\n\n"
        "*Features:*\n"
        "📥  Reels, Videos, IGTV\n"
        "🖼  Photos \\& Carousel posts\n"
        "👤  Entire profile \\(all posts \\+ pfp\\)\n"
        "📸  HD Profile Picture\n"
        "📖  Stories \\(needs login\\)\n\n"
        "*Commands:*\n"
        "`/pfp username` — profile picture\n"
        "`/profile username` — all profile content\n"
        "`/help` — detailed help\n\n"
        "💡 *Pro tip:* paste multiple links at once, even without spaces\\!"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return

    text = (
        "📖 *How to use this bot:*\n\n"
        "*1\\. Individual downloads*\n"
        "Just paste any Instagram link:\n"
        "• Reel / Video / IGTV link\n"
        "• Photo / Post link\n"
        "• Story link \\(requires bot login\\)\n\n"
        "*2\\. Bulk downloads*\n"
        "Paste multiple links at once — even without spaces\\!\n"
        "The bot will split them and download each one\\.\n\n"
        "*3\\. Profile download*\n"
        "Send `/profile username` or paste a profile link\\.\n"
        "Downloads ALL photos, videos, and the profile picture\\.\n\n"
        "*4\\. Profile picture only*\n"
        "Send `/pfp username` to get the HD profile pic\\.\n\n"
        "*Limits:*\n"
        f"• Max {MAX_PROFILE_POSTS} posts per profile\n"
        "• Videos over 50 MB are auto\\-compressed\n"
        "• Stories require Instagram login on the bot"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_pfp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Usage: /pfp <username>\nExample: /pfp cristiano")
        return

    username = context.args[0].lstrip("@").strip()
    if "instagram.com" in username:
        username = extract_username(username)

    status = await update.message.reply_text(f"📸 Downloading profile picture of @{username}…")

    try:
        result = await downloader.download_profile_pic(username)
        await _send_media(update, result)
        await status.edit_text(f"✅ Profile picture of @{username}")
    except Exception as exc:
        await status.edit_text(f"❌ {exc}")
        logger.exception("pfp download failed for %s", username)


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /profile <username>\nExample: /profile cristiano"
        )
        return

    raw = context.args[0].strip().lstrip("@")
    username = extract_username(raw) if "instagram.com" in raw else raw

    status = await update.message.reply_text(
        f"👤 Downloading profile @{username}…\n"
        f"⏳ This may take a while (up to {MAX_PROFILE_POSTS} posts)."
    )

    try:
        result = await downloader.download_profile(username, max_posts=MAX_PROFILE_POSTS)
        total = len(result.files)
        await status.edit_text(f"📤 Sending {total} files from @{username}…")

        # Send in batches so we can update progress
        sent = 0
        try:
            for mf in result.files:
                try:
                    file_size = os.path.getsize(mf.path)
                    if mf.media_type == "video":
                        final_path = compress_video(mf.path)
                        final_size = os.path.getsize(final_path)
                        if final_size > MAX_TELEGRAM_FILE_SIZE:
                            continue
                        with open(final_path, "rb") as f:
                            await update.message.reply_video(
                                video=f,
                                read_timeout=120,
                                write_timeout=120,
                                supports_streaming=True,
                            )
                    else:
                        if file_size > MAX_TELEGRAM_FILE_SIZE:
                            with open(mf.path, "rb") as f:
                                await update.message.reply_document(document=f)
                        else:
                            with open(mf.path, "rb") as f:
                                await update.message.reply_photo(photo=f)
                    sent += 1
                    if sent % 10 == 0:
                        await status.edit_text(
                            f"📤 Sent {sent}/{total} from @{username}…"
                        )
                except Exception:
                    continue
        finally:
            result.cleanup()

        await status.edit_text(f"✅ Done! Sent {sent} files from @{username}")

    except Exception as exc:
        await status.edit_text(f"❌ {exc}")
        logger.exception("profile download failed for %s", username)


# ─── Message handler (auto-detect links) ────────────────────


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detect Instagram URLs in any text message and download them."""
    if not update.message or not update.message.text:
        return
    if not _is_allowed(update.effective_user.id):
        return

    text = update.message.text
    urls = extract_instagram_urls(text)
    if not urls:
        return

    total = len(urls)
    status = await update.message.reply_text(
        f"🔍 Found {total} Instagram link{'s' if total > 1 else ''}. Downloading…"
    )

    success = 0
    failed = 0

    for idx, url in enumerate(urls, 1):
        url_type = classify_url(url)

        try:
            if url_type in (URLType.REEL, URLType.POST):
                if total > 1:
                    await status.edit_text(f"⬇️ Downloading {idx}/{total}…")

                shortcode = extract_shortcode(url)
                result = await downloader.download_post(url, shortcode)
                await _send_media(update, result)
                success += 1

            elif url_type == URLType.STORY:
                if total > 1:
                    await status.edit_text(f"📖 Downloading story {idx}/{total}…")

                username, story_id = extract_story_info(url)
                if not username:
                    await update.message.reply_text(f"⚠️ Could not parse story URL:\n{url}")
                    failed += 1
                    continue

                result = await downloader.download_story(username, story_id)
                await _send_media(update, result)
                success += 1

            elif url_type == URLType.PROFILE:
                username = extract_username(url)
                await status.edit_text(
                    f"👤 Downloading profile @{username} ({idx}/{total})…\n"
                    f"⏳ Up to {MAX_PROFILE_POSTS} posts."
                )

                # Profile pic first
                try:
                    pfp_result = await downloader.download_profile_pic(username)
                    for mf in pfp_result.files:
                        with open(mf.path, "rb") as f:
                            await update.message.reply_photo(
                                photo=f,
                                caption=f"📸 Profile picture — @{username}",
                            )
                    pfp_result.cleanup()
                except Exception:
                    pass

                result = await downloader.download_profile(
                    username, max_posts=MAX_PROFILE_POSTS
                )
                await _send_media(update, result)
                success += 1

            else:
                await update.message.reply_text(f"⚠️ Couldn't recognise this link:\n{url}")
                failed += 1

        except Exception as exc:
            failed += 1
            await update.message.reply_text(f"❌ Link {idx} failed: {exc}")
            logger.exception("download failed for %s", url)

    # Final summary
    if total == 1:
        if success:
            await status.edit_text("✅ Done!")
        else:
            await status.edit_text("❌ Download failed.")
    else:
        await status.edit_text(
            f"✅ Finished! {success} downloaded, {failed} failed (out of {total})"
        )


# ─── Webhook + health-check web server ──────────────────────

# Build the Telegram Application globally so the webhook handler can use it
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("help", cmd_help))
app.add_handler(CommandHandler("pfp", cmd_pfp))
app.add_handler(CommandHandler("profile", cmd_profile))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


async def _health(request: web.Request) -> web.Response:
    """GET / or /health — keeps Render (and UptimeRobot) happy."""
    return web.json_response({"status": "alive", "bot": "InstaDownloaderBot"})


async def _webhook(request: web.Request) -> web.Response:
    """POST /webhook — receives Telegram updates."""
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return web.Response(status=200)


async def _on_startup(webapp: web.Application):
    """Initialize the Telegram bot and register the webhook."""
    await app.initialize()
    await app.start()
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await app.bot.set_webhook(url=webhook_url)
    logger.info("Webhook set → %s", webhook_url)


async def _on_shutdown(webapp: web.Application):
    """Graceful shutdown."""
    await app.stop()
    await app.shutdown()


def main():
    if not BOT_TOKEN:
        raise SystemExit("❌  BOT_TOKEN environment variable is not set!")

    webapp = web.Application()
    webapp.router.add_get("/", _health)
    webapp.router.add_get("/health", _health)
    webapp.router.add_post("/webhook", _webhook)
    webapp.on_startup.append(_on_startup)
    webapp.on_shutdown.append(_on_shutdown)

    logger.info("Starting bot on port %d …", PORT)
    web.run_app(webapp, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
