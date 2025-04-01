from flask import Flask, request, jsonify, render_template
import time

app = Flask(__name__)

# Store the latest command for ESP32
latest_command = {"motor_id": None, "action": None}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/buy_item', methods=['POST'])
def buy_item():
    global latest_command
    item_id = request.form['item_id']

    # Set the command for ESP32 to process
    latest_command = {"motor_id": int(item_id), "action": "start"}
    return f"✅ Item {item_id} purchased successfully!"

@app.route('/get_command', methods=['GET'])
def get_command():
    global latest_command
    if latest_command["motor_id"] is not None:
        command_to_send = latest_command
        latest_command = {"motor_id": None, "action": None}  # Clear after sending
        return jsonify(command_to_send)
    return jsonify({"motor_id": None, "action": None})

@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    data = request.json
    motor_id = data.get("motor_id")
    status = data.get("status")
    print(f"✅ Motor {motor_id} status: {status}")
    return "Acknowledged", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
