import pystray
import PIL.Image
import PIL.ImageDraw
import subprocess
import threading
import os
import shutil
import json
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

CONFIG_DIR = os.path.expanduser("~/.config/freepn")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
WG_CONF_DIR = os.path.join(CONFIG_DIR, "configs")


def load_settings():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_settings(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f)


def get_active_profile():
    s = load_settings()
    return s.get('active_profile')


def list_profiles():
    if not os.path.exists(WG_CONF_DIR):
        return []
    return [f[:-5] for f in os.listdir(WG_CONF_DIR) if f.endswith('.conf')]


def is_connected(profile=None):
    profile = profile or get_active_profile()
    if not profile:
        return False
    result = subprocess.run(['wg', 'show', profile], capture_output=True)
    return result.returncode == 0


def run_privileged(cmd):
    """Run a command with privilege escalation (pkexec → sudo fallback)."""
    if shutil.which('pkexec'):
        result = subprocess.run(['pkexec'] + cmd, capture_output=True, text=True)
    else:
        result = subprocess.run(['sudo'] + cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


def connect(icon, profile=None):
    profile = profile or get_active_profile()
    if not profile:
        prompt_load_config(icon)
        return

    conf_path = os.path.join(WG_CONF_DIR, f"{profile}.conf")
    if not os.path.exists(conf_path):
        prompt_load_config(icon)
        return

    def _do():
        update_icon(icon, connecting=True)
        ok, err = run_privileged(['wg-quick', 'up', conf_path])
        if not ok and 'already exists' not in err:
            show_error(f"Failed to connect:\n{err}")
        update_icon(icon)
        icon.update_menu()

    threading.Thread(target=_do, daemon=True).start()


def disconnect(icon, profile=None):
    profile = profile or get_active_profile()
    if not profile:
        return

    def _do():
        run_privileged(['wg-quick', 'down', profile])
        update_icon(icon)
        icon.update_menu()

    threading.Thread(target=_do, daemon=True).start()


def prompt_load_config(icon):
    def _do():
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        path = filedialog.askopenfilename(
            parent=root,
            title='Select your FreePN config file',
            filetypes=[('WireGuard Config', '*.conf'), ('All Files', '*.*')]
        )
        root.destroy()

        if not path:
            return

        os.makedirs(WG_CONF_DIR, exist_ok=True)
        profile = os.path.basename(path)[:-5]
        dest = os.path.join(WG_CONF_DIR, f"{profile}.conf")
        shutil.copy2(path, dest)
        os.chmod(dest, 0o600)

        s = load_settings()
        s['active_profile'] = profile
        save_settings(s)

        icon.update_menu()
        update_icon(icon)

        # Ask to connect now
        root2 = tk.Tk()
        root2.withdraw()
        root2.attributes('-topmost', True)
        if messagebox.askyesno('FreePN', f'Config "{profile}" loaded.\nConnect now?', parent=root2):
            connect(icon, profile)
        root2.destroy()

    threading.Thread(target=_do, daemon=True).start()


def show_error(msg):
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    messagebox.showerror('FreePN', msg, parent=root)
    root.destroy()


def make_icon_image(connected=False, connecting=False):
    size = 64
    img = PIL.Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = PIL.ImageDraw.Draw(img)

    # Shield shape
    pts = [
        (size*0.5, size*0.05),
        (size*0.95, size*0.2),
        (size*0.95, size*0.55),
        (size*0.5, size*0.95),
        (size*0.05, size*0.55),
        (size*0.05, size*0.2),
    ]

    if connecting:
        color = (224, 154, 61, 255)   # amber
    elif connected:
        color = (61, 186, 122, 255)   # green
    else:
        color = (100, 110, 140, 255)  # grey

    draw.polygon(pts, fill=color)

    # Lock body
    cx, cy = size * 0.5, size * 0.58
    bw, bh = size * 0.28, size * 0.24
    draw.rectangle(
        [cx - bw/2, cy - bh/2, cx + bw/2, cy + bh/2],
        fill=(255, 255, 255, 220)
    )
    # Lock shackle
    sw = size * 0.14
    draw.arc(
        [cx - sw, cy - bh/2 - sw*1.2, cx + sw, cy - bh/2 + sw*0.2],
        start=180, end=0,
        fill=(255, 255, 255, 220),
        width=int(size * 0.06)
    )

    return img


def update_icon(icon, connecting=False):
    connected = is_connected()
    icon.icon = make_icon_image(connected=connected, connecting=connecting)
    icon.title = 'FreePN — Connected' if connected else 'FreePN — Disconnected'


def build_menu(icon):
    profile = get_active_profile()
    connected = is_connected(profile)

    items = []

    if profile:
        status = 'Connected' if connected else 'Disconnected'
        items.append(pystray.MenuItem(f'{profile}  [{status}]', None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)
        if connected:
            items.append(pystray.MenuItem('Disconnect', lambda i, _: disconnect(i)))
        else:
            items.append(pystray.MenuItem('Connect', lambda i, _: connect(i)))
        items.append(pystray.Menu.SEPARATOR)

    items.append(pystray.MenuItem('Load Config...', lambda i, _: prompt_load_config(i)))

    profiles = list_profiles()
    if len(profiles) > 1:
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem('Profiles', pystray.Menu(*[
            pystray.MenuItem(
                p,
                lambda i, _, p=p: switch_profile(i, p),
                checked=lambda _, p=p: get_active_profile() == p
            ) for p in profiles
        ])))

    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem('Quit', lambda i, _: quit_app(i)))

    return pystray.Menu(*items)


def switch_profile(icon, profile):
    active = get_active_profile()
    if active and is_connected(active):
        disconnect(icon, active)
    s = load_settings()
    s['active_profile'] = profile
    save_settings(s)
    icon.update_menu()
    update_icon(icon)


def quit_app(icon):
    profile = get_active_profile()
    if profile and is_connected(profile):
        run_privileged(['wg-quick', 'down', profile])
    icon.stop()


def main():
    # Ensure wg is available
    if not shutil.which('wg'):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            'FreePN — Missing dependency',
            'WireGuard tools not found.\n\nInstall with:\n  sudo apt install wireguard-tools'
        )
        root.destroy()
        sys.exit(1)

    img = make_icon_image(connected=is_connected())
    icon = pystray.Icon(
        'freepn',
        img,
        title='FreePN',
        menu=pystray.Menu(lambda: build_menu(icon))
    )

    # Auto-connect if was connected before
    settings = load_settings()
    if settings.get('auto_connect') and get_active_profile():
        threading.Thread(target=lambda: connect(icon), daemon=True).start()

    icon.run()


if __name__ == '__main__':
    main()
