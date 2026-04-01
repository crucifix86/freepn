#!/bin/bash
set -e

echo "=== FreePN Installer ==="

# Check root
if [ "$EUID" -ne 0 ]; then
  echo "Error: Run as root"
  exit 1
fi

# Install system deps
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq wireguard wireguard-tools python3 python3-pip python3-venv iptables iptables-persistent

# Enable IP forwarding
echo "[2/7] Enabling IP forwarding..."
grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
grep -q "^net.ipv6.conf.all.forwarding=1" /etc/sysctl.conf || echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.conf
sysctl -p -q

# Firewall rules
echo "[3/7] Configuring firewall..."
iptables -I INPUT -p udp --dport 51820 -j ACCEPT   # WireGuard
iptables -I INPUT -p tcp --dport 943 -j ACCEPT     # FreePN web UI
iptables-save > /etc/iptables/rules.v4

# Copy app files
echo "[4/7] Installing FreePN..."
mkdir -p /opt/freepn
cp -r . /opt/freepn/
cd /opt/freepn

# Python venv
echo "[5/7] Setting up Python environment..."
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

# Systemd service
echo "[6/7] Configuring systemd service..."
cp freepn.service /etc/systemd/system/freepn.service
systemctl daemon-reload
systemctl enable freepn

# WireGuard interface
echo "[7/7] Starting services..."
systemctl enable wg-quick@wg0 2>/dev/null || true
systemctl start freepn

PUBLIC_IP=$(curl -s https://ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")

echo ""
echo "=== FreePN installed successfully! ==="
echo ""
echo "  Web UI:     http://${PUBLIC_IP}:943"
echo "  Admin:      admin / admin"
echo ""
echo "  IMPORTANT: Change the admin password after first login!"
echo "  Go to Server Settings and set the endpoint to: ${PUBLIC_IP}"
echo ""
