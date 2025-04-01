from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Store the latest motor command
latest_command = {"motor_id": None, "action": None}

# Home page with UI buttons
@app.route('/')
def index():
    return render_template('index.html')

# Buyer clicks button → queue command
@app.route('/buy_item', methods=['POST'])
def buy_item():
    global latest_command
    item_id = request.form['item_id']
    latest_command = {
        "motor_id": int(item_id),
        "action": "start"
    }
    return f"✅ Item {item_id} command sent to ESP32."

# ESP32 polls this to get the command
@app.route('/get_command', methods=['GET'])
def get_command():
    global latest_command

    if latest_command["motor_id"] is not None:
        # Send the command once, then clear it
        command_to_send = latest_command.copy()
        latest_command = {"motor_id": None, "action": None}
        return jsonify(command_to_send)

    # No command available
    return jsonify({"motor_id": None, "action": None})

# ESP32 sends acknowledgment after motor finishes
@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    data = request.json
    motor_id = data.get("motor_id")
    status = data.get("status")
    print(f"✅ ESP32 acknowledged motor {motor_id}: {status}")
    return "Acknowledged", 200

# Run the Flask app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
