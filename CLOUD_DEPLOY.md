# 🚀 24/7 Hermes Agent Telegram Bot Cloud Deployment

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/mdzxin93/hermes-telegram-bot)
[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/new?template=https://github.com/mdzxin93/hermes-telegram-bot)

Deploy NousResearch **Hermes Agent** as an autonomous 24/7 Telegram bot connected to [@Hsbzbz_bot](https://t.me/Hsbzbz_bot).

---

## ⚡ 1-Click Cloud Deployment (Render.com)

1. Click the button above: **[Deploy to Render](https://render.com/deploy?repo=https://github.com/mdzxin93/hermes-telegram-bot)**.
2. Sign in with your GitHub account (`mdzxin93`).
3. Render will automatically detect `render.yaml` and configure the service.
4. Set your environment variables:
   - `TELEGRAM_BOT_TOKEN`: `8968385636:AAGdU5sXiltqO39ryXiNPlEv8gMwvk9SEBQ`
   - `OPENROUTER_API_KEY`: *(paste your OpenRouter or OpenAI API key)*
5. Click **Apply / Deploy**.

Once deployed, Render keeps the bot running in the cloud 24/7! Even if your PC is shut down, you can message [@Hsbzbz_bot](https://t.me/Hsbzbz_bot) anytime.

---

## ⚡ 1-Click Cloud Deployment (Railway.app)

1. Go to [railway.app](https://railway.app) and click **"Login with GitHub"**.
2. Click **"New Project"** -> **"Deploy from GitHub repo"**.
3. Select `mdzxin93/hermes-telegram-bot`.
4. Under **Variables**, add:
   - `TELEGRAM_BOT_TOKEN` = `8968385636:AAGdU5sXiltqO39ryXiNPlEv8gMwvk9SEBQ`
   - `OPENROUTER_API_KEY` = `your_key_here`
5. Click **Deploy**.

---

## 🖥️ Self-Hosted Cloud VPS (Ubuntu Linux)

If deploying to your own remote server:

```bash
git clone https://github.com/mdzxin93/hermes-telegram-bot.git
cd hermes-telegram-bot
bash deploy-cloud.sh
```
