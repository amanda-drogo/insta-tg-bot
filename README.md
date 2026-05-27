# 🎬 Instagram Downloader Telegram Bot

A Telegram bot that downloads **reels, videos, photos, stories, profile pictures, and entire profiles** from Instagram.

Paste links (even concatenated without spaces!) and the bot handles everything.

---

## ✨ Features

| Feature | How to use |
|---|---|
| 🎬 Reel / Video | Paste the link |
| 🖼 Photo / Carousel | Paste the link |
| 📖 Story | Paste the story link (needs IG login) |
| 📸 HD Profile Picture | `/pfp username` |
| 👤 Full Profile Download | `/profile username` or paste profile link |
| 🔗 Bulk Download | Paste many links at once (even without spaces!) |
| 🗜 Auto-compression | Videos > 50 MB are compressed with ffmpeg |

---

## 🚀 Setup

### 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **API token** — you'll need it

### 2. Get your Telegram User ID (optional)

If you want to restrict the bot to yourself:
1. Search for **@userinfobot** on Telegram
2. Send it any message — it replies with your user ID

### 3. Deploy on Render (Free)

1. Push this folder to a **GitHub repository**

2. Go to [render.com](https://render.com) → **New → Web Service**

3. Connect your GitHub repo

4. Settings:
   - **Runtime**: Docker
   - **Plan**: Free

5. Add these **Environment Variables**:

   | Variable | Value |
   |---|---|
   | `BOT_TOKEN` | Your Telegram bot token |
   | `WEBHOOK_URL` | `https://your-app-name.onrender.com` |
   | `INSTA_USERNAME` | (optional) Instagram username for stories |
   | `INSTA_PASSWORD` | (optional) Instagram password for stories |
   | `ALLOWED_USERS` | (optional) Comma-separated Telegram user IDs |
   | `MAX_PROFILE_POSTS` | (optional) Default: 50 |

6. Click **Deploy**

### 4. Keep it alive with UptimeRobot

Render free tier sleeps after 15 min of inactivity. Fix this:

1. Go to [uptimerobot.com](https://uptimerobot.com) (free account)
2. Create a new monitor:
   - **Type**: HTTP(s)
   - **URL**: `https://your-app-name.onrender.com/health`
   - **Interval**: 5 minutes
3. That's it! The bot will stay awake 24/7.

---

## 🛠 Local Development

```bash
# Clone the repo
cd insta-tg-bot

# Create a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BOT_TOKEN="your-token"
export WEBHOOK_URL=""   # leave empty for polling mode (TODO)

# Run
python bot.py
```

> **Note**: For local development, you'll need a public URL (use [ngrok](https://ngrok.com)) or modify the bot to use polling mode.

---

## 📱 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Feature list and usage guide |
| `/pfp <username>` | Download HD profile picture |
| `/profile <username>` | Download all posts from a profile |
| *Just paste link(s)* | Auto-download any Instagram content |

---

## 🧪 How the Smart URL Parser Works

User pastes this mess:
```
https://instagram.com/reel/ABC123/?igsh=xxhttps://instagram.com/p/XYZ789/https://instagram.com/stories/user/12345
```

Bot automatically splits it into 3 separate URLs and downloads each one.

---

## ⚠️ Limitations

- **Telegram file limit**: 50 MB max — large videos are auto-compressed
- **Stories**: Require Instagram login (`INSTA_USERNAME` + `INSTA_PASSWORD`)
- **Private profiles**: Only work if the logged-in account follows them
- **Rate limits**: Instagram may temporarily block if too many requests are made
- **Render free tier**: 512 MB RAM — very large profiles may hit memory limits

---

## 📂 Project Structure

```
insta-tg-bot/
├── bot.py              # Main entry — Telegram handlers + webhook server
├── downloader.py       # yt-dlp + instaloader download engine
├── url_parser.py       # Smart URL splitter & classifier
├── config.py           # Environment variable loader
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container for Render
├── render.yaml         # Render deployment config
├── .env.example        # Example environment variables
└── README.md           # This file
```

---

## 📄 License

MIT — do whatever you want with it.
