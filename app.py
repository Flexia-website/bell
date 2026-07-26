import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)

# --------------------- CONFIGURATION ---------------------
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')  # Set in Render env

# Use DATABASE_URL from environment (Render) or fallback to SQLite for local dev
database_url = os.environ.get('DATABASE_URL', 'sqlite:///bellesence.db')
# Render provides DATABASE_URL as 'postgres://...' — SQLAlchemy 1.4+ needs 'postgresql://'
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# File upload folder (for logo & product images)
# On Render, mount a disk to this path so files persist across deploys
app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --------------------- DATABASE MODELS ---------------------
class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    image_filename = db.Column(db.String(300), nullable=True)  # cover image (backward compatible)
    images = db.relationship('ProductImage', backref='product', cascade='all, delete-orphan',
                              order_by='ProductImage.sort_order')

    @property
    def all_images(self):
        result = []
        if self.image_filename:
            result.append(self.image_filename)
        for img in self.images:
            if img.filename not in result:
                result.append(img.filename)
        return result

class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(200), nullable=False)
    customer_phone = db.Column(db.String(50), nullable=False)
    customer_address = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default='pending')  # pending, confirmed, shipped, completed, cancelled
    created_at = db.Column(db.DateTime, default=db.func.now())
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan')

    @property
    def total(self):
        return sum(item.price * item.quantity for item in self.items)

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    product_name = db.Column(db.String(200), nullable=False)  # snapshot, survives product deletion
    price = db.Column(db.Float, nullable=False)  # snapshot at order time
    quantity = db.Column(db.Integer, default=1)

# --------------------- THEME PRESETS ---------------------
THEMES = {
    'rose': {
        'label': 'Rose Blush (default)',
        'primary': '#d81b60', 'primary_dark': '#880e4f', 'accent': '#f8bbd0',
        'bg_start': '#fce4ec', 'bg_end': '#f8bbd0',
        'text': '#333333', 'text_muted': '#666666', 'card_bg': 'rgba(255,255,255,0.9)',
    },
    'midnight': {
        'label': 'Midnight Gold',
        'primary': '#d4af37', 'primary_dark': '#8a6d1a', 'accent': '#2c2c3a',
        'bg_start': '#161622', 'bg_end': '#2c2c3a',
        'text': '#f0e9d8', 'text_muted': '#b9b3a3', 'card_bg': 'rgba(35,35,48,0.9)',
    },
    'emerald': {
        'label': 'Emerald Luxe',
        'primary': '#0f9d58', 'primary_dark': '#0b6e3d', 'accent': '#d0f0e0',
        'bg_start': '#e6f7ee', 'bg_end': '#c8ecd9',
        'text': '#1e3a2b', 'text_muted': '#4a6455', 'card_bg': 'rgba(255,255,255,0.9)',
    },
    'ocean': {
        'label': 'Ocean Breeze',
        'primary': '#0288d1', 'primary_dark': '#01579b', 'accent': '#b3e5fc',
        'bg_start': '#e1f5fe', 'bg_end': '#b3e5fc',
        'text': '#0d2b3a', 'text_muted': '#3f6273', 'card_bg': 'rgba(255,255,255,0.9)',
    },
    'sunset': {
        'label': 'Sunset Amber',
        'primary': '#e65100', 'primary_dark': '#a13a00', 'accent': '#ffe0b2',
        'bg_start': '#fff3e0', 'bg_end': '#ffe0b2',
        'text': '#3a2314', 'text_muted': '#6b5140', 'card_bg': 'rgba(255,255,255,0.9)',
    },
}
DEFAULT_THEME = 'rose'
CURRENCY_SYMBOL = '₦'

def format_naira(value):
    try:
        return '₦{:,.2f}'.format(float(value))
    except (TypeError, ValueError):
        return '₦0.00'

app.jinja_env.filters['naira'] = format_naira

# --------------------- CONTEXT PROCESSOR ---------------------
@app.context_processor
def inject_config():
    def cfg(key, default=''):
        row = Config.query.filter_by(key=key).first()
        return row.value if row and row.value else default

    theme_key = cfg('theme', DEFAULT_THEME)
    if theme_key not in THEMES:
        theme_key = DEFAULT_THEME

    return {
        'site_name': cfg('site_name', 'Bellesence'),
        'logo_filename': cfg('logo_filename') or None,
        'hero_title': cfg('hero_title', 'Our Perfumes'),
        'tagline': cfg('tagline'),
        'current_contact_phone': cfg('contact_phone'),
        'current_contact_email': cfg('contact_email'),
        'current_address': cfg('address'),
        'current_whatsapp': cfg('whatsapp'),
        'current_instagram': cfg('instagram'),
        'current_facebook': cfg('facebook'),
        'current_footer_note': cfg('footer_note'),
        'theme': THEMES[theme_key],
        'theme_key': theme_key,
        'themes_all': THEMES,
        'currency': CURRENCY_SYMBOL
    }

# --------------------- DECORATORS ---------------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

# --------------------- ROUTES – PUBLIC ---------------------
@app.route('/')
def index():
    products = Product.query.all()
    return render_template('index.html', products=products)

@app.route('/product/<int:id>')
def product_detail(id):
    product = Product.query.get_or_404(id)
    return render_template('product.html', product=product)

@app.route('/product/<int:id>/order', methods=['POST'])
def place_order(id):
    product = Product.query.get_or_404(id)
    customer_name = request.form.get('customer_name', '').strip()
    customer_phone = request.form.get('customer_phone', '').strip()
    customer_address = request.form.get('customer_address', '').strip()
    try:
        quantity = max(1, int(request.form.get('quantity', 1)))
    except (TypeError, ValueError):
        quantity = 1

    if not customer_name or not customer_phone:
        flash('Please provide your name and phone number to place an order.', 'danger')
        return redirect(url_for('product_detail', id=id))

    order = Order(customer_name=customer_name, customer_phone=customer_phone,
                  customer_address=customer_address, status='pending')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id,
                              product_name=product.name, price=product.price, quantity=quantity))
    db.session.commit()
    flash('Your order has been placed! We will contact you shortly to confirm.', 'success')
    return redirect(url_for('product_detail', id=id))

# --------------------- ROUTES – ADMIN AUTH ---------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid password', 'danger')
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

# --------------------- ROUTES – ADMIN DASHBOARD ---------------------
@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('admin/dashboard.html')

# Site configuration
@app.route('/admin/config', methods=['GET', 'POST'])
@admin_required
def admin_config():
    if request.method == 'POST':
        fields = ['site_name', 'tagline', 'hero_title', 'contact_phone', 'contact_email',
                   'address', 'whatsapp', 'instagram', 'facebook', 'footer_note']
        for field in fields:
            val = request.form.get(field, '').strip()
            Config.query.filter_by(key=field).delete()
            db.session.add(Config(key=field, value=val))

        theme_choice = request.form.get('theme', DEFAULT_THEME)
        if theme_choice not in THEMES:
            theme_choice = DEFAULT_THEME
        Config.query.filter_by(key='theme').delete()
        db.session.add(Config(key='theme', value=theme_choice))

        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename != '':
            filename = secure_filename(logo_file.filename)
            logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            Config.query.filter_by(key='logo_filename').delete()
            db.session.add(Config(key='logo_filename', value=filename))

        db.session.commit()
        flash('Configuration updated.', 'success')
        return redirect(url_for('admin_config'))

    def cfg(key, default=''):
        row = Config.query.filter_by(key=key).first()
        return row.value if row and row.value else default

    theme_key = cfg('theme', DEFAULT_THEME)
    if theme_key not in THEMES:
        theme_key = DEFAULT_THEME

    return render_template('admin/config.html',
                           current_site_name=cfg('site_name', 'Bellesence'),
                           current_tagline=cfg('tagline'),
                           current_hero_title=cfg('hero_title', 'Our Perfumes'),
                           current_contact_phone=cfg('contact_phone'),
                           current_contact_email=cfg('contact_email'),
                           current_address=cfg('address'),
                           current_whatsapp=cfg('whatsapp'),
                           current_instagram=cfg('instagram'),
                           current_facebook=cfg('facebook'),
                           current_footer_note=cfg('footer_note'),
                           current_theme=theme_key,
                           current_logo=cfg('logo_filename') or None,
                           themes=THEMES)

# Order management
@app.route('/admin/orders')
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders)

@app.route('/admin/orders/<int:id>/status', methods=['POST'])
@admin_required
def update_order_status(id):
    order = Order.query.get_or_404(id)
    status = request.form.get('status', 'pending')
    valid_statuses = ['pending', 'confirmed', 'shipped', 'completed', 'cancelled']
    if status in valid_statuses:
        order.status = status
        db.session.commit()
        flash('Order status updated.', 'success')
    return redirect(url_for('admin_orders'))

@app.route('/admin/orders/<int:id>/delete')
@admin_required
def delete_order(id):
    order = Order.query.get_or_404(id)
    db.session.delete(order)
    db.session.commit()
    flash('Order deleted.', 'success')
    return redirect(url_for('admin_orders'))

# Product management
@app.route('/admin/products')
@admin_required
def admin_products():
    products = Product.query.all()
    return render_template('admin/products.html', products=products)

def _save_upload(file_storage):
    filename = secure_filename(file_storage.filename)
    base, ext = os.path.splitext(filename)
    candidate = filename
    i = 1
    while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], candidate)):
        candidate = f"{base}-{i}{ext}"
        i += 1
    file_storage.save(os.path.join(app.config['UPLOAD_FOLDER'], candidate))
    return candidate

@app.route('/admin/products/add', methods=['GET', 'POST'])
@admin_required
def add_product():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])

        images = request.files.getlist('images')
        saved_filenames = []
        for image_file in images:
            if image_file and image_file.filename != '':
                saved_filenames.append(_save_upload(image_file))

        cover = saved_filenames[0] if saved_filenames else None

        product = Product(name=name, description=description, price=price, image_filename=cover)
        db.session.add(product)
        db.session.flush()

        for idx, fn in enumerate(saved_filenames):
            db.session.add(ProductImage(product_id=product.id, filename=fn, sort_order=idx))

        db.session.commit()
        flash('Product added!', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/add_product.html')

@app.route('/admin/products/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        product.name = request.form['name']
        product.description = request.form['description']
        product.price = float(request.form['price'])

        images = request.files.getlist('images')
        new_filenames = []
        for image_file in images:
            if image_file and image_file.filename != '':
                new_filenames.append(_save_upload(image_file))

        if new_filenames:
            start_order = len(product.images)
            for idx, fn in enumerate(new_filenames):
                db.session.add(ProductImage(product_id=product.id, filename=fn, sort_order=start_order + idx))
            if not product.image_filename:
                product.image_filename = new_filenames[0]

        db.session.commit()
        flash('Product updated.', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/edit_product.html', product=product)

@app.route('/admin/products/<int:product_id>/images/<int:image_id>/delete')
@admin_required
def delete_product_image(product_id, image_id):
    product = Product.query.get_or_404(product_id)
    img = ProductImage.query.get_or_404(image_id)
    if img.product_id != product.id:
        flash('Image does not belong to this product.', 'danger')
        return redirect(url_for('edit_product', id=product_id))

    was_cover = (product.image_filename == img.filename)
    db.session.delete(img)
    db.session.flush()

    if was_cover:
        remaining = ProductImage.query.filter_by(product_id=product.id).order_by(ProductImage.sort_order).first()
        product.image_filename = remaining.filename if remaining else None

    db.session.commit()
    flash('Image removed.', 'success')
    return redirect(url_for('edit_product', id=product_id))

@app.route('/admin/products/<int:product_id>/images/<int:image_id>/make-cover')
@admin_required
def make_cover_image(product_id, image_id):
    product = Product.query.get_or_404(product_id)
    img = ProductImage.query.get_or_404(image_id)
    if img.product_id != product.id:
        flash('Image does not belong to this product.', 'danger')
        return redirect(url_for('edit_product', id=product_id))
    product.image_filename = img.filename
    db.session.commit()
    flash('Cover image updated.', 'success')
    return redirect(url_for('edit_product', id=product_id))

@app.route('/admin/products/delete/<int:id>')
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'success')
    return redirect(url_for('admin_products'))

# --------------------- INIT DB ---------------------
@app.before_request
def create_tables():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
