# admin/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from functools import wraps
import os

from db import get_db

# Create the blueprint object
admin_bp = Blueprint('admin', __name__, template_folder='templates')

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _parse_amount(raw):
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if text in ("", "None"):
        return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            flash('Admin access required!', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper

@admin_bp.route('/config', methods=['GET', 'POST'])
@admin_required
def config_index():
    if request.method == 'POST':
        # Debug: Print received form data
        print("Form data:", request.form)

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT background_image, font_size, scroll_speed, google_sheet_id, donor_website, font_color, scroll_direction, scroll_position, scroll_width, scroll_height FROM settings WHERE id = 1')
            current_settings = c.fetchone() or ('default.jpg', 24, 50, '', '', '#FFFFFF', 'up', 'center', 300, 500)

            # Handle background image
            if 'background_image' in request.files:
                file = request.files['background_image']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(UPLOAD_FOLDER, filename))
                    c.execute('UPDATE settings SET background_image = ? WHERE id = 1', (filename,))

            # Other settings from form
            font_size = request.form.get('font_size', type=int) or current_settings[1]
            font_color = request.form.get('font_color') or current_settings[5]
            scroll_speed = request.form.get('scroll_speed', type=int) or current_settings[2]
            scroll_direction = request.form.get('scroll_direction') or current_settings[6]
            scroll_position = request.form.get('scroll_position') or current_settings[7]
            google_sheet_id = request.form.get('google_sheet_id') or current_settings[3]
            donor_website = request.form.get('donor_website') or current_settings[4]
            scroll_width = request.form.get('scroll_width', type=int) or current_settings[8]
            scroll_height = request.form.get('scroll_height', type=int) or current_settings[9]

            # Debug: Print values to be updated in the database
            print("Updating settings:", font_size, font_color, scroll_speed, scroll_direction,
                  scroll_position, google_sheet_id, donor_website, scroll_width, scroll_height)

            c.execute('''
                UPDATE settings
                SET font_size = ?,
                    font_color = ?,
                    scroll_speed = ?,
                    scroll_direction = ?,
                    scroll_position = ?,
                    google_sheet_id = ?,
                    donor_website = ?,
                    scroll_width = ?,
                    scroll_height = ?
                WHERE id = 1
            ''', (font_size, font_color, scroll_speed, scroll_direction, scroll_position,
                  google_sheet_id, donor_website, scroll_width, scroll_height))

        flash('Settings updated successfully!', 'success')
        return redirect(url_for('admin.config_index'))

    # GET request -> show current settings
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT background_image, font_size, scroll_speed, google_sheet_id, donor_website, font_color, scroll_direction, scroll_position, scroll_width, scroll_height FROM settings WHERE id = 1')
        settings = c.fetchone()

    return render_template('admin_config.html', settings=settings)

@admin_bp.route('/donors', methods=['GET', 'POST'])
@admin_required
def manage_donors():
    with get_db() as conn:
        c = conn.cursor()

        if request.method == 'POST':
            # Handle adding a new donor
            name = request.form.get('name')
            amount = _parse_amount(request.form.get('amount', ''))
            if name:
                c.execute('INSERT INTO donors (name, amount) VALUES (?, ?)', (name, amount))
                conn.commit()
                flash('Donor added successfully!', 'success')
            else:
                flash('Name is required to add a donor.', 'danger')

        # Retrieve all donors
        c.execute('SELECT id, name, amount FROM donors')
        donors = c.fetchall()

    return render_template('manage_donors.html', donors=donors)


@admin_bp.route('/donors/delete/<int:donor_id>', methods=['POST'])
@admin_required
def delete_donor(donor_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM donors WHERE id = ?', (donor_id,))
        conn.commit()
        flash('Donor deleted successfully!', 'success')
    return redirect(url_for('admin.manage_donors'))


@admin_bp.route('/donors/edit/<int:donor_id>', methods=['GET', 'POST'])
@admin_required
def edit_donor(donor_id):
    with get_db() as conn:
        c = conn.cursor()

        if request.method == 'POST':
            # Handle donor edit
            name = request.form.get('name')
            amount = _parse_amount(request.form.get('amount', ''))
            if name:
                c.execute('UPDATE donors SET name = ?, amount = ? WHERE id = ?', (name, amount, donor_id))
                conn.commit()
                flash('Donor updated successfully!', 'success')
                return redirect(url_for('admin.manage_donors'))
            else:
                flash('Name is required to update a donor.', 'danger')

        # Retrieve donor details
        c.execute('SELECT id, name, amount FROM donors WHERE id = ?', (donor_id,))
        donor = c.fetchone()

    return render_template('edit_donor.html', donor=donor)
