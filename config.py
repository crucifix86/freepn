import os

class Config:
    SECRET_KEY = os.environ.get('FREEPN_SECRET', 'change-me-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:////opt/freepn/freepn.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # WireGuard
    WG_INTERFACE = 'wg0'
    WG_CONFIG_PATH = '/etc/wireguard/wg0.conf'
    WG_SERVER_PORT = 51820
    VPN_SUBNET = '10.8.0.0/24'
    VPN_SERVER_IP = '10.8.0.1'
    VPN_IP_POOL_START = 2   # 10.8.0.2
    VPN_IP_POOL_END = 254

    # Port forwarding range available to users
    PORT_FORWARD_MIN = 10000
    PORT_FORWARD_MAX = 65000

    # Web UI
    ADMIN_PORT = 943
    CLIENT_PORT = 943
    WEB_HOST = '0.0.0.0'
