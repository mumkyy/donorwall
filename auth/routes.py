# auth/routes.py

from flask import Blueprint, request, render_template, redirect, url_for, flash, session
from passlib.hash import pbkdf2_sha256
from db import get_db

auth_bp = Blueprint('auth', __name__, template_folder='templates')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id, password_hash, is_admin FROM users WHERE username = ?", (username,))
            row = c.fetchone()

            if row:
                user_id, password_hash, is_admin = row
                # Verify password
                if pbkdf2_sha256.verify(password, password_hash):
                    # Store session data
                    session['user_id'] = user_id
                    session['is_admin'] = bool(is_admin)
                    flash('Logged in successfully!', 'success')
                    return redirect(url_for('admin.config_index'))
            flash('Invalid username or password', 'danger')

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('auth.login'))
