#!/bin/bash
set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${BOLD}FreePN Client Installer${NC}"
echo "------------------------"
echo ""

# Root check
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error:${NC} Run as root: sudo bash client-install.sh"
  exit 1
fi

# Detect distro
if [ -f /etc/os-release ]; then
  . /etc/os-release
  DISTRO=$ID
else
  echo -e "${RED}Error:${NC} Could not detect distro."
  exit 1
fi

# Install packages
echo -e "${BOLD}[1/4] Installing WireGuard...${NC}"
case $DISTRO in
  ubuntu|debian|linuxmint|pop)
    apt-get update -qq
    apt-get install -y -qq wireguard wireguard-tools openresolv network-manager
    # NM WireGuard plugin
    apt-get install -y -qq network-manager-dev 2>/dev/null || true
    ;;
  fedora)
    dnf install -y -q wireguard-tools NetworkManager
    ;;
  arch|manjaro)
    pacman -Sy --noconfirm wireguard-tools networkmanager
    ;;
  *)
    echo -e "${YELLOW}Warning:${NC} Unknown distro '$DISTRO'. Trying apt..."
    apt-get update -qq && apt-get install -y -qq wireguard wireguard-tools openresolv network-manager || {
      echo -e "${RED}Error:${NC} Could not install packages. Install wireguard-tools manually."
      exit 1
    }
    ;;
esac
echo -e "${GREEN}Done.${NC}"

# Get conf file
echo ""
echo -e "${BOLD}[2/4] Locate your FreePN config file${NC}"
echo "  You should have downloaded a .conf file from the FreePN portal."
echo ""

while true; do
  read -rp "  Path to your .conf file: " CONF_PATH
  # Strip surrounding quotes if user dragged and dropped
  CONF_PATH="${CONF_PATH//\'/}"
  CONF_PATH="${CONF_PATH//\"/}"
  CONF_PATH="${CONF_PATH/ /}"

  if [ -f "$CONF_PATH" ]; then
    break
  else
    echo -e "  ${RED}File not found:${NC} $CONF_PATH — try again."
  fi
done

CONF_NAME=$(basename "$CONF_PATH" .conf)
echo -e "${GREEN}Found:${NC} $CONF_PATH"

# Install config
echo ""
echo -e "${BOLD}[3/4] Installing config...${NC}"

# Copy to /etc/wireguard for wg-quick fallback
cp "$CONF_PATH" /etc/wireguard/${CONF_NAME}.conf
chmod 600 /etc/wireguard/${CONF_NAME}.conf

# Import into NetworkManager so the system tray widget works
if command -v nmcli &>/dev/null; then
  # Remove existing connection with same name if present
  nmcli connection delete "$CONF_NAME" 2>/dev/null || true
  nmcli connection import type wireguard file /etc/wireguard/${CONF_NAME}.conf 2>/dev/null && \
    nmcli connection modify "$CONF_NAME" connection.autoconnect no && \
    echo -e "${GREEN}Imported into NetworkManager — use your system tray to connect/disconnect.${NC}" || \
    echo -e "${YELLOW}NetworkManager import failed — falling back to wg-quick.${NC}"
else
  echo -e "${YELLOW}NetworkManager not found — using wg-quick instead.${NC}"
  echo "  To connect:    sudo wg-quick up ${CONF_NAME}"
  echo "  To disconnect: sudo wg-quick down ${CONF_NAME}"
fi

echo -e "${GREEN}Done.${NC}"

# Done
echo ""
echo -e "${BOLD}[4/4] All set!${NC}"
echo ""
echo -e "  ${GREEN}FreePN is installed.${NC}"
echo ""

if command -v nmcli &>/dev/null; then
  echo "  ${BOLD}To connect:${NC}"
  echo "    • Click the network icon in your system tray"
  echo "    • Select '${CONF_NAME}' under VPN"
  echo "    • Or run: nmcli connection up ${CONF_NAME}"
  echo ""
  echo "  ${BOLD}To disconnect:${NC}"
  echo "    • Click the network icon → disconnect VPN"
  echo "    • Or run: nmcli connection down ${CONF_NAME}"
else
  echo "  ${BOLD}To connect:${NC}    sudo wg-quick up ${CONF_NAME}"
  echo "  ${BOLD}To disconnect:${NC} sudo wg-quick down ${CONF_NAME}"
fi

echo ""
