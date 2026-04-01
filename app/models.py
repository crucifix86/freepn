from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from . import db, login_manager
import ipaddress


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    full_tunnel = db.Column(db.Boolean, default=True)   # route all traffic through VPN
    dns = db.Column(db.String(64), default='1.1.1.1, 8.8.8.8')
    allowed_ips = db.Column(db.Text, default='0.0.0.0/0')  # custom split tunnel routes
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    peer = db.relationship('Peer', back_populates='user', uselist=False, cascade='all, delete-orphan')
    port_forwards = db.relationship('PortForward', back_populates='user', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_allowed_ips(self):
        if self.full_tunnel:
            return '0.0.0.0/0, ::/0'
        return self.allowed_ips or '0.0.0.0/0'


class Peer(db.Model):
    __tablename__ = 'peers'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    public_key = db.Column(db.Text, nullable=False)
    private_key = db.Column(db.Text, nullable=False)
    vpn_ip = db.Column(db.String(20), unique=True, nullable=False)
    preshared_key = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship('User', back_populates='peer')


class PortForward(db.Model):
    __tablename__ = 'port_forwards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    external_port = db.Column(db.Integer, unique=True, nullable=False)
    internal_port = db.Column(db.Integer, nullable=False)
    protocol = db.Column(db.String(4), default='tcp')   # tcp, udp, both
    description = db.Column(db.String(128), default='')
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship('User', back_populates='port_forwards')


class ServerConfig(db.Model):
    __tablename__ = 'server_config'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)

    @staticmethod
    def get(key, default=None):
        row = ServerConfig.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = ServerConfig.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            db.session.add(ServerConfig(key=key, value=str(value)))
        db.session.commit()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
