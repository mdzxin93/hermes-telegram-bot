#!/usr/bin/env python3
"""
Telegram Bot Wrapper for Hermes Agent
====================================
Integrates NousResearch Hermes Agent with Telegram using python-telegram-bot.
Features:
- Strict authorization via TELEGRAM_ALLOWED_USER_ID.
- Per-chat persistent Hermes AIAgent instance.
- Chat action (typing) indicator during agent deliberation and tool calls.
- Automatic message chunking for responses exceeding Telegram's 4096-character limit.
- Markdown / HTML safe delivery with automatic fallback to plain text.
- Commands: /start, /help, /reset, /status.
"""

import os
import sys
import asyncio
import logging
from typing import Dict, Optional, Set
from pathlib import Path
from dotenv import load_dotenv

# Ensure UTF-8 stdio on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("HermesTelegramBot")

# Load environment variables (.env in workspace and parent paths)
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    logger.info("Loaded environment from %s", env_path)
else:
    load_dotenv()

# Verify telegram library
try:
    from telegram import Update, constants
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        filters,
    )
except ImportError:
    logger.critical("python-telegram-bot is not installed. Please run: pip install 'python-telegram-bot>=21.0,<22'")
    sys.exit(1)

# Import Hermes AIAgent
try:
    from run_agent import AIAgent
    from hermes_constants import get_hermes_home
except ImportError as e:
    logger.critical("Failed to import Hermes Agent modules: %s", e)
    sys.exit(1)


# Maximum characters per Telegram message chunk (safe margin under 4096)
MAX_MESSAGE_CHUNK = 4000


class HermesTelegramBridge:
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.allowed_user_ids: Set[int] = self._load_allowed_user_ids()
        self.default_model = os.getenv("HERMES_MODEL", "").strip()
        self.default_provider = os.getenv("HERMES_PROVIDER", "").strip() or None
        self.base_url = os.getenv("HERMES_BASE_URL", "").strip() or None
        self.api_key = os.getenv("HERMES_API_KEY", "").strip() or None
        
        # Per-chat active AIAgent sessions: chat_id -> AIAgent
        self.active_agents: Dict[int, AIAgent] = {}
        self.agent_locks: Dict[int, asyncio.Lock] = {}

    def _load_allowed_user_ids(self) -> Set[int]:
        raw = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
        if not raw:
            logger.warning("⚠️ TELEGRAM_ALLOWED_USER_ID is not configured! Bot will reject all user messages.")
            return set()
        ids = set()
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
            elif part.startswith("-") and part[1:].isdigit():
                ids.add(int(part))
        logger.info("Configured %d authorized Telegram user ID(s): %s", len(ids), list(ids))
        return ids

    def is_authorized(self, user_id: int) -> bool:
        if not self.allowed_user_ids:
            return False
        return user_id in self.allowed_user_ids

    def claim_owner_if_unclaimed(self, user_id: int, username: str = "") -> bool:
        """If no owner is configured yet, bind the first user as the sole administrator and persist to .env."""
        if self.allowed_user_ids:
            return user_id in self.allowed_user_ids

        self.allowed_user_ids.add(user_id)
        logger.info("🎉 First-User Auto-Claim! Binding bot administrator to user_id=%s (@%s)", user_id, username)

        try:
            env_path = Path(__file__).resolve().parent / ".env"
            lines = []
            if env_path.exists():
                lines = env_path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            found = False
            for line in lines:
                if line.startswith("TELEGRAM_ALLOWED_USER_ID="):
                    new_lines.append(f"TELEGRAM_ALLOWED_USER_ID={user_id}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"TELEGRAM_ALLOWED_USER_ID={user_id}")
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            logger.info("Persisted TELEGRAM_ALLOWED_USER_ID=%s to %s", user_id, env_path)
        except Exception as e:
            logger.error("Failed to write TELEGRAM_ALLOWED_USER_ID to .env: %s", e)

        return True

    def has_llm_key(self) -> bool:
        for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HERMES_API_KEY"):
            val = os.getenv(key, "").strip()
            if val and not val.startswith("your_") and not val.startswith("YOUR_") and "here" not in val:
                return True
        return False

    def get_or_create_agent(self, chat_id: int, user_id: int, user_name: str = "") -> AIAgent:
        """Instantiate or retrieve the Hermes agent for a chat."""
        if chat_id in self.active_agents:
            return self.active_agents[chat_id]

        kwargs = {
            "platform": "telegram",
            "chat_id": str(chat_id),
            "user_id": str(user_id),
            "user_name": user_name,
            "quiet_mode": True,
        }
        if self.default_model:
            kwargs["model"] = self.default_model
        if self.default_provider:
            kwargs["provider"] = self.default_provider
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.api_key:
            kwargs["api_key"] = self.api_key

        logger.info("Initializing fresh Hermes AIAgent for chat_id=%s (user=%s)", chat_id, user_name)
        agent = AIAgent(**kwargs)
        self.active_agents[chat_id] = agent
        return agent

    def reset_agent(self, chat_id: int):
        """Cleanly close and reset the agent session for a chat."""
        if chat_id in self.active_agents:
            agent = self.active_agents.pop(chat_id)
            try:
                agent.close()
                logger.info("Closed Hermes AIAgent for chat_id=%s", chat_id)
            except Exception as e:
                logger.warning("Error closing agent for chat_id=%s: %s", chat_id, e)

    async def send_typing_loop(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, stop_event: asyncio.Event):
        """Continuously sends TYPING chat action while agent is running."""
        while not stop_event.is_set():
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                continue

    @staticmethod
    def chunk_text(text: str, max_chunk: int = MAX_MESSAGE_CHUNK) -> list[str]:
        """Splits long text safely into message chunks preserving paragraph breaks."""
        if not text:
            return [""]
        if len(text) <= max_chunk:
            return [text]
        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= max_chunk:
                chunks.append(remaining)
                break
            # Try finding last newline within max_chunk
            split_idx = remaining.rfind("\n", 0, max_chunk)
            if split_idx <= 0:
                # Try finding last space within max_chunk
                split_idx = remaining.rfind(" ", 0, max_chunk)
            if split_idx <= 0:
                # Hard cut at max_chunk
                split_idx = max_chunk

            chunk = remaining[:split_idx].strip()
            if chunk:
                chunks.append(chunk)
            # Advance remaining past split_idx guaranteed
            remaining = remaining[split_idx:].lstrip("\r\n ")
        return chunks

    async def reply_chunks(self, update: Update, text: str):
        """Sends text in chunks with markdown fallback."""
        chunks = self.chunk_text(text)
        for chunk in chunks:
            try:
                await update.effective_message.reply_text(
                    chunk,
                    parse_mode=constants.ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
            except Exception as md_err:
                logger.debug("Markdown parse failed (%s), sending as plain text", md_err)
                await update.effective_message.reply_text(
                    chunk,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )


bridge = HermesTelegramBridge()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command with auto-claim support."""
    user = update.effective_user
    user_id = user.id if user else 0
    username = user.username or user.first_name or "there"

    was_unclaimed = len(bridge.allowed_user_ids) == 0
    if was_unclaimed:
        bridge.claim_owner_if_unclaimed(user_id, username)

    if not bridge.is_authorized(user_id):
        logger.warning("Unauthorized access attempt on /start: user_id=%s username=%s", user_id, username)
        await update.effective_message.reply_text(
            f"⛔ *Access Denied*\n\n"
            f"Your Telegram User ID is `{user_id}`.\n"
            f"You are not authorized to use this Hermes Agent instance.",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    if was_unclaimed:
        welcome_msg = (
            f"🎉 *Hermes Agent Claimed & Paired!*\n\n"
            f"Welcome, *{username}*! Your Telegram account (ID: `{user_id}`) is now successfully registered as the sole administrator.\n\n"
        )
    else:
        welcome_msg = f"🤖 *Hermes Agent Online*\n\nHello, *{username}*! I am your personal Hermes AI Agent running 24/7.\n\n"

    if not bridge.has_llm_key():
        welcome_msg += (
            "⚠️ *Action Required: Set LLM API Key*\n"
            "Hermes is connected to your Telegram bot, but needs an LLM API key to generate responses.\n\n"
            "You can set your key right here by sending:\n"
            "`/key sk-or-v1-xxxx...` (for OpenRouter)\n"
            "or `/key OPENAI_API_KEY sk-proj-xxxx...` (for OpenAI)\n\n"
        )
    else:
        welcome_msg += "Send me any task or question to get started!\n\n"

    welcome_msg += (
        "• *Commands:*\n"
        "  `/start` - Show this greeting\n"
        "  `/status` - Check agent & model status\n"
        "  `/key <api_key>` - Set or update your LLM API key\n"
        "  `/reset` - Clear context and start a fresh session\n"
        "  `/help` - View usage guide"
    )
    await update.effective_message.reply_text(welcome_msg, parse_mode=constants.ParseMode.MARKDOWN)


async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows the authorized owner to set or update their LLM API key directly from Telegram."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not bridge.is_authorized(user_id):
        return

    args = context.args
    if not args:
        await update.effective_message.reply_text(
            "🔑 *Set LLM API Key*\n\n"
            "Usage:\n"
            "`/key sk-or-v1-xxxx...` (defaults to OpenRouter)\n"
            "or `/key OPENAI_API_KEY sk-xxxx...`\n"
            "or `/key ANTHROPIC_API_KEY sk-ant-xxxx...`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    raw_input = args[0].strip()
    key_name = "OPENROUTER_API_KEY"
    key_val = raw_input

    if len(args) >= 2:
        key_name = args[0].strip().upper()
        key_val = args[1].strip()
    elif raw_input.startswith("sk-ant-"):
        key_name = "ANTHROPIC_API_KEY"
    elif raw_input.startswith("sk-proj-") or (raw_input.startswith("sk-") and not raw_input.startswith("sk-or-")):
        key_name = "OPENAI_API_KEY"

    # Set in os.environ
    os.environ[key_name] = key_val

    # Write to .env
    env_path = Path(__file__).resolve().parent / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith(f"{key_name}="):
            new_lines.append(f"{key_name}={key_val}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key_name}={key_val}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Reset any active agents to load new key
    chat_id = update.effective_chat.id
    bridge.reset_agent(chat_id)

    await update.effective_message.reply_text(
        f"✅ *{key_name} Saved Successfully!*\n\n"
        f"Hermes Agent is now fully operational. Send any message to begin!",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not bridge.is_authorized(user_id):
        return

    help_msg = (
        f"📖 *Hermes Agent Usage Guide*\n\n"
        f"Hermes is an autonomous agent capable of web search, terminal execution, "
        f"code interpretation, browsing, memory retention, and tool use.\n\n"
        f"• *Chatting:* Simply type your prompt directly.\n"
        f"• *Context:* Your conversation history is maintained continuously.\n"
        f"• *Session Reset:* If you want to start a new topic from scratch, send `/reset`.\n"
        f"• *Set API Key:* Send `/key <your_api_key>` to update your provider key.\n"
        f"• *Diagnostics:* Run `/status` to verify current model and runtime health."
    )
    await update.effective_message.reply_text(help_msg, parse_mode=constants.ParseMode.MARKDOWN)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /reset or /clear command."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not bridge.is_authorized(user_id):
        return

    chat_id = update.effective_chat.id
    bridge.reset_agent(chat_id)
    await update.effective_message.reply_text(
        "🔄 *Session Reset*\n\nAgent memory context for this chat has been reset. Ready for a fresh task!",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /status command."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not bridge.is_authorized(user_id):
        return

    chat_id = update.effective_chat.id
    agent = bridge.active_agents.get(chat_id)
    
    session_id = agent.session_id if agent else "No active turn yet"
    model = (agent.model if agent else bridge.default_model) or "Default Provider Model"
    provider = (agent.provider if agent else bridge.default_provider) or "auto"
    tool_count = len(agent.tools) if agent and hasattr(agent, "tools") else "Auto-discovered"
    has_key = "Configured ✓" if bridge.has_llm_key() else "Missing ⚠️ (use /key to set)"

    status_msg = (
        f"📊 *Hermes Agent Status*\n\n"
        f"• *Status:* 🟢 Running 24/7\n"
        f"• *LLM Key:* {has_key}\n"
        f"• *Model:* `{model}`\n"
        f"• *Provider:* `{provider}`\n"
        f"• *Active Tools:* `{tool_count}`\n"
        f"• *Session ID:* `{session_id}`\n"
        f"• *Chat ID:* `{chat_id}`"
    )
    await update.effective_message.reply_text(status_msg, parse_mode=constants.ParseMode.MARKDOWN)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all inbound text messages from the authorized user."""
    if not update.effective_message or not update.effective_message.text:
        return

    user = update.effective_user
    user_id = user.id if user else 0
    username = user.username or user.first_name or "user"
    chat_id = update.effective_chat.id
    user_text = update.effective_message.text.strip()

    if not bridge.allowed_user_ids:
        bridge.claim_owner_if_unclaimed(user_id, username)

    # Strict authorization check
    if not bridge.is_authorized(user_id):
        logger.warning("Unauthorized message blocked from user_id=%s username=%s: %r", user_id, username, user_text[:60])
        await update.effective_message.reply_text(
            f"⛔ *Access Denied*\n\n"
            f"Your Telegram User ID is `{user_id}`.\n"
            f"This Hermes Agent instance is restricted to authorized users only.",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    # Check for LLM key
    if not bridge.has_llm_key():
        await update.effective_message.reply_text(
            "⚠️ *LLM API Key Required*\n\n"
            "Hermes is connected to your bot, but requires an LLM API key to generate responses.\n\n"
            "You can set your key right here by sending:\n"
            "`/key sk-or-v1-xxxx...` (for OpenRouter)\n"
            "or `/key OPENAI_API_KEY sk-xxxx...` (for OpenAI)",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    # Per-chat lock to avoid concurrent turns in the same conversation
    if chat_id not in bridge.agent_locks:
        bridge.agent_locks[chat_id] = asyncio.Lock()

    async with bridge.agent_locks[chat_id]:
        # Background typing loop
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(bridge.send_typing_loop(chat_id, context, stop_typing))

        try:
            logger.info("Processing message for chat_id=%s from %s: %s", chat_id, username, user_text[:80])
            
            # Retrieve or instantiate agent
            agent = bridge.get_or_create_agent(chat_id=chat_id, user_id=user_id, user_name=username)

            # Run agent conversation turn in executor to avoid blocking the asyncio event loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, agent.run_conversation, user_text)

            final_response = result.get("final_response") if isinstance(result, dict) else str(result)
            if not final_response:
                final_response = "*(No response generated by the agent)*"

            stop_typing.set()
            await typing_task

            await bridge.reply_chunks(update, final_response)

        except Exception as e:
            stop_typing.set()
            await typing_task
            logger.error("Error executing Hermes agent turn for chat_id=%s: %s", chat_id, e, exc_info=True)
            err_msg = (
                f"⚠️ *Hermes Error*\n\n"
                f"An error occurred while processing your message:\n`{type(e).__name__}: {str(e)}`\n\n"
                f"You can try resetting the session with `/reset`."
            )
            await update.effective_message.reply_text(err_msg, parse_mode=constants.ParseMode.MARKDOWN)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set in environment or .env!\n"
            "Please create a bot via @BotFather on Telegram and set TELEGRAM_BOT_TOKEN in your .env file."
        )
        sys.exit(1)

    async def on_startup(app: Application):
        raw_port = os.getenv("PORT", "").strip()
        if raw_port and raw_port.isdigit():
            port = int(raw_port)
            async def handle_http(reader, writer):
                try:
                    await reader.read(512)
                except Exception:
                    pass
                body = '{"status":"healthy","bot":"@Hsbzbz_bot","service":"hermes-agent"}\n'
                response = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"Connection: close\r\n\r\n"
                    f"{body}"
                )
                try:
                    writer.write(response.encode("utf-8"))
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

            await asyncio.start_server(handle_http, "0.0.0.0", port)
            logger.info("🌐 Cloud HTTP Health Check listening on 0.0.0.0:%s", port)

    application = Application.builder().token(token).post_init(on_startup).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("key", key_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("clear", reset_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    logger.info("🚀 Hermes Telegram Bot is polling and ready to serve 24/7.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
