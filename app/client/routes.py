from flask import Blueprint, render_template, redirect, url_for, flash, Response, current_app, request
from flask_login import login_required, current_user
from .. import db
from ..models import ServerConfig, PortForward, User
from ..wg.manager import generate_client_config, get_live_peers, fmt_bytes, apply_port_forward_rule, remove_port_forward_rule
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


@client_bp.route('/port-forwards/new', methods=['POST'])
@login_required
def add_port_forward():
    if not current_user.peer:
        flash('Your VPN profile is not set up yet. Contact your admin.', 'error')
        return redirect(url_for('client.dashboard'))

    try:
        ext_port = int(request.form.get('external_port', 0))
        int_port = int(request.form.get('internal_port', 0))
    except ValueError:
        flash('Invalid port numbers.', 'error')
        return redirect(url_for('client.dashboard'))

    protocol = request.form.get('protocol', 'tcp')
    description = request.form.get('description', '').strip()

    if not (1 <= ext_port <= 65535) or not (1 <= int_port <= 65535):
        flash('Port numbers must be between 1 and 65535.', 'error')
        return redirect(url_for('client.dashboard'))

    conflict = PortForward.query.filter_by(external_port=ext_port).first()
    if conflict:
        # Don't reveal who owns it — just say it's taken
        flash(f'Public port {ext_port} is already in use. Please choose a different port.', 'error')
        return redirect(url_for('client.dashboard'))

    pf = PortForward(
        user_id=current_user.id,
        external_port=ext_port,
        internal_port=int_port,
        protocol=protocol,
        description=description,
    )
    db.session.add(pf)
    db.session.commit()
    apply_port_forward_rule(pf, current_user.peer.vpn_ip)

    server_endpoint = ServerConfig.get('server_endpoint', 'your-vpn-server')
    flash(f'Port forward added! Share this address: {server_endpoint}:{ext_port}', 'success')
    return redirect(url_for('client.dashboard'))


@client_bp.route('/port-forwards/<int:pf_id>/delete', methods=['POST'])
@login_required
def delete_port_forward(pf_id):
    pf = PortForward.query.get_or_404(pf_id)
    if pf.user_id != current_user.id:
        flash('Not authorised.', 'error')
        return redirect(url_for('client.dashboard'))
    remove_port_forward_rule(pf)
    db.session.delete(pf)
    db.session.commit()
    flash('Port forward removed.', 'success')
    return redirect(url_for('client.dashboard'))
