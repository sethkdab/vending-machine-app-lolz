import os
import json
from dotenv import load_dotenv
from flask import (
    Flask, request, render_template,
    redirect, url_for, flash, jsonify # Added jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
from functools import wraps # For API key decorator

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
    # In a real production scenario, you might want to raise an error or prevent startup
    print("CRITICAL WARNING: MACRODROID_API_KEY environment variable not set. Payment endpoint is insecure and will fail!")
    # For development/testing, you might allow it, but log heavily.
    # MACRODROID_API_KEY = None # Or set a dummy value for testing if absolutely needed

# Optional: Load account mapping even if not used in this endpoint, maybe useful elsewhere
ABA_ACCOUNT_MAPPING_JSON = os.environ.get('ABA_ACCOUNT_MAPPING', '{}')
try:
    ACCOUNT_NUMBER_TO_MACHINE_ID = json.loads(ABA_ACCOUNT_MAPPING_JSON)
    if not isinstance(ACCOUNT_NUMBER_TO_MACHINE_ID, dict):
        raise ValueError("ABA_ACCOUNT_MAPPING is not a valid JSON object.")
    print(f"Loaded ABA Account Mapping (for reference): {ACCOUNT_NUMBER_TO_MACHINE_ID}")
except (json.JSONDecodeError, ValueError) as e:
    print(f"ERROR: Could not parse ABA_ACCOUNT_MAPPING JSON: {e}")
    ACCOUNT_NUMBER_TO_MACHINE_ID = {}


# --- Initialize DB and Migrate ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models ---
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
    # Statuses: awaiting_payment, pending, acknowledged_success, acknowledged_failure, cancelled_by_new_request, etc.
    status = db.Column(db.String(40), nullable=False, default='awaiting_payment', index=True) # Default for new commands via /buy
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
        # Check if the key is configured on the server AT ALL
        if not MACRODROID_API_KEY:
            print("CRITICAL SECURITY ALERT: API Key decorator invoked but MACRODROID_API_KEY is NOT SET on the server!")
            return jsonify({"error": "Server configuration error: Missing API Key setup"}), 503 # Service Unavailable

        # Get the key from the request header
        api_key = request.headers.get('X-API-Key')

        # Compare the provided key with the server's configured key
        if not api_key or api_key != MACRODROID_API_KEY:
            print(f"[AUTH-FAIL] '/{f.__name__}' endpoint: Invalid or missing API Key. Provided: '{api_key}'")
            return jsonify({"error": "Unauthorized: Invalid API Key"}), 401 # Unauthorized

        # If keys match, proceed with the actual route function
        print(f"[AUTH-OK] '/{f.__name__}' endpoint: API Key verified.")
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

# Simple Home Route
@app.route('/')
def home():
    # ... (keep your home route) ...
    return """
    <h1>Minimal Vending App</h1>
    <p><a href="/admin/machines">View Machine IDs</a></p>
    <p><a href="/admin/products">Manage Product Slots</a></p>
    <hr>
    <p><strong>Customer View Example:</strong> Try <a href="/vending/v3">/vending/v3</a> (replace v3 with an ID you added)</p>
    """

# --- Admin Routes ---
# ... (keep list_machines_from_products, list_products, add_product, edit_product, delete_product) ...
@app.route('/admin/machines')
def list_machines_from_products():
    try:
        machine_ids_tuples = db.session.query(Product.machine_id).distinct().order_by(Product.machine_id).all()
        machine_ids = [m[0] for m in machine_ids_tuples] # Extract strings
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
    return render_template('admin/products.html', products=products)

@app.route('/admin/product/add', methods=['GET', 'POST'])
def add_product():
    # ... (Your existing add_product logic) ...
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

@app.route('/admin/product/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    # ... (Your existing edit_product logic) ...
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

@app.route('/admin/product/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    # ... (Your existing delete_product logic) ...
    product = Product.query.get_or_404(product_id)
    product_desc = f"'{product.name}' (Machine: {product.machine_id}, Motor: {product.motor_id})"
    try:
        # Prevent deletion if related records exist
        cmd_exists = VendCommand.query.filter_by(product_id=product_id).first()
        tran_exists = Transaction.query.filter_by(product_id=product_id).first()
        if cmd_exists or tran_exists:
             flash(f"Cannot delete {product_desc} - it has associated commands or transactions. Please clear them first or contact support.", 'warning')
             return redirect(url_for('list_products'))

        db.session.delete(product)
        db.session.commit()
        flash(f"Product {product_desc} deleted successfully!", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting product {product_desc}: {e}", 'danger')
        print(f"[DELETE PRODUCT ERROR] {e}")
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

    # Check for pending purchases for THIS machine to maybe show a status
    pending_command = VendCommand.query.filter_by(
        vend_id=machine_identifier,
        status='pending' # Waiting for ESP pickup
    ).order_by(VendCommand.created_at.desc()).first()

    awaiting_payment_command = VendCommand.query.filter_by(
        vend_id=machine_identifier,
        status='awaiting_payment' # Waiting for user payment
    ).order_by(VendCommand.created_at.desc()).first()


    return render_template('vending_interface.html',
                           machine_id=machine_identifier,
                           products=available_products,
                           pending_command=pending_command,
                           awaiting_payment_command=awaiting_payment_command)


# --- Buy Route (Initiates 'awaiting_payment') ---
@app.route('/buy/<int:product_id>', methods=['POST'])
def buy_product(product_id):
    product = Product.query.get_or_404(product_id)
    machine_id = product.machine_id
    redirect_url = url_for('vending_interface', machine_identifier=machine_id)

    # Find the ABA account number for THIS machine (Needed for user instructions)
    target_account_number = None
    # Efficiently find the account number associated with the product's machine_id
    for acc_num, mach_id in ACCOUNT_NUMBER_TO_MACHINE_ID.items():
        if mach_id == machine_id:
            target_account_number = acc_num
            break

    if not target_account_number:
        flash(f"Configuration error: No ABA account set for machine '{machine_id}'. Cannot process payment.", "danger")
        print(f"[BUY ERROR] No account number configured for machine_id: {machine_id}")
        return redirect(redirect_url)

    try:
        # Check stock again right before creating command
        product = Product.query.get(product_id) # Re-fetch to be safe
        if not product or product.stock <= 0:
            flash(f"Sorry, '{product.name if product else 'Item'}' is out of stock!", "warning")
            return redirect(redirect_url)

        # --- Cancel Previous Awaiting Payment Commands for THIS Machine ---
        # Use with_for_update() if your DB supports it for better locking, but often okay without
        existing_awaiting_commands = VendCommand.query.filter_by(
            vend_id=machine_id,
            status='awaiting_payment'
        ).all()

        for cmd in existing_awaiting_commands:
            print(f"[BUY] Cancelling previous awaiting command ID {cmd.id} for machine {machine_id}")
            cmd.status = 'cancelled_by_new_request'
            # db.session.add(cmd) # Mark as dirty, commit will handle it

        # --- Create New Vend Command (Awaiting Payment) ---
        new_command = VendCommand(
            vend_id=machine_id,
            product_id=product.id,
            motor_id=product.motor_id,
            status='awaiting_payment' # Start in this state
        )
        db.session.add(new_command)
        db.session.commit() # Commit cancellation and new command creation

        # --- Inform User for ABA Payment ---
        # Simple formatting for display
        formatted_account = "..."+target_account_number[-4:] # Show last 4 digits only
        flash_message = (
            f"Request for '{product.name}' initiated! "
            f"To complete purchase, please transfer exactly <b>{product.price:.2f} USD</b> "
            f"to ABA account ending in <b>{formatted_account}</b> "
            f"using your ABA Mobile app. The machine will dispense after payment is confirmed."
        )
        flash(flash_message, "info") # Use 'info' category
        print(f"[BUY] Created VendCommand {new_command.id} for Product {product_id} on Machine {machine_id}. Status: awaiting_payment. Target ABA Account: {target_account_number}")

        # No automatic redirection to ABA needed/possible here based on requirements

    except Exception as e:
        db.session.rollback()
        print(f"[BUY ERROR] Exception processing purchase for product {product_id}: {e}")
        flash(f"An error occurred processing your request. Please try again.", "danger")

    return redirect(redirect_url)


# --- Payment Received Endpoint (Called by MacroDroid) ---
@app.route('/payment-received', methods=['POST'])
@require_api_key # Apply the security decorator
def payment_received():
    """
    Receives notification FROM MACRODROID when a specific payment
    (e.g., 0.01 USD to account linked to 'v3') is detected.
    Finds the corresponding 'awaiting_payment' command and updates its status
    to 'pending' so the ESP32 can pick it up.
    Relies on MacroDroid sending {'machine_id': 'the_correct_id'}.
    """
    # 1. Check if the request is JSON
    if not request.is_json:
        print("[PAYMENT-RECEIVED] Error: Request received is not JSON.")
        return jsonify({"error": "Request must be JSON"}), 400 # Bad Request

    # 2. Parse the JSON data
    data = request.get_json()
    print(f"[PAYMENT-RECEIVED] Received data payload: {data}")

    # 3. Extract the machine_id (sent directly by MacroDroid)
    received_machine_id = data.get("machine_id")

    # 4. Validate that machine_id was provided
    if not received_machine_id:
        print("[PAYMENT-RECEIVED] Error: 'machine_id' field missing in JSON payload.")
        return jsonify({"error": "Missing 'machine_id' field in request body"}), 400 # Bad Request

    print(f"[PAYMENT-RECEIVED] Processing payment signal for machine_id: '{received_machine_id}'")

    # --- Find the Command and Update Status ---
    try:
        # Find the *most recent* command for THIS specific machine that is currently waiting for payment.
        command_to_update = VendCommand.query.filter_by(
            vend_id=received_machine_id,
            status='awaiting_payment'
        ).order_by(VendCommand.created_at.desc()).first()

        # 5. Check if a suitable command was found
        if command_to_update:
            # Found the command! Update its status to 'pending'
            print(f"[PAYMENT-RECEIVED] Found matching command ID {command_to_update.id} (Status: {command_to_update.status}). Updating status to 'pending'.")
            command_to_update.status = 'pending'
            # You could optionally add a timestamp here like:
            # command_to_update.payment_confirmed_at = datetime.utcnow()

            # Commit the status change to the database
            db.session.commit()

            print(f"[PAYMENT-RECEIVED] SUCCESS: Updated Command ID {command_to_update.id} status to 'pending' for machine '{received_machine_id}'.")

            # Return a success response to MacroDroid
            return jsonify({"message": f"Payment acknowledged. Command {command_to_update.id} for machine {received_machine_id} is now pending."}), 200 # OK

        else:
            # No command was found for this machine in 'awaiting_payment' status.
            # This is normal if payment notification is late/duplicate, or if user paid without 'buying' first.
            print(f"[PAYMENT-RECEIVED] WARNING: No command found in 'awaiting_payment' status for machine_id '{received_machine_id}'. Signal ignored.")

            # Return a 'Not Found' response - the resource (command to update) wasn't there.
            return jsonify({"error": f"No command currently awaiting payment found for machine '{received_machine_id}'."}), 404 # Not Found

    except Exception as e:
        # 6. Handle potential database errors
        db.session.rollback() # Rollback any partial changes on error
        print(f"[PAYMENT-RECEIVED] DATABASE ERROR processing payment signal for machine '{received_machine_id}': {e}")
        # Return a server error response
        return jsonify({"error": "Internal server error during payment processing"}), 500 # Internal Server Error


# --- ESP32 Interaction Routes (Unchanged) ---

@app.route('/get_command', methods=['GET'])
def get_command():
    """Called by the ESP32 to get the next 'pending' command."""
    req_vend_id = request.args.get('vend_id')
    if not req_vend_id:
        print("[GET_COMMAND] Error: vend_id query parameter missing")
        return jsonify({"error": "vend_id is required"}), 400
    print(f"[GET_COMMAND] Request received from vend_id: {req_vend_id}")
    try:
        command = VendCommand.query.filter_by(
            vend_id=req_vend_id,
            status='pending' # Only fetch commands ready for vending
        ).order_by(VendCommand.created_at.asc()).first()
        if command:
            print(f"[GET_COMMAND] Found pending command ID: {command.id} for Motor: {command.motor_id}")
            return jsonify({"motor_id": command.motor_id, "command_id": command.id})
        else:
            print(f"[GET_COMMAND] No pending commands found for vend_id: {req_vend_id}")
            return jsonify({"motor_id": None, "command_id": None})
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
    req_command_id = data.get("command_id"); req_vend_id = data.get("vend_id"); req_motor_id = data.get("motor_id"); req_status = data.get("status")
    if not all([req_command_id, req_vend_id, req_motor_id is not None, req_status]):
         print(f"[ACKNOWLEDGE] Error: Missing fields. Got: {list(data.keys())}")
         return jsonify({"error": "Missing command_id, vend_id, motor_id, or status"}), 400
    if req_status not in ["success", "failure"]:
        print(f"[ACKNOWLEDGE] Error: Invalid status '{req_status}'.")
        return jsonify({"error": "Invalid status value"}), 400
    try:
        command = db.session.get(VendCommand, req_command_id)
        if not command:
            print(f"[ACKNOWLEDGE] Error: Command ID {req_command_id} not found.")
            return jsonify({"error": "Command not found"}), 404
        if command.vend_id != req_vend_id:
            print(f"[ACKNOWLEDGE] Error: Mismatched vend_id for Command {req_command_id}. DB: {command.vend_id}, Req: {req_vend_id}")
            return jsonify({"error": "Vending machine ID mismatch"}), 400
        # Optional: Check motor_id match as a warning or error
        # if command.motor_id != req_motor_id: print(f"[ACK] Warning: Motor mismatch...")

        if command.status != 'pending': # Make sure we are acknowledging a command that was actually pending
            print(f"[ACKNOWLEDGE] Info: Command {req_command_id} not in 'pending' state (Status: {command.status}). Ignoring ACK.")
            return jsonify({"message": f"Command already processed (status: {command.status})"}), 200 # Or maybe 409 Conflict? 200 is okay.

        # --- Process Acknowledgment ---
        product = db.session.get(Product, command.product_id)
        ack_time = datetime.utcnow()
        command.acknowledged_at = ack_time

        if req_status == "success":
            print(f"[ACKNOWLEDGE] Processing SUCCESS for Command {req_command_id}")
            command.status = "acknowledged_success"
            if product:
                if product.stock > 0:
                    product.stock -= 1
                    print(f"   - Decremented stock for Product {product.id} ({product.name}) to {product.stock}")
                    transaction = Transaction(product_id=product.id, quantity=1, amount_paid=product.price, timestamp=ack_time)
                    db.session.add(transaction)
                    print(f"   - Logged transaction ID {transaction.id if transaction.id else '(pending commit)'} for Product {product.id}")
                else:
                    print(f"   - WARNING: Success ACK for Command {req_command_id}, but Product {product.id} stock was already 0!")
                    command.status = "acknowledged_success_stock_error" # Mark differently
            else:
                print(f"   - ERROR: Product {command.product_id} not found for successful Command {req_command_id}!")
                command.status = "acknowledged_success_product_missing"

        elif req_status == "failure":
            print(f"[ACKNOWLEDGE] Processing FAILURE for Command {req_command_id}")
            command.status = "acknowledged_failure"
            # No stock change needed as we only decrement on success ACK now.
            print(f"   - Command {req_command_id} marked as failed.")

        # --- Commit Changes to DB ---
        db.session.commit()
        print(f"[ACKNOWLEDGE] Successfully processed ACK for Command {req_command_id}")
        return jsonify({"message": "Acknowledgment received"}), 200

    except Exception as e:
        db.session.rollback()
        print(f"[ACKNOWLEDGE] DATABASE ERROR processing Command {req_command_id}: {e}")
        return jsonify({"error": "Database error during acknowledgment"}), 500


# --- Run Block ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Use FLASK_DEBUG env var provided by Render/Flask standard practice
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    print(f"Starting Flask server on http://0.0.0.0:{port} with debug={debug_mode}")
    # Set use_reloader=False if debug is True when running migrations or in some prod environments
    # app.run(host='0.0.0.0', port=port, debug=debug_mode, use_reloader=not debug_mode)
    app.run(host='0.0.0.0', port=port, debug=debug_mode)