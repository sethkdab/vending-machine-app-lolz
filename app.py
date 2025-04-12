# === app.py (Cleaned and Merged) ===
import os
from dotenv import load_dotenv # Import load_dotenv
from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, flash, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import time # Keep time for command timestamp if needed

# Load environment variables from .env file (especially for local development)
load_dotenv()

# Initialize Flask application (Only ONCE)
app = Flask(__name__)

# --- Configuration ---
# Get DATABASE_URL from environment variables (loaded from .env locally or set by Render)
db_url = os.environ.get('DATABASE_URL')
if not db_url:
    raise ValueError("DATABASE_URL environment variable not set. "
                     "Ensure it's in your .env file locally or set in your deployment environment.")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Good practice to disable

# Get SECRET_KEY from environment variables
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    print("ERROR: SECRET_KEY environment variable not set. Cannot run securely.")
    # Using an insecure default only as a last resort for initial testing:
    secret_key = 'temporary-insecure-key-please-set-env'
    # In a real production scenario, you might want to raise ValueError here instead.

app.secret_key = secret_key # Needed for flash messages

# --- Database Setup (Only ONCE) ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models (Consolidated) ---

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    description = db.Column(db.Text, nullable=True) # Keep description if needed
    motor_id = db.Column(db.Integer, unique=True, nullable=False) # From flask_server.py version
    image_url = db.Column(db.String(255), nullable=True) # From flask_server.py version

    def __repr__(self):
        return f'<Product {self.id}: {self.name} (Motor {self.motor_id})>'

class VendCommand(db.Model): # From flask_server.py version
    id = db.Column(db.Integer, primary_key=True)
    vend_id = db.Column(db.String(80), nullable=False) # ID of the specific vending machine
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    motor_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False, default='pending') # Status: pending, acknowledged_success, acknowledged_failure, expired
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship('Product', backref=db.backref('commands', lazy=True)) # Use 'commands' backref

    def __repr__(self):
        return f'<Command {self.id} for {self.vend_id} - Motor {self.motor_id} ({self.status})>'

class Transaction(db.Model): # Kept for potential logging
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    amount_paid = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # Optional: Link to the command that generated this transaction
    # vend_command_id = db.Column(db.Integer, db.ForeignKey('vend_command.id'), nullable=True)

    product = db.relationship('Product', backref=db.backref('transactions', lazy=True))

    def __repr__(self):
        return f'<Transaction {self.id} for Product {self.product_id}>'


# --- User Routes (Using the command-based flow) ---

@app.route('/')
def index():
    # Main user view for a specific vending machine
    vend_id = request.args.get('vend_id')
    if not vend_id:
        # Consider a better landing page or clearer instructions
        return "Error: Missing 'vend_id' parameter. Use /?vend_id=YOUR_MACHINE_ID", 400

    try:
        products = Product.query.filter(Product.stock > 0).order_by(Product.name).all()
    except Exception as e:
        print(f"Database error fetching products for index: {e}")
        flash("Error loading products. Please try again later.", "error")
        products = []
    # Assumes you have an 'index.html' template
    return render_template('index.html', vend_id=vend_id, products=products)

# Optional general browse page
@app.route('/browse')
def browse_products():
    try:
        products = Product.query.filter(Product.stock > 0).order_by(Product.name).all()
    except Exception as e:
        print(f"Database error fetching products for browse: {e}")
        flash("Error loading products. Please try again later.", "error")
        products = []
    # You'll need a 'browse.html' template for this
    return render_template('browse.html', products=products)


@app.route('/buy/<int:product_id>', methods=['POST'])
def buy_item(product_id):
    vend_id = request.form.get('vend_id')

    if not vend_id:
        flash("Vending machine ID is missing.", "error")
        return redirect(url_for('browse_products')) # Redirect to browse if no ID

    # Use get_or_404 for cleaner product not found handling
    product = Product.query.get_or_404(product_id)

    redirect_url = url_for('index', vend_id=vend_id) # URL to redirect back to

    if product.stock <= 0:
        flash(f"'{product.name}' is out of stock.", "warning")
        return redirect(redirect_url)

    # Check for existing pending commands for THIS machine
    try:
        existing_command = VendCommand.query.filter_by(
            vend_id=vend_id,
            status='pending'
        ).first()

        if existing_command:
            flash("Another purchase is already in progress for this machine. Please wait.", "warning")
            return redirect(redirect_url)

        # --- Create Command and Optimistic Update ---
        new_command = VendCommand(
            vend_id=vend_id,
            product_id=product.id,
            motor_id=product.motor_id,
            status='pending'
        )
        db.session.add(new_command)

        product.stock -= 1 # Decrement stock

        db.session.commit() # Commit both changes

        flash(f"Purchase initiated for '{product.name}'. Please wait for the item.", "info")
        print(f"[BUY] Initiated command {new_command.id} for {vend_id}, motor {product.motor_id}. Stock reduced to {product.stock}.")

    except Exception as e:
        db.session.rollback() # Rollback changes if anything failed
        flash("An error occurred while initiating the purchase. Please try again.", "error")
        print(f"[ERROR] Failed to initiate purchase for product {product_id} on {vend_id}: {e}")

    return redirect(redirect_url)


# --- Vending Machine Client Routes ---

@app.route('/get_command', methods=['GET'])
def get_command():
    """Called by the vending machine client (ESP32)"""
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return jsonify({"error": "vend_id is required"}), 400

    try:
        command = VendCommand.query.filter_by(
            vend_id=vend_id,
            status='pending'
        ).order_by(VendCommand.created_at.asc()).first()

        if command:
            print(f"[GET_COMMAND] Sending command {command.id} (Motor {command.motor_id}) to {vend_id}")
            return jsonify({
                "motor_id": command.motor_id,
                "command_id": command.id
            })
        else:
            # No pending commands is normal, return empty response
            return jsonify({"motor_id": None, "command_id": None})
    except Exception as e:
        print(f"[ERROR] Database error in get_command for {vend_id}: {e}")
        return jsonify({"error": "Database error fetching command"}), 500


@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    """Called by the vending machine client (ESP32) after attempting command"""
    data = request.json
    if not data:
        return jsonify({"error": "Request must be JSON"}), 400

    vend_id = data.get("vend_id")
    command_id = data.get("command_id")
    ack_status = data.get("status") # Expect "success" or "failure"

    if not all([vend_id, command_id, ack_status]):
        return jsonify({"error": "Missing vend_id, command_id, or status"}), 400

    try:
        # Use db.session.get for primary key lookup (more efficient)
        command = db.session.get(VendCommand, command_id)

        if not command:
            print(f"[ACK_ERROR] Command ID {command_id} not found.")
            return jsonify({"error": "Command not found"}), 404

        if command.vend_id != vend_id:
            print(f"[ACK_ERROR] Mismatched vend_id for command {command_id}. Expected {command.vend_id}, got {vend_id}.")
            return jsonify({"error": "Vending machine ID mismatch"}), 400

        if command.status != 'pending':
            print(f"[ACK_WARN] Command {command_id} already processed (status: {command.status}). Ignoring.")
            return jsonify({"message": "Command already processed"}), 200 # Not an error

        log_prefix = f"[ACK_{ack_status.upper()}]"

        if ack_status == "success":
            command.status = "acknowledged_success"
            command.acknowledged_at = datetime.utcnow()
            # Log the successful transaction here if desired
            try:
                # Ensure product is loaded for price access
                product = db.session.get(Product, command.product_id)
                if product:
                    transaction = Transaction(product_id=command.product_id, quantity=1, amount_paid=product.price)
                    db.session.add(transaction)
                    print(f"{log_prefix} Command {command_id} success for {vend_id}. Transaction logged.")
                else:
                    print(f"{log_prefix} Command {command_id} success for {vend_id}, but product {command.product_id} not found for transaction logging.")
            except Exception as log_e:
                print(f"{log_prefix} Command {command_id} success for {vend_id}. FAILED TO LOG TRANSACTION: {log_e}")
                # Continue committing the command status update even if logging fails

        elif ack_status == "failure":
            command.status = "acknowledged_failure"
            command.acknowledged_at = datetime.utcnow()
            # --- Rollback Stock ---
            product = db.session.get(Product, command.product_id)
            if product:
                product.stock += 1
                print(f"{log_prefix} Command {command.id} failed for {vend_id}. Rolled back stock for product {product.id} to {product.stock}.")
            else:
                print(f"{log_prefix} Command {command.id} failed, BUT COULD NOT FIND product {command.product_id} to roll back stock!")
        else:
            print(f"[ACK_ERROR] Invalid status '{ack_status}' received for command {command_id}.")
            return jsonify({"error": "Invalid status provided"}), 400

        db.session.commit() # Commit status update, stock rollback (if any), and transaction log

    except Exception as e:
        db.session.rollback()
        print(f"[ACK_DB_ERROR] Failed DB operation during acknowledgment for command {command_id}: {e}")
        return jsonify({"error": "Database error during acknowledgment"}), 500

    return jsonify({"message": "Acknowledgment received"}), 200


# --- Admin Routes ---

@app.route('/admin')
def admin_dashboard():
    # Simple dashboard page using command counts
    try:
        product_count = Product.query.count()
        pending_commands = VendCommand.query.filter_by(status='pending').count()
        failed_commands = VendCommand.query.filter_by(status='acknowledged_failure').count()
    except Exception as e:
        print(f"Database error fetching dashboard data: {e}")
        flash("Error fetching dashboard data.", "error")
        product_count, pending_commands, failed_commands = 0, 0, 0

    # Assumes you have 'admin/dashboard.html' template
    return render_template('admin/dashboard.html',
                           product_count=product_count,
                           pending_commands=pending_commands,
                           failed_commands=failed_commands)

@app.route('/admin/products')
def list_products():
    try:
        products = Product.query.order_by(Product.name).all()
    except Exception as e:
        print(f"Database error fetching products: {e}")
        flash("Error fetching products.", "error")
        products = []
     # Assumes you have 'admin/products.html' template
    return render_template('admin/products.html', products=products)

# Add Product Route
@app.route('/admin/product/new', methods=['GET', 'POST'])
def new_product():
    if request.method == 'POST':
        try:
            # Get all fields from form
            name = request.form['name']
            price = float(request.form['price'])
            stock = int(request.form['stock'])
            motor_id = int(request.form['motor_id'])
            description = request.form.get('description') # Optional
            image_url = request.form.get('image_url')   # Optional

            # Validation
            if not name or price <= 0 or stock < 0 or motor_id <= 0:
                flash("Invalid data: Name required, price/motor_id positive, stock non-negative.", 'warning')
                # Pass submitted data back to form
                return render_template('admin/product_form.html', action="Add New", product=request.form)

            # Check motor_id uniqueness
            existing = Product.query.filter_by(motor_id=motor_id).first()
            if existing:
                 flash(f"Motor ID {motor_id} is already assigned to product '{existing.name}'.", 'error')
                 return render_template('admin/product_form.html', action="Add New", product=request.form)

            # Create new product with all fields
            new_product = Product(name=name, price=price, stock=stock,
                                  motor_id=motor_id, description=description, image_url=image_url)
            db.session.add(new_product)
            db.session.commit()
            flash(f'Product "{name}" added successfully!', 'success')
            return redirect(url_for('list_products'))

        except ValueError:
             flash("Invalid number format for price, stock, or motor ID.", 'danger')
             return render_template('admin/product_form.html', action="Add New", product=request.form)
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", 'danger')
            print(f"[ADMIN_ADD_ERROR] {e}")
            return render_template('admin/product_form.html', action="Add New", product=request.form)

    # GET request
    # Assumes you have 'admin/product_form.html' template
    return render_template('admin/product_form.html', action="Add New", product=None)


# Edit Product Route - using 'id' from URL
@app.route('/admin/product/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    product = Product.query.get_or_404(id)

    if request.method == 'POST':
        try:
            original_motor_id = product.motor_id
            new_motor_id = int(request.form['motor_id'])

            # Update all fields from form
            product.name = request.form['name']
            product.price = float(request.form['price'])
            product.stock = int(request.form['stock'])
            product.motor_id = new_motor_id
            product.description = request.form.get('description') # Optional
            product.image_url = request.form.get('image_url')   # Optional

            # Validation
            if not product.name or product.price <= 0 or product.stock < 0 or product.motor_id <= 0:
                flash("Invalid data: Name required, price/motor_id positive, stock non-negative.", 'warning')
                # Don't commit, just re-render form with current (attempted) values
                return render_template('admin/product_form.html', action="Edit", product=product)

            # Check motor_id uniqueness if changed
            if new_motor_id != original_motor_id:
                existing = Product.query.filter(Product.motor_id == new_motor_id, Product.id != id).first()
                if existing:
                    flash(f"Motor ID {new_motor_id} is already assigned to product '{existing.name}'.", 'error')
                    # Revert motor_id change before re-rendering form? Or show attempted value? Let's show attempted
                    # No need to change product.motor_id back here if we just re-render
                    return render_template('admin/product_form.html', action="Edit", product=product)

            db.session.commit() # Commit changes if validation and checks pass
            flash(f'Product "{product.name}" updated successfully!', 'success')
            return redirect(url_for('list_products'))

        except ValueError:
             flash("Invalid number format for price, stock, or motor ID.", 'danger')
             # Preserve edits in form for correction
             # Manually assign from form to ensure attempted values are shown
             product.name=request.form['name']
             product.price=request.form['price']
             product.stock=request.form['stock']
             product.motor_id=request.form['motor_id']
             product.description=request.form.get('description')
             product.image_url=request.form.get('image_url')
             return render_template('admin/product_form.html', action="Edit", product=product)
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", 'danger')
            print(f"[ADMIN_EDIT_ERROR] {e}")
            # Re-render form with original product data on unexpected error
            product = Product.query.get_or_404(id) # Re-fetch original data
            return render_template('admin/product_form.html', action="Edit", product=product)

    # GET request - Show form with existing product data
    return render_template('admin/product_form.html', action="Edit", product=product)


# Delete Product Route - using 'id' from URL
@app.route('/admin/product/delete/<int:id>', methods=['POST'])
def delete_product(id):
    product = Product.query.get_or_404(id)
    product_name = product.name # Store name before potential deletion

    try:
        # Check dependencies before deleting
        # Use lazy='dynamic' on backrefs to make these checks efficient
        if product.commands.first() or product.transactions.first():
             flash(f"Cannot delete '{product.name}' as it has associated command or transaction history.", 'warning')
             return redirect(url_for('list_products'))

        db.session.delete(product)
        db.session.commit()
        flash(f'Product "{product_name}" deleted successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting product '{product_name}': {str(e)}", 'danger')
        print(f"[ADMIN_DELETE_ERROR] {e}")

    return redirect(url_for('list_products'))


# --- Main Execution Block ---
if __name__ == '__main__':
    # For local development using 'python app.py'
    # Render uses the Start Command (e.g., gunicorn app:app)
    print("Starting Flask development server...")
    # Set debug=False in production environments for security and performance
    # Render might override this via environment variables (e.g., FLASK_DEBUG=0)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG', 'true').lower() == 'true')