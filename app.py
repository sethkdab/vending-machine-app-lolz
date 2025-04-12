# === app.py ===
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
# Remove the debug prints now that dotenv is working
load_dotenv()

# Initialize Flask application
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
    # Consider raising an error in production environments:
    # raise ValueError("SECRET_KEY environment variable not set.")
    # Using an insecure default only as a last resort for initial testing:
    secret_key = 'temporary-insecure-key-please-set-env'

app.secret_key = secret_key # Needed for flash messages

# --- Database Setup ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models ---
# Using not set. Using a default insecure key.")
secret_key = 'your_actual_secret_key_here'
app.secret_key = secret_key

# --- Database Setup (Only ONCE) ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models (Combined) ---

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False) # Increased length slightly
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    description = db.Column(db.Text, nullable=True) # From app.py
    motor_id = db.Column(db.Integer, unique=True, nullable=False) # From flask_server.py
    image_url = db.Column(db.String(255), nullable=True) # From flask_server.py

    def __repr__(self):
        # Updated repr to include more info
        return f'<Product {self.id}: {self.name} (Motor {self.motor_id})>'

class Transaction(db.Model): # Keep Transaction model for logging successful simulated payments if desired
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product', backref=db.backref('transactions', lazy=True)) # Keep relationship

    def __repr__(self):
        return f'<Transaction {self.id} for Product {self.product_id}>'

class VendCommand(db.Model): # Model from flask_server.py
    id = db.Column(db.Integer, primary_key=True)
    vend_id = db.Column(db.String(80), nullable=False) # ID of the specific vending machine
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    motor_id = db.Column(db.Integer, nullable=False)
    # Status: pending, acknowledged_success, acknowledged_failure, expired
    status = db.Column(db.String(30), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_at = db.Column(db.DateTime, nullable=True)

    # Use the same relationship defined for Transaction (if Product backref is just 'commands')
    # Or define a new one if needed. Let's assume 'commands' is fine for now.
    product = db.relationship('Product', backref=db.backref('commands', lazy='dynamic')) # Changed lazy to dynamic as example

    def __repr__(self):
        return f'<Command {self.id} for {self.vend_id} - Motor {self.motor_id} ({self.status})>'

# --- User Routes (Using the command-based flow from flask_server.py) ---

# This is the main entry point for a specific vending machine
@app.route('/')
def index():
    # This route expects a vend_id to identify the machine
    vend_id = request.args.get('vend_id')
    if not vend_id:
        # Return a clearer error or maybe redirect to a general browse page
        return "Error: Missing 'vend_id' parameter. Use /?vend_id=YOUR_MACHINE_ID", 400

    # Fetch products with stock > 0 for this machine's view
    # Note: We assume all products are available in all machines for now.
    # You might need a more complex model later if products are machine-specific.
    products = Product.query.filter(Product.stock > 0).order_by(Product.name).all()
    # Assumes you have an 'index.html' template
    return render_template('index.html', vend_id=vend_id, products=products)

# Add a general browse page (optional)
@app.route('/browse')
def browse_products():
    products = Product.query.filter(Product.stock > 0).order_by(Product.name).all()
    # You'll need a 'browse.html' template for this
    return render_template('browse.html', products=products)


@app.route('/buy/<int:product_id>', methods=['POST'])
def buy_item(product_id):
    # Logic taken from flask_server.py
    vend_id = request.form.get('vend_id')

    if not vend_id:
        flash("Vending machine ID is missing.", "error")
        # Redirect appropriately - maybe back to browse or show error?
        # Redirecting to index without vend_id will fail the index route.
        return redirect(url_for('browse_products')) # Redirect to browse if ID missing

    # Use get_or_404 for cleaner product not found handling
    product = Product.query.get_or_404(product_id)

    # Use the specific vend_id for redirection
    redirect_url = url_for('index', vend_id=vend_id)

    if product.stock <= 0:
        flash(f"'{product.name}' is out of stock.", "warning")
        return redirect(redirect_url)

    # Check for existing pending commands for THIS machine
    existing_command = VendCommand.query.filter_by(
        vend_id=vend_id,
        status='pending'
    ).first()

    if existing_command:
        flash("Another purchase is already in progress for this machine. Please wait.", "warning")
        return redirect(redirect_url)

    try:
        # Create the command for the ESP32
        new_command = VendCommand(
            vend_id=vend_id,
            product_id=product.id,
            motor_id=product.motor_id, # Use motor_id from Product model
            status='pending'
        )
        db.session.add(new_command)

        # Optimistically decrement stock
        product.stock -= 1
        # db.session.add(product) # Not needed, SQLAlchemy tracks changes

        db.session.commit()

        flash(f"Purchase initiated for '{product.name}'. Please wait for the item.", "info") # Use info or success
        print(f"[BUY] Initiated command {new_command.id} for {vend_id}, motor {product.motor_id}. Stock reduced to {product.stock}.")

    except Exception as e:
        db.session.rollback()
        flash("An error occurred while initiating the purchase. Please try again.", "error")
        print(f"[ERROR] Failed to initiate purchase for product {product_id} on {vend_id}: {e}")

    return redirect(redirect_url)


# --- Vending Machine Client Routes (From flask_server.py) ---

@app.route('/get_command', methods=['GET'])
def get_command():
    """Called by the vending machine client ( the models from flask_server.py which include ESP32 relevant fields

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    motor_id = db.Column(db.Integer, unique=True, nullable=False) # Link to vending machine motor
    image_url = db.Column(db.String(255), nullable=True) # Optional: Image for the product

    def __repr__(self):
        return f'<Product {self.id}: {self.name} (Motor {self.motor_id})>'

class VendCommand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vend_id = db.Column(db.String(80), nullable=False) # ID of the specific vending machine
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    motor_id = db.Column(db.Integer, nullable=False)
    # Status: pending, acknowledged_success, acknowledged_failure, expired
    status = db.Column(db.String(30), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship('Product', backref=db.backref('commands', lazy=True))

    def __repr__(self):
        return f'<Command {self.id} for {self.vend_id} - Motor {self.motor_id} ({self.status})>'

# Optional: Keep the Transaction model for separate logging if desired
# If VendCommand status is sufficient, you could potentially remove this later.
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False) # Always 1 in current flow
    amount_paid = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # You might want to add a foreign key to VendCommand here if you keep this model
    # vend_command_id = db.Column(db.Integer, db.ForeignKey('vend_command.id'), nullable=True)

    # Ensure relationship points to the correct Product model defined above
    product = db.relationship('Product', backref=db.backref('transactions', lazy=True))

    def __repr__(self):
        return f'<Transaction {self.id} for Product {self.product_id}>'


# --- User Routes (from flask_server.py for ESP32 flow) ---

@app.route('/')
def index():
    # This is now the main user view, replacing /vending_machine
    vend_id = request.args.get('vend_id')
    if not vend_id:
        # Maybe render a page asking for the vend_id or show a generic error
        # For now, just showing an error message.
        return "Error: Please provide a 'vend_id' query parameter in the URL (e.g., /?vend_id=VM001)", 400

    # Fetch only products with stock > 0 for the main view
    products = Product.query.filter(Product.stock > 0).order_by(Product.name).all()
    # Make sure you have an 'index.html' template file
    return render_template('index.html', vend_id=vend_id, products=products)

@app.route('/buy/<int:product_id>', methods=['POST'])
def buy_item(product_id):
    vend_id = request.form.get('vend_id')

    if not vend_id:
        flash("Vending machine ID is missing.", "error")
        # Redirect to index, but it needs vend_id. How to handle this better?
        # Maybe store vend_id in session or handle error differently.
        return redirect(url_for('index')) # This might fail if index needs vend_id

    product = Product.query.get(product_id) # Using the merged Product model

    if not product:
        flash("Invalid product selected.", "error")
        return redirect(url_for('index', vend_id=vend_id))

    if product.stock <= 0:
        flash(f"'{product.name}' is out of stock.", "warning")
        return redirect(url_for('index', vend_id=vend_id))

    # Check if there's already a pending command for this machine
    existing_command = VendCommand.query.filter_by(
        vend_id=vend_id,
        status='pending'
    ).first()

    if existing_command:
        flash("Another purchase is already in progress for this machine. Please wait.", "warning")
        return redirect(url_for('index', vend_id=vend_id))

    try:
        # --- Optimistic Update ---
        # 1. Create the command using VendCommand model
        new_command = VendCommand(
            vend_id=vend_id,
            product_id=product.id,
            motor_id=product.motor_id, # Use motor_id from Product
            status='pending'
        )
        db.session.add(new_command)

        # 2. Decrement stock (optimistic)
        product.stock -= 1
        # No need to db.session.add(product) again if modifying an existing object

        # 3. Commit transaction
        db.session.commit()

        flash(f"Purchase initiated for '{product.name}'. Please wait for the item.", "success")
        print(f"[BUY] Initiated command {new_command.id} for {vend_id}, motor {product.motor_id}. Stock reduced to {product.stock}.")

    except Exception as e:
        db.session.rollback() # Rollback changes if anything failed
        flash("An error occurred while initiating the purchase. Please try again.", "error")
        print(f"[ERROR] Failed to initiate purchase for product {product_id} on {vend_id}: {e}")

    return redirect(url_for('index', vend_id=vend_id))

# --- Vending Machine Client Routes (from flask_server.py) ---

@app.route('/get_command', methods=['GET'])
def get_command():
    """
    Called by the vending machine client (ESP32) to check for pending commands.
    """
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return jsonify({"error": "vend_id is required"}), 400

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
        return jsonify({"motor_id": None, "command_id": None})

@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    """
    Called by the vending machine client (ESP32) after attempting to execute a command.
    """
    data = request.json
    vend_id = data.get("vend_id")
    command_id = data.get("command_id")
    ack_status = data.get("status") # e.g., "success" or "failure"

    if not all([vend_id, command_id, ack_status]):ESP32)"""
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return jsonify({"error": "vend_id is required"}), 400

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
        return jsonify({"motor_id": None, "command_id": None})

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

    # Use session scope for potential rollback
    try:
        command = db.session.get(VendCommand, command_id) # Use db.session.get for primary key lookup

        if not command:
            print(f"[ACK_ERROR] Command ID {command_id} not found.")
            return jsonify({"error": "Command not found"}), 404

        if command.vend_id != vend_id:
            print(f"[ACK_ERROR] Mismatched vend_id for command {command_id}. Expected {command.vend_id}, got {vend_id}.")
            return jsonify({"error": "Vending machine ID mismatch"}), 400

        if command.status != 'pending':
            print(f"[ACK_WARN] Command {command_id} already processed (status: {command.status}). Ignoring.")
            return jsonify({"message": "Command already processed"}), 200

        log_prefix = f"[ACK_{ack_status.upper()}]"

        if ack_status == "success":
            command.status = "acknowledged_success"
            command.acknowledged_at = datetime.utcnow()
            # Log the successful transaction here if desired
            try:
                 transaction = Transaction(product_id=command.product_id, quantity=1, amount_paid=command.product.price)
                 db.session.add(transaction)
                 print(f"{log_prefix} Command {command_id} success for {vend_id}. Transaction logged.")
            except Exception as log_e:
                 print(f"{log_prefix} Command {command_id} success for {vend_id}. FAILED TO LOG TRANSACTION: {log_e}")
                 # Decide if failure to log transaction should rollback the command status update? Probably not.

        elif ack_status == "failure":
            command.status = "acknowledged_failure"
            command.acknowledged_at = datetime.utcnow()
            # --- Rollback Stock ---
            product = db.session.get(Product, command.product_id) # Get product within session
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

# --- Admin Routes (Adapted from flask_server.py, adding description) ---

@app.route('/admin')
def admin_dashboard():
    # Using dashboard from flask_server.py which includes command counts
    product_count = Product.query.count()
    pending_commands = VendCommand.query.filter_by(status='pending').count()
    failed_commands = VendCommand.query.filter_by(status='acknowledged_failure').count()
    # Assumes you have 'admin/dashboard.html' template
    return render_template('admin/dashboard.html',
                           product_count=product_count,
                           pending_commands=pending_commands,
                           failed_commands=failed_commands)

@app.route('/admin/products')
def list_products():
    products = Product.query.order_by(Product.name).all()
     # Assumes you have 'admin/products.html' template
    return render_template('admin/products.html', products=products)

# Renamed from add_product for clarity, added description handling
@app.route('/admin/product/new', methods=['GET', 'POST'])
def new_product():
    if request.method == 'POST':
        try:
            # Get all fields from form
            name = request.form['name']
            price = float(request.form['price'])
            stock = int(request.form['stock'])
            motor_id = int(request.form['motor_id'])
            description = request.form.get('description') # Added
            image_url = request.form.get('image_url')

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
            print(f"[ADMIN_DELETE_ERROR] {e}") # <<< Ensure this line is complete!
        return jsonify({"error": "Missing vend_id, command_id, or status"}), 400

    command = VendCommand.query.get(command_id)

    if not command:
        print(f"[ACK_ERROR] Command ID {command_id} not found.")
        return jsonify({"error": "Command not found"}), 404

    if command.vend_id != vend_id:
        print(f"[ACK_ERROR] Mismatched vend_id for command {command_id}. Expected {command.vend_id}, got {vend_id}.")
        return jsonify({"error": "Vending machine ID mismatch"}), 400

    if command.status != 'pending':
        print(f"[ACK_WARN] Command {command_id} already acknowledged or expired (status: {command.status}). Ignoring.")
        return jsonify({"message": "Command already processed"}), 200

    product = None # Define product variable outside the if/else
    try:
        if ack_status == "success":
            command.status = "acknowledged_success"
            command.acknowledged_at = datetime.utcnow()
            print(f"[ACK_SUCCESS] Command {command.id} for {vend_id} (Motor {command.motor_id}) acknowledged successfully.")

            # Optional: Create a Transaction log entry on success
            product = Product.query.get(command.product_id)
            if product:
                 new_transaction = Transaction(product_id=product.id, quantity=1, amount_paid=product.price)
                 db.session.add(new_transaction)
                 print(f"[TRANSACTION] Logged successful transaction {new_transaction.id} for command {command.id}")

        elif ack_status == "failure":
            command.status = "acknowledged_failure"
            command.acknowledged_at = datetime.utcnow()
            # --- Rollback Stock (Crucial on Failure) ---
            product = Product.query.get(command.product_id)
            if product:
                product.stock += 1 # Add the stock back
                print(f"[ACK_FAILURE] Command {command.id} failed. Rolled back stock for product {product.id} to {product.stock}.")
            else:
                print(f"[ACK_FAILURE_ERROR] Command {command.id} failed, but could not find product {command.product_id} to roll back stock!")
        else:
            print(f"[ACK_ERROR] Invalid status '{ack_status}' received for command {command_id}.")
            return jsonify({"error": "Invalid status provided"}), 400

        db.session.commit() # Commit status change and potential stock rollback/transaction log

    except Exception as e:
        db.session.rollback()
        print(f"[ACK_DB_ERROR] Failed to commit acknowledgment for command {command_id}: {e}")
        return jsonify({"error": "Database error during acknowledgment"}), 500

    return jsonify({"message": "Acknowledgment received"}), 200

# --- Admin Routes (adapted from flask_server.py to use merged Product model) ---

@app.route('/admin')
def admin_dashboard():
    # Simple dashboard page
    try:
        product_count = Product.query.count()
        pending_commands = VendCommand.query.filter_by(status='pending').count()
        failed_commands = VendCommand.query.filter_by(status='acknowledged_failure').count()
    except Exception as e:
        flash(f"Error fetching dashboard data: {e}", "error")
        product_count, pending_commands, failed_commands = 0, 0, 0

    # Make sure you have an 'admin/dashboard.html' template
    return render_template('admin/dashboard.html',
                           product_count=product_count,
                           pending_commands=pending_commands,
                           failed_commands=failed_commands)


@app.route('/admin/products')
def list_products():
    try:
        products = Product.query.order_by(Product.name).all()
    except Exception as e:
         flash(f"Error fetching products: {e}", "error")
         products = []
    # Make sure you have an 'admin/products.html' template
    return render_template('admin/products.html', products=products)

@app.route('/admin/product/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        try:
            name = request.form['name']
            price = float(request.form['price'])
            stock = int(request.form['stock'])
            # Get motor_id and image_url from form
            motor_id = int(request.form['motor_id'])
            image_url = request.form.get('image_url') # Optional

            if not name or price <= 0 or stock < 0 or motor_id <= 0:
                flash("Invalid product data. Check all fields.", 'error')
                return render_template('admin/product_form.html', action="Add", product=request.form)

            existing = Product.query.filter_by(motor_id=motor_id).first()
            if existing:
                 flash(f"Motor ID {motor_id} is already assigned to product '{existing.name}'.", 'error')
                 return render_template('admin/product_form.html', action="Add", product=request.form)

            new_product = Product(name=name, price=price, stock=stock, motor_id=motor_id, image_url=image_url)
            db.session.add(new_product)
            db.session.commit()
            flash(f'Product "{name}" added successfully!', 'success')
            return redirect(url_for('list_products'))
        except ValueError:
             flash("Invalid number format for price, stock, or motor ID.", 'error')
             return render_template('admin/product_form.html', action="Add", product=request.form)
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {e}", 'error')
            print(f"[ADMIN_ADD_ERROR] {e}")
            return render_template('admin/product_form.html', action="Add", product=request.form)

    # GET request - Make sure you have 'admin/product_form.html' template
    return render_template('admin/product_form.html', action="Add", product=None)

@app.route('/admin/product/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    if request.method == 'POST':
        try:
            original_motor_id = product.motor_id
            new_motor_id = int(request.form['motor_id'])

            product.name = request.form['name']
            product.price = float(request.form['price'])
            product.stock = int(request.form['stock'])
            product.motor_id = new_motor_id
            product.image_url = request.form.get('image_url') # Optional

            if not product.name or product.price <= 0 or product.stock < 0 or product.motor_id <= 0:
                flash("Invalid product data. Check all fields.", 'error')
                return render_template('admin/product_form.html', action="Edit", product=product)

            if new_motor_id != original_motor_id:
                existing = Product.query.filter(Product.motor_id == new_motor_id, Product.id != product_id).first()
                if existing:
                    flash(f"Motor ID {new_motor_id} is already assigned to product '{existing.name}'.", 'error')
                    # Pass back edited values
                    product.motor_id = original_motor_id # Revert motor_id on error display? Or keep attempted? Let's keep attempted for now.
                    return render_template('admin/product_form.html', action="Edit", product=product)

            db.session.commit()
            flash(f'Product "{product.name}" updated successfully!', 'success')
            return redirect(url_for('list_products'))
        except ValueError:
             flash("Invalid number format for price, stock, or motor ID.", 'error')
             # Pass product back to pre-fill form again,ADMIN_ADD_ERROR] {e}")
            return render_template('admin/product_form.html', action="Add New", product=request.form)

    # GET request
    # Assumes you have 'admin/product_form.html' template
    return render_template('admin/product_form.html', action="Add New", product=None)

# Renamed product_id to id for consistency with original app.py route if preferred, added description
@app.route('/admin/product/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    product = Product.query.get_or_404(id)

    if request.method == 'POST':
        try:
            original_motor_id = product.motor_id
            new_motor_id = int(request.form['motor_id'])

            # Update all fields
            product.name = request.form['name']
            product.price = float(request.form['price'])
            product.stock = int(request.form['stock'])
            product.motor_id = new_motor_id
            product.description = request.form.get('description') # Added
            product.image_url = request.form.get('image_url')

            # Validation
            if not product.name or product.price <= 0 or product.stock < 0 or product.motor_id <= 0:
                flash("Invalid data: Name required, price/motor_id positive, stock non-negative.", 'warning')
                return render_template('admin/product_form.html', action="Edit", product=product) # Keep edits in form

            # Check motor_id uniqueness if changed
            if new_motor_id != original_motor_id:
                existing = Product.query.filter(Product.motor_id == new_motor_id, Product.id != id).first()
                if existing:
                    flash(f"Motor ID {new_motor_id} is already assigned to product '{existing.name}'.", 'error')
                    return render_template('admin/product_form.html', action="Edit", product=product) # Keep edits

            db.session.commit()
            flash(f'Product "{product.name}" updated successfully!', 'success')
            return redirect(url_for('list_products'))

        except ValueError:
             flash("Invalid number format for price, stock, or motor ID.", 'danger')
             # Pass product back to pre-fill form again, preserving attempted edits from request.form
             # This part is tricky, manually re-assigning from form might be needed if validation fails early
             product.name = request.form.get('name', product.name)
             product.price = request.form.get('price', product.price)
             product.stock = request.form.get('stock', product.stock)
             product.motor_id = request.form.get('motor_id', product.motor_id)
             product.description = request.form.get('description', product.description)
             product.image_url = request.form.get('image_url', product.image_url)
             return render_template('admin/product_form.html', action="Edit", product=product)
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", 'danger')
            print(f"[ADMIN_EDIT_ERROR] {e}")
            return render_template('admin/product_form.html', action="Edit", product=product) # Show original data on error

    # GET request
    return render_template('admin/product_form.html', action="Edit", product=product)

# Renamed product_id to id
@app.route('/admin/product/delete/<int:id>', methods=['POST'])
def delete_product(id):
    product = Product.query.get_or_404(id)
    try:
        # Consider implications: Should deleting a product delete related commands/transactions?
        # Foreign key constraints might prevent deletion if related records exist.
        # You might need to handle this (e.g., delete related records first, or prevent deletion).
        # For now, we rely on the database potentially raising an error.

        product_name = product.name
        db.session.delete(product)
        db.session.commit()
        flash(f'Product "{product_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        # Check for specific IntegrityError related to foreign keys
        from sqlalchemy.exc import IntegrityError
        if isinstance(e, IntegrityError):
             flash(f"Cannot delete '{product.name}'. It might be referenced by existing commands or transactions.", 'danger')
        else:
             flash(f'Error deleting product: {str(e)}', 'danger')
        print(f"[ADMIN_DELETE_ERROR] {e}")

    return redirect(url_for('list_products'))

# --- Main Execution Block (Keep from app.py - no db.create_all()) ---
if __name__ == '__main__':
    # For local development using 'python app.py'
    # Render uses the Start Command (e.g., gunicorn app:app)
    print("Starting Flask development server...")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True) # Debug=True for development ONLY