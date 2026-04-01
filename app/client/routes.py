from flask import Blueprint, render_template, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user
from ..models import ServerConfig
from ..wg.manager import generate_client_config, get_live_peers, fmt_bytes
import time
import qrcode
import io
import base64

client_bp = Blueprint('client', __name__, template_folder='templates')


@client_bp.route('/')
@login_required
def dashboard():
    live = get_live_peers()
    peer_status = None
    if current_user.peer and current_user.peer.public_key in live:
        peer_status = live[current_user.peer.public_key]
    server_endpoint = ServerConfig.get('server_endpoint', 'your-vpn-server')
    return render_template('client/dashboard.html', peer_status=peer_status, now=time.time(), fmt_bytes=fmt_bytes, server_endpoint=server_endpoint)


@client_bp.route('/config')
@login_required
def download_config():
    endpoint = ServerConfig.get('server_endpoint', '')
    if not endpoint:
        flash('Server endpoint not configured yet. Contact your admin.', 'error')
        return redirect(url_for('client.dashboard'))

    config = generate_client_config(current_user, endpoint)
    if not config:
        flash('No VPN configuration found for your account. Contact your admin.', 'error')
        return redirect(url_for('client.dashboard'))

    filename = f"freepn-{current_user.username}.conf"
    return Response(
        config,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@client_bp.route('/qr')
@login_required
def qr_code():
    endpoint = ServerConfig.get('server_endpoint', '')
    if not endpoint:
        flash('Server endpoint not configured yet. Contact your admin.', 'error')
        return redirect(url_for('client.dashboard'))

    config = generate_client_config(current_user, endpoint)
    if not config:
        flash('No VPN configuration found.', 'error')
        return redirect(url_for('client.dashboard'))

    img = qrcode.make(config)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return render_template('client/qr.html', qr_data=b64)
