import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime

# Initialize Flask application
app = Flask(__name__)

# Configure the database URI from Render's environment variable
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key') # For flash messages

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize Flask-Migrate for database migrations
migrate = Migrate(app, db)

# -------------------- Database Models --------------------

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    description = db.Column(db.Text)

    def __repr__(self):
        return f'<Product {self.name}>'

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product', backref=db.backref('transactions', lazy=True))

    def __repr__(self):
        return f'<Transaction {self.id}>'

# -------------------- Flask Routes (Admin Interface) --------------------

@app.route('/admin/products')
def list_products():
    products = Product.query.all()
    return render_template('admin/products.html', products=products)

@app.route('/admin/product/new', methods=['GET', 'POST'])
def new_product():
    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        stock = int(request.form['stock'])
        description = request.form.get('description')
        new_product = Product(name=name, price=price, stock=stock, description=description)
        db.session.add(new_product)
        db.session.commit()
        flash(f'Product "{name}" added successfully!', 'success')
        return redirect(url_for('list_products'))
    return render_template('admin/new_product.html')

@app.route('/admin/product/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        product.name = request.form['name']
        product.price = float(request.form['price'])
        product.stock = int(request.form['stock'])
        product.description = request.form.get('description')
        db.session.commit()
        flash(f'Product "{product.name}" updated successfully!', 'success')
        return redirect(url_for('list_products'))
    return render_template('admin/edit_product.html', product=product)

# -------------------- Flask Routes (Vending Machine Interface) --------------------

@app.route('/vending_machine')
def vending_machine():
    products = Product.query.all()
    return render_template('vending_machine.html', products=products)

@app.route('/select_product/<int:product_id>')
def select_product(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('select_product.html', product=product)

@app.route('/process_payment/<int:product_id>', methods=['POST'])
def process_payment(product_id):
    product = Product.query.get_or_404(product_id)
    # Placeholder for payment processing integration
    payment_successful = True
    if payment_successful and product.stock > 0:
        product.stock -= 1
        new_transaction = Transaction(product_id=product.id, quantity=1, amount_paid=product.price)
        db.session.add(new_transaction)
        db.session.commit()
        flash(f'Successfully purchased {product.name} for ${product.price}!', 'success')
        return redirect(url_for('vending_machine')) # Redirect to a confirmation page later
    elif not payment_successful:
        flash('Payment failed. Please try again.', 'danger')
    else:
        flash(f'{product.name} is out of stock.', 'warning')
    return redirect(url_for('vending_machine'))

# -------------------- Main Execution Block --------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all() # This will create the tables if they don't exist
    app.run(debug=True)