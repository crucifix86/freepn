#!/bin/bash
set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

APP_NAME="FreePN"
APP_DIR="AppDir"
ARCH=$(uname -m)

echo ""
echo -e "${BOLD}Building FreePN AppImage${NC}"
echo "-------------------------"
echo ""

cd "$(dirname "$0")"

# Dependencies
echo -e "${BOLD}[1/5] Installing build deps...${NC}"
pip install -q pyinstaller pystray Pillow
echo -e "${GREEN}Done.${NC}"

# PyInstaller bundle
echo -e "${BOLD}[2/5] Bundling with PyInstaller...${NC}"
pyinstaller \
  --onedir \
  --name freepn_tray \
  --noconsole \
  --hidden-import pystray._xorg \
  --hidden-import PIL._tkinter_finder \
  freepn_tray.py
echo -e "${GREEN}Done.${NC}"

# AppDir structure
echo -e "${BOLD}[3/5] Building AppDir...${NC}"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/share/applications"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"

cp -r dist/freepn_tray/* "$APP_DIR/usr/bin/"
cp freepn.desktop "$APP_DIR/usr/share/applications/freepn.desktop"
cp freepn.desktop "$APP_DIR/freepn.desktop"

# Generate icon using Python
python3 - <<'PYEOF'
from PIL import Image, ImageDraw
import os

size = 256
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

pts = [
    (size*0.5, size*0.05),
    (size*0.95, size*0.2),
    (size*0.95, size*0.55),
    (size*0.5, size*0.95),
    (size*0.05, size*0.55),
    (size*0.05, size*0.2),
]
draw.polygon(pts, fill=(79, 142, 247, 255))

cx, cy = size * 0.5, size * 0.58
bw, bh = size * 0.28, size * 0.24
draw.rectangle([cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2], fill=(255,255,255,220))
sw = size * 0.14
draw.arc([cx-sw, cy-bh/2-sw*1.2, cx+sw, cy-bh/2+sw*0.2],
         start=180, end=0, fill=(255,255,255,220), width=int(size*0.06))

os.makedirs('AppDir/usr/share/icons/hicolor/256x256/apps', exist_ok=True)
img.save('AppDir/usr/share/icons/hicolor/256x256/apps/freepn.png')
img.save('AppDir/freepn.png')
print('Icon generated.')
PYEOF

# AppRun entry point
cat > "$APP_DIR/AppRun" << 'EOF'
#!/bin/bash
SELF_DIR="$(dirname "$(readlink -f "$0")")"
export PATH="$SELF_DIR/usr/bin:$PATH"
exec "$SELF_DIR/usr/bin/freepn_tray" "$@"
EOF
chmod +x "$APP_DIR/AppRun"

echo -e "${GREEN}Done.${NC}"

# Download appimagetool if needed
echo -e "${BOLD}[4/5] Getting appimagetool...${NC}"
if [ ! -f appimagetool ]; then
  curl -sSL -o appimagetool \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x appimagetool
fi
echo -e "${GREEN}Done.${NC}"

# Build AppImage
echo -e "${BOLD}[5/5] Packaging AppImage...${NC}"
ARCH=$ARCH ./appimagetool "$APP_DIR" "${APP_NAME}-${ARCH}.AppImage"
echo -e "${GREEN}Done.${NC}"

echo ""
echo -e "${GREEN}${BOLD}Built: ${APP_NAME}-${ARCH}.AppImage${NC}"
echo ""
echo "Users just need to:"
echo "  chmod +x ${APP_NAME}-${ARCH}.AppImage"
echo "  ./${APP_NAME}-${ARCH}.AppImage"
echo ""
