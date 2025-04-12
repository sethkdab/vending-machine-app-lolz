# === flask_server.py ===
import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
import threading
import time

app = Flask(__name__)

# Configure the database URI from Render's environment variable
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', '8f09cb2c58d3b2f012fe5cb6d98626e9') # For flash messages

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize Flask-Migrate for database migrations
migrate = Migrate(app, db)

# Retry interval in seconds
RETRY_INTERVAL = 10
ACK_TIMEOUT = 60  # Timeout in seconds for waiting for acknowledgment

# -------------------- Database Models --------------------

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    motor_id = db.Column(db.Integer, unique=True, nullable=False) # Link to vending machine motor

    def __repr__(self):
        return f'<Product {self.name} (Motor {self.motor_id})>'

class VendCommand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vend_id = db.Column(db.String(80), nullable=False)
    motor_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(20), nullable=False)
    acknowledged = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.Float, default=time.time)

    def __repr__(self):
        return f'<Command for {self.vend_id} - Motor {self.motor_id} ({self.action})>'

# Store latest command per vending machine (in memory for now, could be replaced with DB queries)
latest_commands = {}

@app.route('/')
def index():
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return "\u274c Missing vend_id in URL", 400
    products = Product.query.all()
    return render_template('index.html', vend_id=vend_id, products=products)

@app.route('/buy_item', methods=['POST'])
def buy_item():
    vend_id = request.form.get('vend_id')
    item_id = request.form.get('item_id')

    if not vend_id or not item_id:
        return "\u274c Missing vend_id or item_id", 400

    product = Product.query.filter_by(id=item_id).first()
    if not product:
        return "\u274c Invalid item_id", 400

    if product.stock > 0:
        # Store the command in the database
        new_command = VendCommand(vend_id=vend_id, motor_id=product.motor_id, action="start")
        db.session.add(new_command)
        db.session.commit()
        latest_commands[vend_id] = {"id": new_command.id, "motor_id": product.motor_id, "action": "start", "acknowledged": False, "timestamp": time.time()}
        print(f"[buy_item] Command stored for {vend_id}: motor {product.motor_id} (DB ID: {new_command.id})")

        # Wait for acknowledgment (in-memory for now)
        start_time = time.time()
        while time.time() - start_time < ACK_TIMEOUT:
            command_data = latest_commands.get(vend_id)
            if command_data and command_data.get("acknowledged", False):
                print(f"[buy_item] Acknowledgment received for {vend_id}.")
                product.stock -= 1
                db.session.commit()
                flash(f"Successfully purchased {product.name}!", "success")
                return redirect(url_for('index', vend_id=vend_id))
            time.sleep(1)  # Check every second

        # If acknowledgment is not received within the timeout
        print(f"[buy_item] Acknowledgment timeout for {vend_id}.")
        flash("Acknowledgment not received in time.", "error")
        return redirect(url_for('index', vend_id=vend_id), code=408)
    else:
        flash(f"{product.name} is out of stock.", "warning")
        return redirect(url_for('index', vend_id=vend_id))

@app.route('/get_command', methods=['GET'])
def get_command():
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return jsonify({"motor_id": None, "action": None})

    # Fetch the latest unacknowledged command from the database
    command = VendCommand.query.filter_by(vend_id=vend_id, acknowledged=False).order_by(VendCommand.timestamp.desc()).first()

    if command:
        return jsonify({
            "motor_id": command.motor_id,
            "action": command.action,
            "command_id": command.id # Include command ID for acknowledgment
        })
    else:
        return jsonify({"motor_id": None, "action": None, "command_id": None})

@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    data = request.json
    vend_id = data.get("vend_id")
    motor_id = data.get("motor_id")
    status = data.get("status")
    command_id = data.get("command_id")

    command = VendCommand.query.get(command_id)
    if command and command.vend_id == vend_id and command.motor_id == motor_id:
        command.acknowledged = True
        db.session.commit()
        # Update in-memory store as well
        if vend_id in latest_commands and latest_commands[vend_id].get("id") == command_id:
            latest_commands[vend_id]["acknowledged"] = True
        print(f"[ACK] {vend_id} confirmed motor {motor_id} (Command ID: {command_id}) ran successfully.")
    else:
        print(f"[ACK] Unknown vend_id or command: {vend_id}, motor {motor_id}, command_id {command_id}")
    return "OK", 200

# Background thread to retry unacknowledged commands
def retry_unacknowledged_commands():
    while True:
        time.sleep(RETRY_INTERVAL)
        current_time = time.time()
        unacked_commands = VendCommand.query.filter_by(acknowledged=False).all()
        for command in unacked_commands:
            # Check if the command is stale (e.g., older than 60 seconds)
            if current_time - command.timestamp > 60:
                print(f"[Retry] Command for {command.vend_id} (Motor {command.motor_id}, ID {command.id}) expired and will be marked (not deleted).")
                command.acknowledged = True # Mark as acknowledged to stop retrying
                db.session.commit()
                if command.vend_id in latest_commands and latest_commands[command.vend_id].get("id") == command.id:
                    latest_commands[command.vend_id]["acknowledged"] = True
            else:
                print(f"[Retry] Resending command to {command.vend_id}: motor {command.motor_id} (ID: {command.id})")

# Start the retry thread
if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Create database tables if they don't exist
    retry_thread = threading.Thread(target=retry_unacknowledged_commands, daemon=True)
    retry_thread.start()
    app.run(host='0.0.0.0', port=5000)