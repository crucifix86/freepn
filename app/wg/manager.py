import subprocess
import ipaddress
import re
from flask import current_app
from .. import db
from ..models import Peer, User, PortForward, ServerConfig


def run(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
    return result.stdout.strip()


def generate_keypair():
    private = run("wg genkey")
    public = run(f"echo '{private}' | wg pubkey")
    return private, public


def generate_psk():
    return run("wg genpsk")


def get_server_pubkey():
    key = ServerConfig.get('server_public_key')
    if not key:
        raise RuntimeError("Server keys not initialized. Run init_server_keys().")
    return key


def init_server_keys():
    if ServerConfig.get('server_private_key'):
        return
    private, public = generate_keypair()
    ServerConfig.set('server_private_key', private)
    ServerConfig.set('server_public_key', public)


def next_vpn_ip():
    cfg = current_app.config
    used = {p.vpn_ip for p in Peer.query.all()}
    used.add(cfg['VPN_SERVER_IP'])
    base = ipaddress.ip_network(cfg['VPN_SUBNET'])
    for host in base.hosts():
        ip = str(host)
        if ip not in used:
            return ip
    raise RuntimeError("VPN IP pool exhausted")


def write_wg_config():
    cfg = current_app.config
    private_key = ServerConfig.get('server_private_key')
    if not private_key:
        init_server_keys()
        private_key = ServerConfig.get('server_private_key')

    lines = [
        "[Interface]",
        f"Address = {cfg['VPN_SERVER_IP']}/24",
        f"ListenPort = {cfg['WG_SERVER_PORT']}",
        f"PrivateKey = {private_key}",
        f"PostUp = iptables -A FORWARD -i {cfg['WG_INTERFACE']} -j ACCEPT; iptables -A FORWARD -o {cfg['WG_INTERFACE']} -j ACCEPT; iptables -t nat -A POSTROUTING -s {cfg['VPN_SUBNET']} -o $(ip route show default | awk '{{print $5}}' | head -1) -j MASQUERADE; iptables -t nat -A POSTROUTING -o {cfg['WG_INTERFACE']} -j MASQUERADE",
        f"PostDown = iptables -D FORWARD -i {cfg['WG_INTERFACE']} -j ACCEPT; iptables -D FORWARD -o {cfg['WG_INTERFACE']} -j ACCEPT; iptables -t nat -D POSTROUTING -s {cfg['VPN_SUBNET']} -o $(ip route show default | awk '{{print $5}}' | head -1) -j MASQUERADE; iptables -t nat -D POSTROUTING -o {cfg['WG_INTERFACE']} -j MASQUERADE",
        "",
    ]

    peers = Peer.query.all()
    for peer in peers:
        user = User.query.get(peer.user_id)
        if not user or not user.is_active:
            continue
        lines += [
            f"# {user.username}",
            "[Peer]",
            f"PublicKey = {peer.public_key}",
        ]
        if peer.preshared_key:
            lines.append(f"PresharedKey = {peer.preshared_key}")
        lines += [
            f"AllowedIPs = {peer.vpn_ip}/32",
            "",
        ]

    config = "\n".join(lines)
    with open(cfg['WG_CONFIG_PATH'], 'w') as f:
        f.write(config)

    # Sync live config without dropping connections
    try:
        run(f"wg syncconf {cfg['WG_INTERFACE']} <(wg-quick strip {cfg['WG_INTERFACE']})")
    except Exception:
        pass


def get_live_peers():
    try:
        output = run("wg show all dump", check=False)
    except Exception:
        return {}

    peers = {}
    for line in output.splitlines():
        parts = line.split('\t')
        if len(parts) >= 8 and parts[1] != '(none)':
            pubkey = parts[1]
            endpoint = parts[3] if parts[3] != '(none)' else None
            rx = int(parts[5]) if parts[5].isdigit() else 0
            tx = int(parts[6]) if parts[6].isdigit() else 0
            last_handshake = int(parts[4]) if parts[4].isdigit() else 0
            peers[pubkey] = {
                'endpoint': endpoint,
                'rx_bytes': rx,
                'tx_bytes': tx,
                'last_handshake': last_handshake,
            }
    return peers


def create_peer(user):
    vpn_ip = next_vpn_ip()
    private_key, public_key = generate_keypair()
    psk = generate_psk()

    peer = Peer(
        user_id=user.id,
        public_key=public_key,
        private_key=private_key,
        preshared_key=psk,
        vpn_ip=vpn_ip,
    )
    db.session.add(peer)
    db.session.commit()
    write_wg_config()
    return peer


def delete_peer(user):
    if user.peer:
        # Remove port forwards from iptables
        for pf in user.port_forwards:
            remove_port_forward_rule(pf)
        db.session.delete(user.peer)
        db.session.commit()
        write_wg_config()


def regenerate_peer_keys(user):
    if not user.peer:
        return create_peer(user)
    private_key, public_key = generate_keypair()
    psk = generate_psk()
    user.peer.private_key = private_key
    user.peer.public_key = public_key
    user.peer.preshared_key = psk
    db.session.commit()
    write_wg_config()
    return user.peer


def generate_client_config(user, server_endpoint):
    if not user.peer:
        return None
    cfg = current_app.config
    server_pubkey = get_server_pubkey()
    peer = user.peer

    lines = [
        "[Interface]",
        f"PrivateKey = {peer.private_key}",
        f"Address = {peer.vpn_ip}/24",
        f"DNS = {user.dns}",
        "",
        "[Peer]",
        f"PublicKey = {server_pubkey}",
        f"PresharedKey = {peer.preshared_key}",
        f"Endpoint = {server_endpoint}:{cfg['WG_SERVER_PORT']}",
        f"AllowedIPs = {user.get_allowed_ips()}",
        "PersistentKeepalive = 25",
    ]
    return "\n".join(lines)


# --- Port Forwarding ---

def apply_port_forward_rule(pf, peer_vpn_ip):
    protos = ['tcp', 'udp'] if pf.protocol == 'both' else [pf.protocol]
    for proto in protos:
        # Allow inbound on public port
        run(f"iptables -I INPUT -p {proto} --dport {pf.external_port} -j ACCEPT", check=False)
        # DNAT to VPN peer
        run(
            f"iptables -t nat -A PREROUTING -p {proto} --dport {pf.external_port} "
            f"-j DNAT --to-destination {peer_vpn_ip}:{pf.internal_port}",
            check=False
        )
        # Allow forwarding to peer
        run(
            f"iptables -A FORWARD -p {proto} -d {peer_vpn_ip} --dport {pf.internal_port} -j ACCEPT",
            check=False
        )


def remove_port_forward_rule(pf):
    user = User.query.get(pf.user_id)
    if not user or not user.peer:
        return
    peer_vpn_ip = user.peer.vpn_ip
    protos = ['tcp', 'udp'] if pf.protocol == 'both' else [pf.protocol]
    for proto in protos:
        run(f"iptables -D INPUT -p {proto} --dport {pf.external_port} -j ACCEPT", check=False)
        run(
            f"iptables -t nat -D PREROUTING -p {proto} --dport {pf.external_port} "
            f"-j DNAT --to-destination {peer_vpn_ip}:{pf.internal_port}",
            check=False
        )
        run(
            f"iptables -D FORWARD -p {proto} -d {peer_vpn_ip} --dport {pf.internal_port} -j ACCEPT",
            check=False
        )


def restore_port_forward_rules():
    for pf in PortForward.query.all():
        user = User.query.get(pf.user_id)
        if user and user.peer and user.is_active:
            apply_port_forward_rule(pf, user.peer.vpn_ip)


def fmt_bytes(b):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
