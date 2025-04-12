# === flask_server.py ===
import os
from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, flash, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import time # Keep time for command timestamp if needed

app = Flask(__name__)

# Configure the database URI from Render's environment variable
# Make sure the DATABASE_URL starts with postgresql:// not postgres://
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# IMPORTANT: Set a strong secret key in Render environment variables!
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', '8f09cb2c58d3b2f012fe5cb6d98626e9')

# Initialize SQLAlchemy & Flask-Migrate
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models ---

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

# --- User Routes ---

@app.route('/')
def index():
    vend_id = request.args.get('vend_id')
    if not vend_id:
        # Maybe render a page asking for the vend_id or show a generic error
        return "Error: Please provide a 'vend_id' query parameter in the URL (e.g., /?vend_id=VM001)", 400

    # Fetch only products with stock > 0 for the main view
    products = Product.query.filter(Product.stock > 0).order_by(Product.name).all()
    return render_template('index.html', vend_id=vend_id, products=products)

@app.route('/buy/<int:product_id>', methods=['POST'])
def buy_item(product_id):
    vend_id = request.form.get('vend_id')

    if not vend_id:
        flash("Vending machine ID is missing.", "error")
        return redirect(url_for('index')) # Redirect back without vend_id might be problematic

    product = Product.query.get(product_id)

    if not product:
        flash("Invalid product selected.", "error")
        return redirect(url_for('index', vend_id=vend_id))

    if product.stock <= 0:
        flash(f"'{product.name}' is out of stock.", "warning")
        return redirect(url_for('index', vend_id=vend_id))

    # Check if there's already a pending command for this machine
    # This prevents users from spamming the buy button while a vend is in progress
    existing_command = VendCommand.query.filter_by(
        vend_id=vend_id,
        status='pending'
    ).first()

    if existing_command:
        flash("Another purchase is already in progress for this machine. Please wait.", "warning")
        return redirect(url_for('index', vend_id=vend_id))

    try:
        # --- Optimistic Update ---
        # 1. Create the command
        new_command = VendCommand(
            vend_id=vend_id,
            product_id=product.id,
            motor_id=product.motor_id,
            status='pending' # Start as pending
        )
        db.session.add(new_command)

        # 2. Decrement stock (optimistic)
        product.stock -= 1
        db.session.add(product)

        # 3. Commit transaction
        db.session.commit()

        flash(f"Purchase initiated for '{product.name}'. Please wait for the item.", "success")
        print(f"[BUY] Initiated command {new_command.id} for {vend_id}, motor {product.motor_id}. Stock reduced to {product.stock}.")

    except Exception as e:
        db.session.rollback() # Rollback changes if anything failed
        flash("An error occurred while initiating the purchase. Please try again.", "error")
        print(f"[ERROR] Failed to initiate purchase for product {product_id} on {vend_id}: {e}")

    return redirect(url_for('index', vend_id=vend_id))

# --- Vending Machine Client Routes ---

@app.route('/get_command', methods=['GET'])
def get_command():
    """
    Called by the vending machine client to check for pending commands.
    """
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return jsonify({"error": "vend_id is required"}), 400

    # Find the latest pending command for this specific vending machine
    command = VendCommand.query.filter_by(
        vend_id=vend_id,
        status='pending'
    ).order_by(VendCommand.created_at.asc()).first() # Get the oldest pending command

    if command:
        # Optional: Check for command expiry
        # expiry_time = datetime.utcnow() - timedelta(seconds=60) # e.g., 60 seconds expiry
        # if command.created_at < expiry_time:
        #     command.status = 'expired'
        #     db.session.commit()
        #     print(f"[EXPIRED] Command {command.id} for {vend_id} expired.")
        #     # Return no command since this one expired
        #     return jsonify({"motor_id": None, "command_id": None})

        print(f"[GET_COMMAND] Sending command {command.id} (Motor {command.motor_id}) to {vend_id}")
        return jsonify({
            "motor_id": command.motor_id,
            "command_id": command.id
        })
    else:
        # No pending commands for this machine
        return jsonify({"motor_id": None, "command_id": None})

@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    """
    Called by the vending machine client after attempting to execute a command.
    """
    data = request.json
    vend_id = data.get("vend_id")
    command_id = data.get("command_id")
    ack_status = data.get("status") # e.g., "success" or "failure"

    if not all([vend_id, command_id, ack_status]):
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
        return jsonify({"message": "Command already processed"}), 200 # Or 409 Conflict

    # Update command status based on acknowledgment
    if ack_status == "success":
        command.status = "acknowledged_success"
        command.acknowledged_at = datetime.utcnow()
        print(f"[ACK_SUCCESS] Command {command_id} for {vend_id} (Motor {command.motor_id}) acknowledged successfully.")
    elif ack_status == "failure":
        command.status = "acknowledged_failure"
        command.acknowledged_at = datetime.utcnow()
        # --- Rollback Stock (Crucial on Failure) ---
        product = Product.query.get(command.product_id)
        if product:
            product.stock += 1 # Add the stock back
            db.session.add(product)
            print(f"[ACK_FAILURE] Command {command.id} failed. Rolled back stock for product {product.id} to {product.stock}.")
        else:
            print(f"[ACK_FAILURE_ERROR] Command {command.id} failed, but could not find product {command.product_id} to roll back stock!")
        # -------------------------------------------
    else:
        print(f"[ACK_ERROR] Invalid status '{ack_status}' received for command {command_id}.")
        return jsonify({"error": "Invalid status provided"}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[ACK_DB_ERROR] Failed to commit acknowledgment for command {command_id}: {e}")
        # If DB commit fails, the command remains pending, and the client might retry acknowledging.
        return jsonify({"error": "Database error during acknowledgment"}), 500

    return jsonify({"message": "Acknowledgment received"}), 200

# --- Admin Routes ---
# You might want to add authentication/authorization here later
# (e.g., using Flask-Login or Flask-BasicAuth)

@app.route('/admin')
def admin_dashboard():
    # Simple dashboard page
    product_count = Product.query.count()
    pending_commands = VendCommand.query.filter_by(status='pending').count()
    failed_commands = VendCommand.query.filter_by(status='acknowledged_failure').count()
    return render_template('admin/dashboard.html',
                           product_count=product_count,
                           pending_commands=pending_commands,
                           failed_commands=failed_commands)


@app.route('/admin/products')
def list_products():
    products = Product.query.order_by(Product.name).all()
    return render_template('admin/products.html', products=products)

@app.route('/admin/product/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        try:
            name = request.form['name']
            price = float(request.form['price'])
            stock = int(request.form['stock'])
            motor_id = int(request.form['motor_id'])
            image_url = request.form.get('image_url') # Optional

            # Basic validation
            if not name or price <= 0 or stock < 0 or motor_id <= 0:
                flash("Invalid product data. Check all fields.", 'error')
                return render_template('admin/product_form.html', action="Add", product=request.form) # Keep form data

            # Check if motor_id is unique
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

    # GET request
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
                # Pass product back to pre-fill form again
                return render_template('admin/product_form.html', action="Edit", product=product)

            # Check if motor_id is unique (if changed)
            if new_motor_id != original_motor_id:
                existing = Product.query.filter(Product.motor_id == new_motor_id, Product.id != product_id).first()
                if existing:
                    flash(f"Motor ID {new_motor_id} is already assigned to product '{existing.name}'.", 'error')
                    return render_template('admin/product_form.html', action="Edit", product=product) # Keep edits

            db.session.commit()
            flash(f'Product "{product.name}" updated successfully!', 'success')
            return redirect(url_for('list_products'))
        except ValueError:
             flash("Invalid number format for price, stock, or motor ID.", 'error')
             # Pass product back to pre-fill form again, keeping edits
             product.name=request.form['name'] # Keep attempted changes
             product.price=request.form['price']
             product.stock=request.form['stock']
             product.motor_id=request.form['motor_id']
             product.image_url=request.form.get('image_url')
             return render_template('admin/product_form.html', action="Edit", product=product)
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {e}", 'error')
            print(f"[ADMIN_EDIT_ERROR] {e}")
            # Pass product back to pre-fill form again
            return render_template('admin/product_form.html', action="Edit", product=product)

    # GET request
    return render_template('admin/product_form.html', action="Edit", product=product)

@app.route('/admin/product/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    try:
        # Optional: Check if there are pending commands for this product?
        # Or prevent deletion if stock > 0? Depends on requirements.

        product_name = product.name # Get name before deletion
        db.session.delete(product)
        db.session.commit()
        flash(f'Product "{product_name}" deleted successfully!', 'success')
    except Exception as e:
        # Catch potential foreign key constraint errors if VendCommands exist
        db.session.rollback()
        flash(f"Error deleting product '{product.name}'. Maybe it's part of existing commands? Error: {e}", 'error')
        print(f"[ADMIN_DELETE_ERROR] {e}")

    return redirect(url_for('list_products'))


# --- Initialization ---
if __name__ == '__main__':
    # Ensure the database tables are created (Flask-Migrate handles this better)
    # with app.app_context():
    #     db.create_all() # Use migrations instead for production
    # Make sure to run `flask db init`, `flask db migrate`, `flask db upgrade`
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True) # Use PORT env var