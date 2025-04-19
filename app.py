import os
import json
from dotenv import load_dotenv
from flask import (
    Flask, request, render_template,
    redirect, url_for, flash, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
from functools import wraps
from urllib.parse import quote_plus # Keep import, might be needed later
from datetime import datetime, timedelta, timezone # Added timedelta and timezone

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
    secret_key = 'your_actual_secret_key_here_flask' # CHANGE THIS in .env for Flask sessions/flash

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = secret_key # Used for Flask flash messages etc.

# --- Load Vending Specific Config ---
MACRODROID_API_KEY = os.environ.get('MACRODROID_API_KEY')
if not MACRODROID_API_KEY:
    print("CRITICAL WARNING: MACRODROID_API_KEY environment variable not set. Payment endpoint is insecure and will fail!")

# Optional: Load account mapping - NOT used by this test /buy route, but maybe needed elsewhere
ABA_ACCOUNT_MAPPING_JSON = os.environ.get('ABA_ACCOUNT_MAPPING', '{}')
try:
    ACCOUNT_NUMBER_TO_MACHINE_ID = json.loads(ABA_ACCOUNT_MAPPING_JSON)
    if not isinstance(ACCOUNT_NUMBER_TO_MACHINE_ID, dict):
        raise ValueError("ABA_ACCOUNT_MAPPING is not a valid JSON object.")
    print(f"Loaded ABA Account Mapping (for reference): {ACCOUNT_NUMBER_TO_MACHINE_ID}")
except (json.JSONDecodeError, ValueError) as e:
    print(f"WARNING: Could not parse ABA_ACCOUNT_MAPPING JSON: {e}. Using empty map.")
    ACCOUNT_NUMBER_TO_MACHINE_ID = {}


# --- Initialize DB and Migrate ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models (NO payment_url column needed for this test version) ---
class Product(db.Model):
    __tablename__ = 'product'
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.String(80), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    description = db.Column(db.Text, nullable=True)
    motor_id = db.Column(db.Integer, nullable=False)
    image_url = db.Column(db.String(255), nullable=True)
    # payment_url = db.Column(db.String(512), nullable=True) # <- Field NOT ADDED for this test

    __table_args__ = (db.UniqueConstraint('machine_id', 'motor_id', name='uq_machine_motor_product'),)
    commands = db.relationship('VendCommand', backref='product_commanded', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='product_transacted', lazy='dynamic')
    def __repr__(self): return f'<Product {self.id}: {self.name} (Machine: {self.machine_id}, Motor: {self.motor_id})>'

class VendCommand(db.Model):
    __tablename__ = 'vend_command'
    id = db.Column(db.Integer, primary_key=True)
    vend_id = db.Column(db.String(80), nullable=False, index=True) # Machine ID (e.g., "v3")
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    motor_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(40), nullable=False, default='awaiting_payment', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    def __repr__(self): return f'<Command {self.id} for Vend {self.vend_id} - Prod {self.product_id} / Motor {self.motor_id} ({self.status})>'

class Transaction(db.Model):
    __tablename__ = 'transaction'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    amount_paid = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    def __repr__(self): return f'<Transaction {self.id} for Prod {self.product_id} @ {self.timestamp}>'

# --- Decorator for API Key Authentication ---
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not MACRODROID_API_KEY:
            print("CRITICAL SECURITY ALERT: API Key decorator invoked but MACRODROID_API_KEY is NOT SET on the server!")
            return jsonify({"error": "Server configuration error: Missing API Key setup"}), 503 # Service Unavailable
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != MACRODROID_API_KEY:
            print(f"[AUTH-FAIL] '/{f.__name__}' endpoint: Invalid or missing API Key. Provided: '{api_key}'")
            return jsonify({"error": "Unauthorized: Invalid API Key"}), 401 # Unauthorized
        print(f"[AUTH-OK] '/{f.__name__}' endpoint: API Key verified.")
        return f(*args, **kwargs)
    return decorated_function

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
# (Keep your existing list_machines, list_products, add_product, edit_product, delete_product routes)
# Ensure they DO NOT try to access product.payment_url since it doesn't exist in the DB model here
@app.route('/admin/machines')
def list_machines_from_products():
    try:
        machine_ids_tuples = db.session.query(Product.machine_id).distinct().order_by(Product.machine_id).all()
        machine_ids = [m[0] for m in machine_ids_tuples]
    except Exception as e:
        flash(f"Error fetching machine IDs: {e}", "error")
        machine_ids = []
    return render_template('admin/machines_simple.html', machine_ids=machine_ids)

@app.route('/admin/products')
def list_products():
    try:
        products = Product.query.order_by(Product.machine_id, Product.name).all()
    except Exception as e:
        flash(f"Error fetching products: {e}", "error")
        products = []
    # Pass products to a template that DOES NOT expect 'payment_url'
    return render_template('admin/products.html', products=products) # Assumes this template doesn't show payment_url

@app.route('/admin/product/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        try:
            machine_id_str = request.form.get('machine_id')
            name = request.form.get('name')
            price_str = request.form.get('price')
            stock_str = request.form.get('stock')
            motor_id_str = request.form.get('motor_id')
            description = request.form.get('description')
            image_url = request.form.get('image_url')
            # NO payment_url field expected from form in this test version

            # --- Validation ---
            if not all([machine_id_str, name, price_str, stock_str, motor_id_str]):
                flash("Machine ID, Motor ID, Name, Price, and Stock are required.", 'warning')
                return render_template('admin/product_form.html', action="Add New", product=request.form) # Pass form back
            price = float(price_str); stock = int(stock_str); motor_id = int(motor_id_str)
            if price <= 0 or stock < 0 or motor_id <= 0:
                 flash("Price/Motor ID must be positive, Stock non-negative.", 'warning')
                 return render_template('admin/product_form.html', action="Add New", product=request.form)
            existing = Product.query.filter_by(machine_id=machine_id_str, motor_id=motor_id).first()
            if existing:
                flash(f"Motor ID {motor_id} is already used in Machine '{machine_id_str}'.", 'error')
                return render_template('admin/product_form.html', action="Add New", product=request.form)

            # --- Create and Save (without payment_url) ---
            new_product = Product(
                machine_id=machine_id_str, name=name, price=price, stock=stock,
                motor_id=motor_id, description=description, image_url=image_url
                # No payment_url here
            )
            db.session.add(new_product); db.session.commit()
            flash(f"Product '{name}' added!", 'success'); return redirect(url_for('list_products'))
        except ValueError: flash("Invalid number format.", 'danger'); return render_template('admin/product_form.html', action="Add New", product=request.form)
        except Exception as e: db.session.rollback(); flash(f"Error adding product: {e}", 'danger'); print(f"[ADD PRODUCT ERROR] {e}"); return render_template('admin/product_form.html', action="Add New", product=request.form)
    else: return render_template('admin/product_form.html', action="Add New", product=None) # Ensure this template doesn't have payment_url field

@app.route('/admin/product/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        try:
            original_machine_id = product.machine_id; original_motor_id = product.motor_id
            new_machine_id = request.form.get('machine_id'); name = request.form.get('name')
            price_str = request.form.get('price'); stock_str = request.form.get('stock')
            new_motor_id_str = request.form.get('motor_id'); description = request.form.get('description')
            image_url = request.form.get('image_url')
            # NO payment_url field expected

            # --- Validation ---
            if not all([new_machine_id, name, price_str, stock_str, new_motor_id_str]):
                flash("Machine ID, Motor ID, Name, Price, Stock are required.", 'warning'); return render_template('admin/product_form.html', action="Edit", product=product) # Show original product
            price = float(price_str); stock = int(stock_str); new_motor_id = int(new_motor_id_str)
            if price <= 0 or stock < 0 or new_motor_id <= 0:
                 flash("Price/Motor ID positive, Stock non-negative.", 'warning'); return render_template('admin/product_form.html', action="Edit", product=product)
            if new_machine_id != original_machine_id or new_motor_id != original_motor_id:
                existing = Product.query.filter(Product.machine_id == new_machine_id, Product.motor_id == new_motor_id, Product.id != product_id).first()
                if existing: flash(f"Motor ID {new_motor_id} already used in Machine '{new_machine_id}'.", 'error'); return render_template('admin/product_form.html', action="Edit", product=product)

            # --- Update Product Fields (without payment_url) ---
            product.machine_id = new_machine_id; product.name = name; product.price = price; product.stock = stock
            product.motor_id = new_motor_id; product.description = description; product.image_url = image_url
            # No payment_url update here

            db.session.commit(); flash(f"Product '{product.name}' updated!", 'success'); return redirect(url_for('list_products'))
        except ValueError: flash("Invalid number format.", 'danger'); return render_template('admin/product_form.html', action="Edit", product=product)
        except Exception as e: db.session.rollback(); flash(f"Error updating product: {e}", 'danger'); print(f"[EDIT PRODUCT ERROR] {e}"); return render_template('admin/product_form.html', action="Edit", product=product)
    else: return render_template('admin/product_form.html', action="Edit", product=product) # Ensure template doesn't show payment_url

@app.route('/admin/product/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    # (Keep existing delete logic - check for commands/transactions before deleting)
    product = Product.query.get_or_404(product_id)
    product_desc = f"'{product.name}' (Machine: {product.machine_id}, Motor: {product.motor_id})"
    try:
        cmd_exists = VendCommand.query.filter_by(product_id=product_id).first()
        tran_exists = Transaction.query.filter_by(product_id=product_id).first()
        if cmd_exists or tran_exists:
             flash(f"Cannot delete {product_desc} - has associated commands/transactions.", 'warning')
             return redirect(url_for('list_products'))
        db.session.delete(product); db.session.commit()
        flash(f"Product {product_desc} deleted!", 'success')
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

    # Fetch potential commands
    pending_command = VendCommand.query.filter_by(
        vend_id=machine_identifier,
        status='pending' # Waiting for ESP pickup
    ).order_by(VendCommand.created_at.desc()).first()

    awaiting_payment_command = VendCommand.query.filter_by(
        vend_id=machine_identifier,
        status='awaiting_payment' # Waiting for user payment
    ).order_by(VendCommand.created_at.desc()).first()

    # --- Add current time and threshold for display logic ---
    now_utc = datetime.now(timezone.utc) # Use timezone-aware UTC time
    # How long to show the "awaiting payment" message before hiding it (e.g., 10 minutes)
    awaiting_display_threshold = timedelta(minutes=0.25)

    return render_template('vending_interface.html',
                           machine_id=machine_identifier,
                           products=available_products,
                           pending_command=pending_command,
                           awaiting_payment_command=awaiting_payment_command,
                           # --- Pass time variables to template ---
                           current_time_utc=now_utc,
                           awaiting_threshold=awaiting_display_threshold
                           )
# --- Buy Route (REFINED TEMPORARY VERSION - HARDCODED HTTPS LINKS TEST) ---
@app.route('/buy/<int:product_id>', methods=['POST'])
def buy_product(product_id):
    """
    TEMPORARY TEST VERSION (REFINED):
    - Ensures VendCommand is created with 'awaiting_payment' BEFORE redirect.
    - If product_id matches a key in TEST_PRODUCT_LINKS, redirects to the hardcoded HTTPS link.
    - Otherwise, creates command & redirects back to vending page (manual payment needed).
    *** REMEMBER TO REVERT OR CHANGE THIS AFTER TESTING ***
    """

    # ===================================================================
    # === VV --- USER: CONFIGURE THESE FOR YOUR TEST --- VV ===
    # ===================================================================

    # Dictionary mapping Product IDs to their specific ABA Pay HTTPS links
    # NOTE: You provided the SAME link for both 1 and 2. This code uses that.
    TEST_PRODUCT_LINKS = {
        1: "https://pay.ababank.com/ehikwoiZBp38PWgo8",  # Link for Product ID 1
        2: "https://pay.ababank.com/ehikwoiZBp38PWgo8"   # Link for Product ID 2
        # Add more entries here if testing other products:
        # 3: "https://pay.ababank.com/ANOTHER_LINK_HERE"
    }

    # ===================================================================
    # === ^^ --- USER: CONFIGURE THESE FOR YOUR TEST --- ^^ ===
    # ===================================================================

    print(f"[BUY-TEST-START] Request for product_id: {product_id}")
    product = Product.query.get_or_404(product_id)
    machine_id = product.machine_id
    redirect_url_default = url_for('vending_interface', machine_identifier=machine_id)

    # --- Check if this product is one we have a hardcoded link for ---
    hardcoded_link_for_product = TEST_PRODUCT_LINKS.get(product_id) # Returns link or None

    if hardcoded_link_for_product:
        print(f"[BUY-TEST-INFO] Product ID {product_id} found in TEST_PRODUCT_LINKS.")
        # Optional: Basic check if the link looks like a valid HTTPS URL
        if not hardcoded_link_for_product.startswith("https://"):
             print(f"[BUY-TEST-ERROR] Hardcoded link for Product ID {product_id} doesn't start with https!: '{hardcoded_link_for_product}'")
             flash(f"Configuration Error: Test payment link for '{product.name}' is invalid. Contact admin.", "danger")
             return redirect(redirect_url_default)
    else:
         print(f"[BUY-TEST-INFO] Product ID {product_id} not found in TEST_PRODUCT_LINKS. Manual payment flow expected.")


    # --- Check Stock ---
    if product.stock <= 0:
        print(f"[BUY-TEST-WARN] Product {product_id} is out of stock.")
        flash(f"Sorry, '{product.name}' just went out of stock!", "warning")
        return redirect(redirect_url_default)

    # --- Database Operations: MUST complete before redirect decision ---
    new_command_id = None
    try:
               # Inside the try block of the /buy route:
        print(f"[BUY-DB] Preparing DB update for machine {machine_id} (Product {product_id})...")
        # 1. Cancel previous awaiting commands for THIS machine
        existing_awaiting_commands = VendCommand.query.filter_by(
            vend_id=machine_id,
            status='awaiting_payment'
        ).with_for_update().all() # Optional lock

        cancelled_count = 0
        for cmd in existing_awaiting_commands:
            # Use a clear status name like 'superseded' or stick with 'cancelled_by_new_request'
            cancelled_status = 'superseded_by_new_request' # Or 'cancelled_by_new_request'
            print(f"[BUY-DB] Superseding previous awaiting command ID {cmd.id} with status '{cancelled_status}'")
            cmd.status = cancelled_status
            cancelled_count += 1

        # 2. Create the new command record (comes after cancelling old ones)
        new_command = VendCommand(
            vend_id=machine_id, product_id=product.id, motor_id=product.motor_id,
            status='awaiting_payment' # Set status for the new command
        )
        db.session.add(new_command)
        print(f"[BUY-DB] Added new VendCommand object (pending commit).")

        # 3. Commit the transaction (Cancellation AND New Command together)
        print("[BUY-DB] Attempting db.session.commit()...")
        db.session.commit()
        new_command_id = new_command.id # Get ID after commit
        print(f"[BUY-DB] COMMIT SUCCESSFUL! New Command ID: {new_command_id}. Superseded {cancelled_count} previous commands.")

    except Exception as e:
        db.session.rollback()
        print(f"[BUY-TEST-ERROR] DATABASE EXCEPTION during command creation/cancellation: {e}")
        flash(f"An error occurred saving purchase details. Please try again.", "danger")
        return redirect(redirect_url_default) # Don't proceed if DB failed

    # --- Redirect Logic (Only if DB operations were successful) ---
    if hardcoded_link_for_product:
        # DB part succeeded, AND we have a hardcoded link for this product. Redirect.
        print(f"[BUY-TEST-REDIRECT] Product ID {product_id} is configured for redirect.")
        print(f"[BUY-TEST-REDIRECT] Attempting redirect to URL: '{hardcoded_link_for_product}'")
        try:
            return redirect(hardcoded_link_for_product)
        except Exception as e:
            print(f"[BUY-TEST-ERROR] EXCEPTION during redirect call: {e}")
            flash(f"Error trying to redirect to payment page. Please try again or pay manually.", "warning")
            return redirect(redirect_url_default)
    else:
        # DB part succeeded, but it's NOT a product with a hardcoded link. Redirect back.
        print(f"[BUY-TEST-INFO] Product ID {product_id} has no hardcoded link. Redirecting back to vending interface.")
        # The VendCommand (ID: new_command_id) IS created with 'awaiting_payment'
        flash(f"Purchase initiated for '{product.name}' (Ref: {new_command_id}). Please complete payment manually.", "info")
        return redirect(redirect_url_default)


# --- Payment Received Endpoint (Called by MacroDroid) ---
@app.route('/payment-received', methods=['POST'])
@require_api_key
def payment_received():
    # (Keep existing payment_received logic - verifies key, gets machine_id from payload, updates status)
    if not request.is_json: print("[PAYMENT-RECEIVED] Error: Request is not JSON"); return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json(); print(f"[PAYMENT-RECEIVED] Received data payload: {data}")
    received_machine_id = data.get("machine_id")
    if not received_machine_id: print("[PAYMENT-RECEIVED] Error: 'machine_id' missing."); return jsonify({"error": "Missing 'machine_id'"}), 400
    print(f"[PAYMENT-RECEIVED] Processing payment signal for machine_id: '{received_machine_id}'")
    try:
        command_to_update = VendCommand.query.filter_by(vend_id=received_machine_id, status='awaiting_payment').order_by(VendCommand.created_at.desc()).first()
        if command_to_update:
            print(f"[PAYMENT-RECEIVED] Found command ID {command_to_update.id}. Updating status to 'pending'.")
            command_to_update.status = 'pending'; db.session.commit()
            print(f"[PAYMENT-RECEIVED] SUCCESS: Updated Command ID {command_to_update.id} to 'pending' for machine '{received_machine_id}'.")
            return jsonify({"message": f"Payment acknowledged. Command {command_to_update.id} for machine {received_machine_id} is now pending."}), 200
        else:
            print(f"[PAYMENT-RECEIVED] WARNING: No 'awaiting_payment' command found for machine_id '{received_machine_id}'. Signal ignored.")
            return jsonify({"error": f"No command currently awaiting payment found for machine '{received_machine_id}'."}), 404 # Not Found
    except Exception as e: db.session.rollback(); print(f"[PAYMENT-RECEIVED] DATABASE ERROR for machine '{received_machine_id}': {e}"); return jsonify({"error": "Internal server error"}), 500


# --- ESP32 Interaction Routes (Unchanged) ---
@app.route('/get_command', methods=['GET'])
def get_command():
    # (Keep existing get_command logic - finds oldest 'pending' command for vend_id)
    req_vend_id = request.args.get('vend_id')
    if not req_vend_id: print("[GET_COMMAND] Error: vend_id missing"); return jsonify({"error": "vend_id is required"}), 400
    print(f"[GET_COMMAND] Request from vend_id: {req_vend_id}")
    try:
        command = VendCommand.query.filter_by(vend_id=req_vend_id, status='pending').order_by(VendCommand.created_at.asc()).first()
        if command: print(f"[GET_COMMAND] Found pending cmd ID: {command.id} Motor: {command.motor_id}"); return jsonify({"motor_id": command.motor_id, "command_id": command.id})
        else: print(f"[GET_COMMAND] No pending commands for vend_id: {req_vend_id}"); return jsonify({"motor_id": None, "command_id": None})
    except Exception as e: print(f"[GET_COMMAND] DB error for vend_id {req_vend_id}: {e}"); return jsonify({"error": "Database error"}), 500

@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    # (Keep existing acknowledge logic - updates command status, decrements stock, logs transaction)
    if not request.is_json: print("[ACK] Error: Not JSON"); return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json(); print(f"[ACK] Received data: {data}")
    req_command_id = data.get("command_id"); req_vend_id = data.get("vend_id"); req_motor_id = data.get("motor_id"); req_status = data.get("status")
    if not all([req_command_id, req_vend_id, req_motor_id is not None, req_status]): print(f"[ACK] Error: Missing fields."); return jsonify({"error": "Missing fields"}), 400
    if req_status not in ["success", "failure"]: print(f"[ACK] Error: Invalid status '{req_status}'."); return jsonify({"error": "Invalid status"}), 400
    try:
        command = db.session.get(VendCommand, req_command_id)
        if not command: print(f"[ACK] Error: Command ID {req_command_id} not found."); return jsonify({"error": "Command not found"}), 404
        if command.vend_id != req_vend_id: print(f"[ACK] Error: Mismatched vend_id."); return jsonify({"error": "Vending machine ID mismatch"}), 400
        if command.status != 'pending': print(f"[ACK] Info: Command {req_command_id} not pending (Status: {command.status}). Ignoring."); return jsonify({"message": f"Command already processed (status: {command.status})"}), 200

        product = db.session.get(Product, command.product_id); ack_time = datetime.utcnow(); command.acknowledged_at = ack_time
        if req_status == "success":
            print(f"[ACK] Processing SUCCESS for Command {req_command_id}")
            command.status = "acknowledged_success"
            if product:
                if product.stock > 0: product.stock -= 1; print(f"   - Decremented stock for Prod {product.id} to {product.stock}"); transaction = Transaction(product_id=product.id, quantity=1, amount_paid=product.price, timestamp=ack_time); db.session.add(transaction); print(f"   - Logged transaction.")
                else: print(f"   - WARNING: Success ACK but Prod {product.id} stock was 0!"); command.status = "acknowledged_success_stock_error"
            else: print(f"   - ERROR: Product {command.product_id} not found!"); command.status = "acknowledged_success_product_missing"
        elif req_status == "failure": print(f"[ACK] Processing FAILURE for Cmd {req_command_id}"); command.status = "acknowledged_failure"; print(f"   - Marked as failed.")
        db.session.commit(); print(f"[ACK] Successfully processed ACK for Cmd {req_command_id}"); return jsonify({"message": "Acknowledgment received"}), 200
    except Exception as e: db.session.rollback(); print(f"[ACK] DATABASE ERROR processing Cmd {req_command_id}: {e}"); return jsonify({"error": "Database error during acknowledgment"}), 500


# --- Run Block ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    print(f"Starting Flask server on http://0.0.0.0:{port} with debug={debug_mode}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)