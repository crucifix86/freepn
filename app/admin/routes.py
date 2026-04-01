from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, Response
from flask_login import login_required, current_user
from functools import wraps
from .. import db
from ..models import User, Peer, PortForward, ServerConfig
from ..wg.manager import (
    create_peer, delete_peer, regenerate_peer_keys, write_wg_config,
    get_live_peers, init_server_keys, get_server_pubkey,
    apply_port_forward_rule, remove_port_forward_rule, fmt_bytes
)
import time

admin_bp = Blueprint('admin', __name__, template_folder='templates')


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Admin access required.', 'error')
            return redirect(url_for('client.dashboard'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@admin_required
def dashboard():
    users = User.query.filter_by(is_admin=False).all()
    live = get_live_peers()
    peers = Peer.query.all()
    connected = sum(
        1 for p in peers
        if p.public_key in live and (time.time() - live[p.public_key]['last_handshake']) < 180
    )
    total_rx = sum(v['rx_bytes'] for v in live.values())
    total_tx = sum(v['tx_bytes'] for v in live.values())
    return render_template(
        'admin/dashboard.html',
        users=users, live=live, connected=connected,
        total_rx=fmt_bytes(total_rx), total_tx=fmt_bytes(total_tx),
        now=time.time()
    )


@admin_bp.route('/users')
@admin_required
def users():
    all_users = User.query.filter_by(is_admin=False).all()
    live = get_live_peers()
    return render_template('admin/users.html', users=all_users, live=live, now=time.time())


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@admin_required
def new_user():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_tunnel = request.form.get('full_tunnel') == 'on'
        dns = request.form.get('dns', '1.1.1.1, 8.8.8.8').strip()
        allowed_ips = request.form.get('allowed_ips', '0.0.0.0/0').strip()

        if not username or not password:
            flash('Username and password are required.', 'error')
            return render_template('admin/user_form.html', action='new')

        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'error')
            return render_template('admin/user_form.html', action='new')

        user = User(
            username=username,
            is_admin=False,
            full_tunnel=full_tunnel,
            dns=dns,
            allowed_ips=allowed_ips,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        create_peer(user)
        flash(f'User {username} created.', 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', action='new')


@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@admin_required
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    live = get_live_peers()
    peer_status = None
    if user.peer and user.peer.public_key in live:
        peer_status = live[user.peer.public_key]
    server_endpoint = ServerConfig.get('server_endpoint', 'your-server-ip')
    return render_template('admin/user_detail.html', user=user, peer_status=peer_status, now=time.time(), fmt_bytes=fmt_bytes, server_endpoint=server_endpoint)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.full_tunnel = request.form.get('full_tunnel') == 'on'
        user.dns = request.form.get('dns', '1.1.1.1, 8.8.8.8').strip()
        user.allowed_ips = request.form.get('allowed_ips', '0.0.0.0/0').strip()
        user.is_active = request.form.get('is_active') == 'on'

        new_password = request.form.get('password', '').strip()
        if new_password:
            user.set_password(new_password)

        db.session.commit()
        write_wg_config()
        flash(f'User {user.username} updated.', 'success')
        return redirect(url_for('admin.user_detail', user_id=user.id))

    return render_template('admin/user_form.html', action='edit', user=user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    username = user.username
    delete_peer(user)
    db.session.delete(user)
    db.session.commit()
    flash(f'User {username} deleted.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    write_wg_config()
    return jsonify({'active': user.is_active})


@admin_bp.route('/users/<int:user_id>/regen-keys', methods=['POST'])
@admin_required
def regen_keys(user_id):
    user = User.query.get_or_404(user_id)
    regenerate_peer_keys(user)
    flash('Keys regenerated. User must re-download their config.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user.id))


# --- Port Forwards ---

@admin_bp.route('/users/<int:user_id>/port-forwards/new', methods=['POST'])
@admin_required
def add_port_forward(user_id):
    user = User.query.get_or_404(user_id)
    if not user.peer:
        flash('User has no VPN peer configured.', 'error')
        return redirect(url_for('admin.user_detail', user_id=user_id))

    ext_port = int(request.form.get('external_port', 0))
    int_port = int(request.form.get('internal_port', 0))
    protocol = request.form.get('protocol', 'tcp')
    description = request.form.get('description', '').strip()

    if not (1 <= ext_port <= 65535) or not (1 <= int_port <= 65535):
        flash('Invalid port numbers — must be between 1 and 65535.', 'error')
        return redirect(url_for('admin.user_detail', user_id=user_id))

    # Check for conflict — a public port can only be assigned to one user.
    # If protocol is 'both', we block if that port is taken by anyone for any protocol.
    conflict = PortForward.query.filter_by(external_port=ext_port).first()
    if conflict:
        conflict_owner = User.query.get(conflict.user_id)
        owner_name = conflict_owner.username if conflict_owner else 'another user'
        flash(
            f'Public port {ext_port} is already in use'
            + (f' by {owner_name}' if conflict_owner and conflict_owner.id != user_id else '')
            + '. Choose a different public port.',
            'error'
        )
        return redirect(url_for('admin.user_detail', user_id=user_id))

    pf = PortForward(
        user_id=user.id,
        external_port=ext_port,
        internal_port=int_port,
        protocol=protocol,
        description=description,
    )
    db.session.add(pf)
    db.session.commit()
    apply_port_forward_rule(pf, user.peer.vpn_ip)
    server_endpoint = ServerConfig.get('server_endpoint', 'server')
    flash(f'Port forward added: {server_endpoint}:{ext_port} → localhost:{int_port} ({protocol.upper()})', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/port-forwards/<int:pf_id>/delete', methods=['POST'])
@admin_required
def delete_port_forward(pf_id):
    pf = PortForward.query.get_or_404(pf_id)
    user_id = pf.user_id
    remove_port_forward_rule(pf)
    db.session.delete(pf)
    db.session.commit()
    flash('Port forward removed.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


# --- Server Settings ---

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        ServerConfig.set('server_endpoint', request.form.get('server_endpoint', '').strip())
        ServerConfig.set('server_dns', request.form.get('server_dns', '1.1.1.1, 8.8.8.8').strip())
        flash('Settings saved.', 'success')
        return redirect(url_for('admin.settings'))

    try:
        server_pubkey = get_server_pubkey()
    except Exception:
        init_server_keys()
        server_pubkey = get_server_pubkey()

    return render_template('admin/settings.html',
        server_pubkey=server_pubkey,
        server_endpoint=ServerConfig.get('server_endpoint', ''),
        server_dns=ServerConfig.get('server_dns', '1.1.1.1, 8.8.8.8'),
    )


@admin_bp.route('/settings/regen-server-keys', methods=['POST'])
@admin_required
def regen_server_keys():
    from ..wg.manager import generate_keypair
    private, public = generate_keypair()
    ServerConfig.set('server_private_key', private)
    ServerConfig.set('server_public_key', public)
    write_wg_config()
    flash('Server keys regenerated. ALL clients must re-download their configs.', 'warning')
    return redirect(url_for('admin.settings'))
