#!/bin/bash
set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO="https://github.com/crucifix86/freepn.git"
INSTALL_DIR="/opt/freepn"

echo ""
echo -e "${BOLD}FreePN Server Setup${NC}"
echo "--------------------"
echo ""

# Root check
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error:${NC} Run as root: sudo bash server-setup.sh"
  exit 1
fi

# Detect public IP
PUBLIC_IP=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || \
            curl -s --max-time 5 https://api.ipify.org 2>/dev/null || \
            echo "")

# Ask for endpoint
echo -e "${BOLD}Server endpoint${NC}"
echo "  This is the public IP or hostname clients will connect to."
if [ -n "$PUBLIC_IP" ]; then
  read -rp "  Endpoint [${PUBLIC_IP}]: " ENDPOINT
  ENDPOINT="${ENDPOINT:-$PUBLIC_IP}"
else
  read -rp "  Endpoint (IP or hostname): " ENDPOINT
fi
echo ""

# [1] Packages
echo -e "${BOLD}[1/6] Installing packages...${NC}"
apt-get update -qq
apt-get install -y -qq \
  wireguard wireguard-tools \
  python3 python3-pip python3-venv \
  iptables iptables-persistent \
  git curl
echo -e "${GREEN}Done.${NC}"

# [2] IP forwarding
echo -e "${BOLD}[2/6] Enabling IP forwarding...${NC}"
grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
grep -q "^net.ipv6.conf.all.forwarding=1" /etc/sysctl.conf || echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.conf
sysctl -p -q
echo -e "${GREEN}Done.${NC}"

# [3] Firewall
echo -e "${BOLD}[3/6] Configuring firewall...${NC}"
iptables -I INPUT -p udp --dport 51820 -j ACCEPT   # WireGuard
iptables -I INPUT -p tcp --dport 943 -j ACCEPT     # FreePN web UI
iptables-save > /etc/iptables/rules.v4
echo -e "${GREEN}Done.${NC}"

# [4] Clone/update repo
echo -e "${BOLD}[4/6] Installing FreePN...${NC}"
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "  Existing install found — updating..."
  cd "$INSTALL_DIR" && git pull
else
  git clone "$REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi
echo -e "${GREEN}Done.${NC}"

# [5] Python env
echo -e "${BOLD}[5/6] Setting up Python environment...${NC}"
cd "$INSTALL_DIR"
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
echo -e "${GREEN}Done.${NC}"

# [6] Service
echo -e "${BOLD}[6/6] Starting FreePN...${NC}"
cp "$INSTALL_DIR/freepn.service" /etc/systemd/system/freepn.service
systemctl daemon-reload
systemctl enable freepn
systemctl restart freepn

# Set endpoint in DB
sleep 3
cd "$INSTALL_DIR"
venv/bin/python - <<PYEOF
from app import create_app
from app.models import ServerConfig
from app.wg.manager import init_server_keys, write_wg_config
app = create_app()
with app.app_context():
    ServerConfig.set('server_endpoint', '${ENDPOINT}')
    init_server_keys()
    write_wg_config()
PYEOF

echo -e "${GREEN}Done.${NC}"

echo ""
echo -e "${BOLD}=============================${NC}"
echo -e "${GREEN}  FreePN is ready!${NC}"
echo -e "${BOLD}=============================${NC}"
echo ""
echo -e "  Web UI:   ${BOLD}http://${ENDPOINT}:943${NC}"
echo -e "  Admin:    ${BOLD}admin${NC} / ${BOLD}admin${NC}"
echo ""
echo -e "  ${YELLOW}Change the admin password after first login!${NC}"
echo ""
