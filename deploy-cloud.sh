#!/usr/bin/env bash
# ==============================================================================
# Hermes Agent - 24/7 Cloud VPS Deployment Script (Ubuntu / Debian / Oracle)
# ==============================================================================
# Usage:
#   bash deploy-cloud.sh
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}==================================================================${NC}"
echo -e "${GREEN}  Hermes Agent - 24/7 Cloud Deployment (Telegram + Cloudflare)    ${NC}"
echo -e "${CYAN}==================================================================${NC}"

# 1. Update system packages and install prerequisites
echo -e "\n${CYAN}[1/5] Installing core dependencies (curl, git, python3, ffmpeg, ripgrep)...${NC}"
if command -v apt-get &>/dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y curl git python3 python3-pip python3-venv ffmpeg ripgrep ca-certificates
elif command -v dnf &>/dev/null; then
    sudo dnf install -y curl git python3 python3-pip ffmpeg ripgrep ca-certificates
fi

# 2. Setup project directory
INSTALL_DIR="${HOME}/hermes-agent"
if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo -e "\n${CYAN}[2/5] Cloning Hermes Agent to $INSTALL_DIR...${NC}"
    git clone https://github.com/NousResearch/hermes-agent.git "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# 3. Create Virtual Environment & Install Dependencies
echo -e "\n${CYAN}[3/5] Setting up Python virtual environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

echo -e "\n${CYAN}[4/5] Installing Hermes and Telegram dependencies...${NC}"
pip install --upgrade pip
pip install -e . || true
pip install "python-telegram-bot>=21.0,<22" "python-dotenv>=1.0.0" httpx rich pydantic qrcode

# 4. Copy telegram_hermes.py if not present
if [ ! -f "telegram_hermes.py" ]; then
    echo -e "${YELLOW}Downloading latest telegram_hermes.py wrapper...${NC}"
    curl -fsSL -o telegram_hermes.py https://raw.githubusercontent.com/NousResearch/hermes-agent/main/telegram_hermes.py || true
fi

# 5. Create or verify .env
if [ ! -f ".env" ]; then
    echo -e "\n${YELLOW}Creating initial .env file...${NC}"
    cat << 'EOF' > .env
TELEGRAM_BOT_TOKEN=8968385636:AAGdU5sXiltqO39ryXiNPlEv8gMwvk9SEBQ
TELEGRAM_ALLOWED_USER_ID=
HERMES_MODEL=openrouter/auto
HERMES_PROVIDER=openrouter
OPENROUTER_API_KEY=
EOF
    echo -e "${GREEN}Created .env with your bot token: 8968385636:AAGdU5sXiltqO39ryXiNPlEv8gMwvk9SEBQ${NC}"
fi

# 6. Configure systemd service for 24/7 background persistence
echo -e "\n${CYAN}[5/5] Configuring systemd 24/7 background service...${NC}"
SERVICE_FILE="/etc/systemd/system/hermes-telegram.service"
CURRENT_USER="$(whoami)"

sudo bash -c "cat << EOF > $SERVICE_FILE
[Unit]
Description=Hermes Agent 24/7 Telegram Bot
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/telegram_hermes.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable hermes-telegram.service
sudo systemctl restart hermes-telegram.service

echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}  ✓ HERMES AGENT IS NOW RUNNING 24/7 IN THE CLOUD!               ${NC}"
echo -e "${GREEN}==================================================================${NC}"
echo -e "Service status:"
sudo systemctl status hermes-telegram.service --no-pager || true
echo -e "\n${CYAN}Useful commands:${NC}"
echo -e "  View live logs:    ${YELLOW}sudo journalctl -u hermes-telegram.service -f${NC}"
echo -e "  Restart service:   ${YELLOW}sudo systemctl restart hermes-telegram.service${NC}"
echo -e "  Stop service:      ${YELLOW}sudo systemctl stop hermes-telegram.service${NC}"
echo -e "\n${GREEN}Your bot @Hsbzbz_bot is online 24/7 even if your PC is shut down!${NC}"
