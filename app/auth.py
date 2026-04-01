from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from .models import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('client.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=True)
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            if user.is_admin:
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('client.dashboard'))

        flash('Invalid username or password.', 'error')

    return render_template('login.html')


@auth_bp.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    from . import db
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'error')
        elif len(new_password) < 6:
            flash('New password must be at least 6 characters.', 'error')
        elif new_password != confirm:
            flash('New passwords do not match.', 'error')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash('Password updated successfully.', 'success')

    return render_template('account.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
