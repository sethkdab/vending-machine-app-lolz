from flask import Flask, request, jsonify, render_template
import threading

app = Flask(__name__)

# Store commands for each vending machine
latest_commands = {}

@app.route('/')
def index():
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return "❌ Missing vend_id in URL", 400
    return render_template('index.html', vend_id=vend_id)

@app.route('/buy_item', methods=['POST'])
def buy_item():
    vend_id = request.form.get('vend_id')
    item_id = request.form.get('item_id')

    if not vend_id or not item_id:
        return "❌ Missing vend_id or item_id", 400

    # Store the command for this vend_id
    latest_commands[vend_id] = {
        "motor_id": int(item_id),
        "action": "start"
    }
    return f"✅ Order sent to vending machine {vend_id} for motor {item_id}"

@app.route('/get_command', methods=['GET'])
def get_command():
    vend_id = request.args.get('vend_id')
    if not vend_id:
        return jsonify({"motor_id": None, "action": None})

    command = latest_commands.get(vend_id)
    if command:
        # Send command once, then clear it
        latest_commands[vend_id] = {"motor_id": None, "action": None}
        return jsonify(command)
    else:
        return jsonify({"motor_id": None, "action": None})

@app.route('/acknowledge', methods=['POST'])
def acknowledge():
    data = request.json
    vend_id = data.get("vend_id")
    motor_id = data.get("motor_id")
    status = data.get("status")

    print(f"✅ {vend_id} acknowledged motor {motor_id} with status: {status}")
    return "Acknowledged", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
