# --- app.py ---
# (Includes previous setup, models, home route, admin routes)
# Add jsonify to imports if not already there
import os
from dotenv import load_dotenv
from flask import (
    Flask, request, render_template,
    redirect, url_for, flash, jsonify # Added jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime

# --- Load Environment Variables ---
load_dotenv()

# --- Initialize Flask App ---
app = Flask(__name__)

# --- Configure App ---
db_url = os.environ.get('DATABASE_URL')
if not db_url:
    raise ValueError("DATABASE_URL environment variable not set.")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    print("Warning: SECRET_KEY not set. Using insecure default.")
    secret_key = 'your_actual_secret_key_here' # CHANGE THIS in .env

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = secret_key

# --- Initialize DB and Migrate ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models ---
# (Keep the Product, VendCommand, Transaction models exactly as defined
#  in the previous complete app.py code for the simpler solution)
class Product(db.Model):
    __tablename__ = 'product'
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.String(80), nullable=False, index=True) # Machine this slot belongs to
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0) # Stock for THIS slot
    description = db.Column(db.Text, nullable=True)
    motor_id = db.Column(db.Integer, nullable=False) # Slot number within the machine
    image_url = db.Column(db.String(255), nullable=True)
    __table_args__ = (db.UniqueConstraint('machine_id', 'motor_id', name='uq_machine_motor_product'),)
    commands = db.relationship('VendCommand', backref='product_commanded', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='product_transacted', lazy='dynamic')
    def __repr__(self): return f'<Product {self.id}: {self.name} (Machine: {self.machine_id}, Motor: {self.motor_id})>'

class VendCommand(db.Model):
    __tablename__ = 'vend_command'
    id = db.Column(db.Integer, primary_key=True)
    vend_id = db.Column(db.String(80), nullable=False) # Machine ID where command should run
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False) # Which specific product slot
    motor_id = db.Column(db.Integer, nullable=False) # Which motor to activate
    status = db.Column(db.String(30), nullable=False, default='pending') # Status: pending, acknowledged_success, acknowledged_failure, expired
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    def __repr__(self): return f'<Command {self.id} for Vend {self.vend_id} - Prod {self.product_id} / Motor {self.motor_id} ({self.status})>'

class Transaction(db.Model):
    __tablename__ = 'transaction'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False) # Which specific product slot
    quantity = db.Column(db.Integer, nullable=False, default=1)
    amount_paid = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    def __repr__(self): return f'<Transaction {self.id} for Prod {self.product_id} @ {self.timestamp}>'

# --- Routes ---

# Simple Home Route
@app.route('/')
def home():
    return """
    <h1>Minimal Vending App</h1>
    <p><a href="/admin/machines">View Machine IDs</a></p>
    <p><a href="/admin/products">Manage Product Slots</a></p>
    <hr>
    <p><strong>Customer View Example:</strong> Try <a href="/vending/v3">/vending/v3</a> (replace v3 with an ID you added)</p>
    """

# --- Admin Routes ---
# (Keep list_machines_from_products, list_products, add_product, edit_product, delete_product)
# List distinct machine IDs found in the Product table
@app.route('/admin/machines')
def list_machines_from_products():
    try:
        machine_ids_tuples = db.session.query(Product.machine_id).distinct().order_by(Product.machine_id).all()
        machine_ids = [m[0] for m in machine_ids_tuples] # Extract strings
    except Exception as e:
        flash(f"Error fetching machine IDs: {e}", "error")
        machine_ids = []
    return render_template('admin/machines_simple.html', machine_ids=machine_ids)

# List Products (Slots)
@app.route('/admin/products')
def list_products():
    try:
        products = Product.query.order_by(Product.machine_id, Product.name).all()
    except Exception as e:
        flash(f"Error fetching products: {e}", "error")
        products = []
    return render_template('admin/products.html', products=products)

# Add Product Slot (CREATE)
@app.route('/admin/product/add', methods=['GET', 'POST'])
def add_product():
    # ... (Keep full code from previous answer) ...
    if request.method == 'POST':
        try:
            machine_id_str = request.form.get('machine_id')
            name = request.form.get('name')
            price_str = request.form.get('price')
            stock_str = request.form.get('stock')
            motor_id_str = request.form.get('motor_id')
            description = request.form.get('description')
            image_url = request.form.get('image_url')
            if not all([machine_id_str, name, price_str, stock_str, motor_id_str]):
                flash("Machine ID, Name, Price, Stock, and Motor ID are required.", 'warning'); return render_template('admin/product_form.html', action="Add New", product=request.form)
            price = float(price_str); stock = int(stock_str); motor_id = int(motor_id_str)
            if price <= 0 or stock < 0 or motor_id <= 0:
                 flash("Price/Motor ID must be positive, Stock non-negative.", 'warning'); return render_template('admin/product_form.html', action="Add New", product=request.form)
            existing = Product.query.filter_by(machine_id=machine_id_str, motor_id=motor_id).first()
            if existing:
                flash(f"Motor ID {motor_id} is already used in Machine '{machine_id_str}'.", 'error'); return render_template('admin/product_form.html', action="Add New", product=request.form)
            new_product = Product(machine_id=machine_id_str, name=name, price=price, stock=stock, motor_id=motor_id, description=description, image_url=image_url)
            db.session.add(new_product); db.session.commit()
            flash(f"Product '{name}' added to machine '{machine_id_str}' (Motor {motor_id})!", 'success'); return redirect(url_for('list_products'))
        except ValueError: flash("Invalid number format for Price, Stock, or Motor ID.", 'danger'); return render_template('admin/product_form.html', action="Add New", product=request.form)
        except Exception as e: db.session.rollback(); flash(f"Error adding product: {e}", 'danger'); print(f"[ADD PRODUCT ERROR] {e}"); return render_template('admin/product_form.html', action="Add New", product=request.form)
    else: return render_template('admin/product_form.html', action="Add New", product=None)

# Edit Product Slot (UPDATE)
@app.route('/admin/product/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    # ... (Keep full code from previous answer) ...
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        try:
            original_machine_id = product.machine_id; original_motor_id = product.motor_id
            new_machine_id = request.form.get('machine_id'); name = request.form.get('name'); price_str = request.form.get('price'); stock_str = request.form.get('stock'); new_motor_id_str = request.form.get('motor_id'); description = request.form.get('description'); image_url = request.form.get('image_url')
            if not all([new_machine_id, name, price_str, stock_str, new_motor_id_str]):
                flash("Machine ID, Name, Price, Stock, and Motor ID are required.", 'warning'); form_data = request.form.to_dict(); form_data['id'] = product_id; return render_template('admin/product_form.html', action="Edit", product=form_data)
            price = float(price_str); stock = int(stock_str); new_motor_id = int(new_motor_id_str)
            if price <= 0 or stock < 0 or new_motor_id <= 0:
                 flash("Price/Motor ID must be positive, Stock non-negative.", 'warning'); form_data = request.form.to_dict(); form_data['id'] = product_id; return render_template('admin/product_form.html', action="Edit", product=form_data)
            if new_machine_id != original_machine_id or new_motor_id != original_motor_id:
                existing = Product.query.filter(Product.machine_id == new_machine_id, Product.motor_id == new_motor_id, Product.id != product_id).first()
                if existing: flash(f"Motor ID {new_motor_id} is already used in Machine '{new_machine_id}'.", 'error'); form_data = request.form.to_dict(); form_data['id'] = product_id; return render_template('admin/product_form.html', action="Edit", product=form_data)
            product.machine_id = new_machine_id; product.name = name; product.price = price; product.stock = stock; product.motor_id = new_motor_id; product.description = description; product.image_url = image_url
            db.session.commit(); flash(f"Product '{product.name}' updated successfully!", 'success'); return redirect(url_for('list_products'))
        except ValueError: flash("Invalid number format for Price, Stock, or Motor ID.", 'danger'); form_data = request.form.to_dict(); form_data['id'] = product_id; return render_template('admin/product_form.html', action="Edit", product=form_data)
        except Exception as e: db.session.rollback(); flash(f"Error updating product: {e}", 'danger'); print(f"[EDIT PRODUCT ERROR] {e}"); product = Product.query.get_or_404(product_id); return render_template('admin/product_form.html', action="Edit", product=product)
    else: return render_template('admin/product_form.html', action="Edit", product=product)

# Delete Product Slot (DELETE)
@app.route('/admin/product/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    # ... (Keep full code from previous answer) ...
    product = Product.query.get_or_404(product_id)
    product_desc = f"'{product.name}' (Machine: {product.machine_id}, Motor: {product.motor_id})"
    try:
        if product.commands.first() or product.transactions.first():
            flash(f"Cannot delete {product_desc} - it has associated commands or transactions.", 'warning'); return redirect(url_for('list_products'))
        db.session.delete(product); db.session.commit(); flash(f"Product {product_desc} deleted successfully!", 'success')
    except Exception as e: db.session.rollback(); flash(f"Error deleting product {product_desc}: {e}", 'danger'); print(f"[DELETE PRODUCT ERROR] {e}")
    return redirect(url_for('list_products'))

# --- Vending Machine User Interface ---
@app.route('/vending/<string:machine_identifier>')
def vending_interface(machine_identifier):
    try:
        available_products = Product.query.filter(
                Product.machine_id == machine_identifier,
                Product.stock > 0
            ).order_by(Product.motor_id).all()
    except Exception as e:
        print(f"Error fetching products for machine {machine_identifier}: {e}")
        flash("Error loading products for this machine.", "error")
        available_products = []
    return render_template('vending_interface.html',
                           machine_id=machine_identifier,
                           products=available_products)

# --- Buy Route (MODIFIED) ---
@app.route('/buy/<int:product_id>', methods=['POST'])
def buy_product(product_id):
    redirect_url = url_for('home') # Default redirect
    product_info = Product.query.with_entities(Product.machine_id).filter_by(id=product_id).first()
    if product_info:
        redirect_url = url_for('vending_interface', machine_identifier=product_info.machine_id)

    try:
        product = Product.query.get_or_404(product_id)
        if product.stock <= 0:
            flash(f"Sorry, '{product.name}' in slot {product.motor_id} just went out of stock!", "warning")
            return redirect(redirect_url)

        # --- Create Vend Command ONLY ---
        new_command = VendCommand(
            vend_id=product.machine_id,
            product_id=product.id,
            motor_id=product.motor_id,
            status='pending' # Mark as waiting for ESP32
        )
        db.session.add(new_command)
        # --- DO NOT CHANGE STOCK HERE ---
        db.session.commit()
        flash(f"Request to vend '{product.name}' (Slot {product.motor_id}) sent! Please wait.", "success")

    except Exception as e:
        db.session.rollback()
        print(f"Error processing purchase for product {product_id}: {e}")
        flash(f"An error occurred trying to buy item.", "danger")
        # Redirect URL determined at the start of the try block

    return redirect(redirect_url)


# --- ESP32 Interaction Routes ---

@app.route('/get_command', methods=['GET'])
def get_command():
    """Called by the ESP32 to get the next pending command."""
    # Get machine ID from query parameter
    req_vend_id = request.args.get('vend_id')
    if not req_vend_id:
        print("[GET_COMMAND] Error: vend_id query parameter missing")
        return jsonify({"error": "vend_id is required"}), 400

    print(f"[GET_COMMAND] Request received from vend_id: {req_vend_id}")

    try:
        # Find the oldest pending command for this specific vending machine
        command = VendCommand.query.filter_by(
            vend_id=req_vend_id,
            status='pending'
        ).order_by(VendCommand.created_at.asc()).first()

        if command:
            # Found a pending command
            print(f"[GET_COMMAND] Found pending command ID: {command.id} for Motor: {command.motor_id}")
            # Return the command details needed by ESP32
            # ESP32 code expects "motor_id" and "command_id"
            return jsonify({
                "motor_id": command.motor_id,
                "command_id": command.id
                # "action": "start" # ESP32 code doesn't actually check for this 'action' key based on provided code review
            })
        else:
            # No pending commands for this machine
            print(f"[GET_COMMAND] No pending commands found for vend_id: {req_vend_id}")
            return jsonify({"motor_id": None, "command_id": None}) # Indicate no command

    except Exception as e:
        print(f"[GET_COMMAND] Database error for vend_id {req_vend_id}: {e}")
        return jsonify({"error": "Database error processing request"}), 500


@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    """Called by the ESP32 to report the outcome of a vend attempt."""
    if not request.is_json:
        print("[ACKNOWLEDGE] Error: Request is not JSON")
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    print(f"[ACKNOWLEDGE] Received data: {data}")

    # Extract data from JSON payload (match keys used in ESP32 sendAck)
    req_command_id = data.get("command_id")
    req_vend_id = data.get("vend_id")
    req_motor_id = data.get("motor_id") # ESP32 sends motor_id too
    req_status = data.get("status") # Should be "success" or "failure"

    # Basic validation of received data
    if not all([req_command_id, req_vend_id, req_motor_id is not None, req_status]):
         print(f"[ACKNOWLEDGE] Error: Missing fields in JSON payload. Got keys: {list(data.keys())}")
         return jsonify({"error": "Missing command_id, vend_id, motor_id, or status"}), 400

    if req_status not in ["success", "failure"]:
        print(f"[ACKNOWLEDGE] Error: Invalid status '{req_status}' received.")
        return jsonify({"error": "Invalid status value"}), 400

    try:
        # Find the command the ESP32 is referring to
        command = db.session.get(VendCommand, req_command_id) # Use efficient primary key lookup

        if not command:
            print(f"[ACKNOWLEDGE] Error: Command ID {req_command_id} not found.")
            return jsonify({"error": "Command not found"}), 404

        # --- Sanity Checks ---
        if command.vend_id != req_vend_id:
            print(f"[ACKNOWLEDGE] Error: Mismatched vend_id for Command {req_command_id}. DB: {command.vend_id}, Req: {req_vend_id}")
            return jsonify({"error": "Vending machine ID mismatch"}), 400 # Prevent wrong machine ack

        if command.motor_id != req_motor_id:
             print(f"[ACKNOWLEDGE] Warning: Mismatched motor_id for Command {req_command_id}. DB: {command.motor_id}, Req: {req_motor_id}")
             # Decide if this is an error or just a warning
             # return jsonify({"error": "Motor ID mismatch"}), 400

        if command.status != 'pending':
            # Avoid processing acknowledged or expired commands again
            print(f"[ACKNOWLEDGE] Info: Command {req_command_id} already processed (status: {command.status}). Ignoring ACK.")
            return jsonify({"message": f"Command already in status {command.status}"}), 200 # OK response, but do nothing

        # --- Process Acknowledgment ---
        product = db.session.get(Product, command.product_id) # Get related product

        if req_status == "success":
            print(f"[ACKNOWLEDGE] Processing SUCCESS for Command {req_command_id}")
            command.status = "acknowledged_success"
            command.acknowledged_at = datetime.utcnow()

            if product:
                # --- Decrement Stock and Log Transaction ---
                 # Double-check stock before decrementing
                if product.stock > 0:
                    product.stock -= 1
                    print(f"   - Decremented stock for Product {product.id} to {product.stock}")

                    transaction = Transaction(
                        product_id=product.id,
                        quantity=1,
                        amount_paid=product.price # Use price from Product table
                    )
                    db.session.add(transaction)
                    print(f"   - Logged transaction for Product {product.id}")
                else:
                    # This case should be rare if stock checks work, but handle it
                    print(f"   - WARNING: Acknowledged success for Command {req_command_id}, but Product {product.id} stock was already 0!")
                    # Maybe mark command differently? Or just log?
                    command.status = "acknowledged_success_stock_error" # Example of different status

            else:
                print(f"   - ERROR: Product {command.product_id} not found for successful Command {req_command_id}!")
                # Cannot decrement stock or log transaction accurately
                command.status = "acknowledged_success_product_missing" # Example


        elif req_status == "failure":
            print(f"[ACKNOWLEDGE] Processing FAILURE for Command {req_command_id}")
            command.status = "acknowledged_failure"
            command.acknowledged_at = datetime.utcnow()
            # --- No stock change needed if we didn't decrement optimistically in /buy ---
            print(f"   - Command {req_command_id} marked as failed.")
            # If you *did* decrement stock in /buy, you would increment it here:
            # if product:
            #   product.stock += 1
            #   print(f"   - Rolled back stock for Product {product.id} to {product.stock}")


        # --- Commit Changes to DB ---
        db.session.commit()
        print(f"[ACKNOWLEDGE] Successfully processed ACK for Command {req_command_id}")
        return jsonify({"message": "Acknowledgment received"}), 200

    except Exception as e:
        db.session.rollback() # Rollback on any error during processing
        print(f"[ACKNOWLEDGE] DATABASE ERROR processing Command {req_command_id}: {e}")
        return jsonify({"error": "Database error during acknowledgment"}), 500


# --- Run Block ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'true').lower() not in ['false', '0']
    print(f"Starting Flask server on http://0.0.0.0:{port} with debug={debug_mode}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)