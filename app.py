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
    image_filename = db.Column(db.String(300), nullable=True)

# --------------------- CONTEXT PROCESSOR ---------------------
@app.context_processor
def inject_config():
    site_name = Config.query.filter_by(key='site_name').first()
    logo = Config.query.filter_by(key='logo_filename').first()
    return {
        'site_name': site_name.value if site_name else 'Bellesence',
        'logo_filename': logo.value if logo else None
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
        site_name = request.form.get('site_name', '').strip()
        Config.query.filter_by(key='site_name').delete()
        db.session.add(Config(key='site_name', value=site_name))

        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename != '':
            filename = secure_filename(logo_file.filename)
            logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            Config.query.filter_by(key='logo_filename').delete()
            db.session.add(Config(key='logo_filename', value=filename))

        db.session.commit()
        flash('Configuration updated.', 'success')
        return redirect(url_for('admin_config'))

    site_name = Config.query.filter_by(key='site_name').first()
    logo = Config.query.filter_by(key='logo_filename').first()
    return render_template('admin/config.html',
                           current_site_name=site_name.value if site_name else 'Bellesence',
                           current_logo=logo.value if logo else None)

# Product management
@app.route('/admin/products')
@admin_required
def admin_products():
    products = Product.query.all()
    return render_template('admin/products.html', products=products)

@app.route('/admin/products/add', methods=['GET', 'POST'])
@admin_required
def add_product():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])
        image_file = request.files.get('image')
        filename = None
        if image_file and image_file.filename != '':
            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        product = Product(name=name, description=description, price=price, image_filename=filename)
        db.session.add(product)
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
        image_file = request.files.get('image')
        if image_file and image_file.filename != '':
            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            product.image_filename = filename
        db.session.commit()
        flash('Product updated.', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/edit_product.html', product=product)

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
