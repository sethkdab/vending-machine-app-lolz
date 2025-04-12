import os
from dotenv import load_dotenv # Import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
# Add extra prints for debugging
print("--- DEBUG: app.py starting ---")
print(f"--- DEBUG: Current working directory: {os.getcwd()} ---")

# Load environment variables from .env file (especially for local development)
print("--- DEBUG: Attempting to load .env file ---")
# Use verbose=True to see if python-dotenv reports finding the file
# Use override=True just in case something weird is happening
loaded_successfully = load_dotenv(verbose=True, override=True)
print(f"--- DEBUG: load_dotenv() finished. Found and loaded file? {loaded_successfully} ---")

# Print the crucial variables RIGHT AFTER loading .env
print(f"--- DEBUG: Value of os.environ.get('DATABASE_URL') IMMEDIATELY after load_dotenv: {os.environ.get('DATABASE_URL')} ---")
print(f"--- DEBUG: Value of os.environ.get('SECRET_KEY') IMMEDIATELY after load_dotenv: {os.environ.get('SECRET_KEY')} ---")

# Load environment variables from .env file (especially for local development)
load_dotenv()

# Initialize Flask application
app = Flask(__name__)

# --- Configuration ---
# Get DATABASE_URL from environment variables (loaded from .env locally or set by Render)
db_url = os.environ.get('DATABASE_URL')
if not db_url:
    # Provide a clear error if the database URL isn't found.
    raise ValueError("DATABASE_URL environment variable not set. "
                     "Ensure it's in your .env file locally or set in your deployment environment.")

# Optional: Automatically handle postgres:// -> postgresql:// conversion for Render/Heroku compatibility
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Good practice to disable

# Get SECRET_KEY from environment variables
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    # Provide a default BUT WARN that it's insecure for production
    print("WARNING: SECRET_KEY environment variable not set. Using a default insecure key for development.")
    secret_key = 'default-insecure-secret-key-CHANGE-ME'
    # You could also raise an error here if you want to force setting it:
    # raise ValueError("SECRET_KEY environment variable not set.")

app.secret_key = secret_key # Needed for flash messages

# --- Database Setup ---
# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize Flask-Migrate for database migrations
# Make sure Flask-Migrate is installed: pip install Flask-Migrate
migrate = Migrate(app, db)

# -------------------- Database Models --------------------

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    description = db.Column(db.Text, nullable=True) # Allow description to be optional

    def __repr__(self):
        return f'<Product {self.id}: {self.name}>'

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # Establish relationship (optional: specify cascade or backref details if needed)
    product = db.relationship('Product', backref=db.backref('transactions', lazy=True))

    def __repr__(self):
        return f'<Transaction {self.id} for Product {self.product_id}>'

# -------------------- Flask Routes (Admin Interface) --------------------
# Consider adding authentication/authorization later for admin routes

@app.route('/admin') # Simple admin landing page
def admin_index():
    return redirect(url_for('list_products'))

@app.route('/admin/products')
def list_products():
    # Order products for consistent display
    products = Product.query.order_by(Product.name).all()
    return render_template('admin/products.html', products=products)

@app.route('/admin/product/new', methods=['GET', 'POST'])
def new_product():
    if request.method == 'POST':
        try:
            name = request.form['name']
            price = float(request.form['price'])
            stock = int(request.form['stock'])
            description = request.form.get('description')

            # Basic Validation
            if not name or price <= 0 or stock < 0:
                 flash('Invalid input. Name is required, price must be positive, stock cannot be negative.', 'warning')
                 return render_template('admin/new_product.html') # Re-render form

            new_product = Product(name=name, price=price, stock=stock, description=description)
            db.session.add(new_product)
            db.session.commit()
            flash(f'Product "{name}" added successfully!', 'success')
            return redirect(url_for('list_products'))
        except ValueError:
            flash('Invalid number format for price or stock.', 'danger')
            # You might want to pass form data back to the template here
            return render_template('admin/new_product.html')
        except Exception as e:
            db.session.rollback() # Rollback in case of other DB errors
            flash(f'An error occurred: {str(e)}', 'danger')
            print(f"Error adding product: {e}") # Log the error
            return render_template('admin/new_product.html')

    # GET request
    return render_template('admin/new_product.html')

@app.route('/admin/product/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    product = Product.query.get_or_404(id) # Use get_or_404 for better error handling
    if request.method == 'POST':
        try:
            product.name = request.form['name']
            product.price = float(request.form['price'])
            product.stock = int(request.form['stock'])
            product.description = request.form.get('description')

            # Basic Validation
            if not product.name or product.price <= 0 or product.stock < 0:
                 flash('Invalid input. Name is required, price must be positive, stock cannot be negative.', 'warning')
                 return render_template('admin/edit_product.html', product=product) # Re-render form

            db.session.commit()
            flash(f'Product "{product.name}" updated successfully!', 'success')
            return redirect(url_for('list_products'))
        except ValueError:
            flash('Invalid number format for price or stock.', 'danger')
            return render_template('admin/edit_product.html', product=product) # Re-render form
        except Exception as e:
            db.session.rollback() # Rollback in case of other DB errors
            flash(f'An error occurred: {str(e)}', 'danger')
            print(f"Error editing product {id}: {e}") # Log the error
            return render_template('admin/edit_product.html', product=product)

    # GET request
    return render_template('admin/edit_product.html', product=product)

# Optional: Add a route for deleting products
@app.route('/admin/product/delete/<int:id>', methods=['POST'])
def delete_product(id):
    product = Product.query.get_or_404(id)
    try:
        # Check for related transactions before deleting? Optional.
        # if product.transactions:
        #    flash(f'Cannot delete "{product.name}" as it has transaction history.', 'warning')
        #    return redirect(url_for('list_products'))

        product_name = product.name # Get name before deletion
        db.session.delete(product)
        db.session.commit()
        flash(f'Product "{product_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting product: {str(e)}', 'danger')
        print(f"Error deleting product {id}: {e}") # Log the error
    return redirect(url_for('list_products'))


# -------------------- Flask Routes (Vending Machine Interface) --------------------

# Optional: Redirect root URL to the vending machine?
@app.route('/')
def home():
    return redirect(url_for('vending_machine'))

@app.route('/vending_machine')
def vending_machine():
    # Only show products with stock > 0? Or show all and disable button? (Current template handles disabling)
    products = Product.query.order_by(Product.name).all()
    return render_template('vending_machine.html', products=products)

@app.route('/select_product/<int:product_id>')
def select_product(product_id):
    product = Product.query.get_or_404(product_id)
    if product.stock <= 0:
        flash(f'"{product.name}" is out of stock.', 'warning')
        return redirect(url_for('vending_machine'))
    return render_template('select_product.html', product=product)

@app.route('/process_payment/<int:product_id>', methods=['POST'])
def process_payment(product_id):
    # --- Important: Database Transaction ---
    # It's safer to wrap database changes related to a single action in a try/except/commit/rollback block
    product = Product.query.get_or_404(product_id)

    # Re-check stock within the request/transaction for safety (race condition)
    if product.stock <= 0:
        flash(f'Sorry, "{product.name}" just went out of stock.', 'warning')
        return redirect(url_for('vending_machine'))

    # Placeholder for actual payment processing integration
    # In a real app, you'd call a payment gateway API here.
    payment_successful = True # Simulate successful payment

    if payment_successful:
        try:
            # Decrement stock
            product.stock -= 1

            # Record the transaction
            new_transaction = Transaction(product_id=product.id, quantity=1, amount_paid=product.price)
            db.session.add(new_transaction)
            # db.session.add(product) # No need to add product again if just modifying

            # Commit both changes together
            db.session.commit()

            flash(f'Successfully purchased {product.name} for £{product.price:.2f}!', 'success') # Use £ or $ as appropriate
            # Redirect to a dedicated confirmation page might be better UX
            return redirect(url_for('purchase_confirmation', transaction_id=new_transaction.id))

        except Exception as e:
            db.session.rollback() # Rollback BOTH stock and transaction if commit fails
            flash('An error occurred during the purchase process. Please try again.', 'danger')
            print(f"Error processing payment for product {product_id}: {e}")
            return redirect(url_for('vending_machine'))
    else:
        # Payment failed (based on the placeholder)
        flash('Payment failed. Please try again.', 'danger')
        return redirect(url_for('select_product', product_id=product.id)) # Go back to selection

# Optional: Confirmation page
@app.route('/confirmation/<int:transaction_id>')
def purchase_confirmation(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    # You could pass transaction.product here too if needed
    return render_template('confirmation.html', transaction=transaction)


# -------------------- Main Execution Block --------------------

# The following block is only executed when you run 'python app.py' directly
# It's NOT run when using 'flask run' or a production server like Gunicorn
if __name__ == '__main__':
    # DO NOT use db.create_all() when using Flask-Migrate
    # Migrations are handled by 'flask db upgrade'
    # with app.app_context():
    #    db.create_all() # REMOVE THIS LINE

    # Use Flask's built-in server for development.
    # Render/Gunicorn will use a different command to start the app.
    # Host '0.0.0.0' makes it accessible on your network (optional)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
    # Set debug=False in production environments! (Though Render usually handles this)