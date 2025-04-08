# === flask_server.py ===
from flask import Flask, request, jsonify, render_template, redirect, url_for
import threading
import time

app = Flask(__name__)

# Store latest command per vending machine with delivery tracking
latest_commands = {
    # Example: 'v1': {"motor_id": 1, "action": "start", "acknowledged": False, "timestamp": time.time()}
}

# Retry interval in seconds
RETRY_INTERVAL = 10
ACK_TIMEOUT = 60  # Timeout in seconds for waiting for acknowledgment

@app.route('/')
def index():
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return "\u274c Missing vend_id in URL", 400
    return render_template('index.html', vend_id=vend_id)

@app.route('/buy_item', methods=['POST'])
def buy_item():
    vend_id = request.form.get('vend_id')
    item_id = request.form.get('item_id')

    if not vend_id or not item_id:
        return "\u274c Missing vend_id or item_id", 400

    # Store the command
    latest_commands[vend_id] = {
        "motor_id": int(item_id),
        "action": "start",
        "acknowledged": False,
        "timestamp": time.time()
    }
    print(f"[buy_item] Command stored for {vend_id}: motor {item_id}")

    # Wait for acknowledgment
    start_time = time.time()
    while time.time() - start_time < ACK_TIMEOUT:
        command = latest_commands.get(vend_id)
        if command and command.get("acknowledged", False):
            print(f"[buy_item] Acknowledgment received for {vend_id}.")
            return redirect(url_for('index', vend_id=vend_id))
        time.sleep(1)  # Check every second

    # If acknowledgment is not received within the timeout
    print(f"[buy_item] Acknowledgment timeout for {vend_id}.")
    return "\u274c Acknowledgment not received in time.", 408

@app.route('/get_command', methods=['GET'])
def get_command():
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return jsonify({"motor_id": None, "action": None})

    command = latest_commands.get(vend_id)
    if command and not command.get("acknowledged", True):
        return jsonify({
            "motor_id": command["motor_id"],
            "action": command["action"]
        })
    else:
        return jsonify({"motor_id": None, "action": None})

@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    data = request.json
    vend_id = data.get("vend_id")
    motor_id = data.get("motor_id")
    status = data.get("status")

    if vend_id in latest_commands:
        latest_commands[vend_id]["acknowledged"] = True
        print(f"[ACK] {vend_id} confirmed motor {motor_id} ran successfully.")
    else:
        print(f"[ACK] Unknown vend_id: {vend_id}")
    return "OK", 200

@app.route('/waiting')
def waiting():
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return "\u274c Missing vend_id in URL", 400
    return render_template('waiting.html', vend_id=vend_id)

# Background thread to retry unacknowledged commands
def retry_unacknowledged_commands():
    while True:
        time.sleep(RETRY_INTERVAL)
        current_time = time.time()
        for vend_id, command in list(latest_commands.items()):
            if not command.get("acknowledged", True):
                # Check if the command is stale (e.g., older than 60 seconds)
                if current_time - command["timestamp"] > 60:
                    print(f"[Retry] Command for {vend_id} expired and removed.")
                    del latest_commands[vend_id]
                else:
                    print(f"[Retry] Resending command to {vend_id}: motor {command['motor_id']}")

# Start the retry thread
if __name__ == '__main__':
    retry_thread = threading.Thread(target=retry_unacknowledged_commands, daemon=True)
    retry_thread.start()
    app.run(host='0.0.0.0', port=5000)
