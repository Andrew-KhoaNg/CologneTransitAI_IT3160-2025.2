from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
from engine import TransitEngine
from storage import TransitStorage
import json
import os

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# Path to the data file
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cologne_network.json")
FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "transit_state.sqlite3")
GENERATED_UNKNOWN_LINES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "generated_unknown_lines.json")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# Initialize engine
def load_generated_unknown_lines():
    if not os.path.exists(GENERATED_UNKNOWN_LINES_PATH):
        return []

    with open(GENERATED_UNKNOWN_LINES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


storage = TransitStorage(DB_PATH)
engine = TransitEngine(
    DATA_PATH,
    disabled_lines=storage.get_disabled_lines(),
    encoded_unknown_lines=load_generated_unknown_lines(),
)


def require_admin(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Admin login required"}), 401
        return handler(*args, **kwargs)

    return wrapper

# --- Serve Frontend Static Files ---
@app.route('/')
def index():
    return send_from_directory(FRONTEND_PATH, 'index.html')

@app.route('/admin')
def admin_index():
    return send_from_directory(FRONTEND_PATH, 'index.html')

@app.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory(os.path.join(FRONTEND_PATH, 'js'), filename)

# --- API Routes ---
@app.route('/api/network', methods=['GET'])
def get_network():
    return jsonify(engine.get_network_data())

@app.route('/api/lines', methods=['GET'])
def get_lines():
    return jsonify({
        "all_lines": engine.get_all_lines(),
        "disabled_lines": list(engine.disabled_lines)
    })

@app.route('/api/admin/status', methods=['GET'])
def admin_status():
    return jsonify({"authenticated": bool(session.get("is_admin"))})

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"error": "Invalid admin password"}), 401

    session["is_admin"] = True
    return jsonify({"success": True})

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"success": True})

@app.route('/api/admin/toggle-line', methods=['POST'])
@require_admin
def toggle_line():
    data = request.json or {}
    line_name = data.get('line')
    disabled = data.get('disabled', True)
    
    if not line_name:
        return jsonify({"error": "Line name is required"}), 400
        
    disabled_list = engine.toggle_line(line_name, disabled)
    storage.set_line_disabled(line_name, disabled)
    return jsonify({"success": True, "disabled_lines": disabled_list})

@app.route('/api/find-path', methods=['POST'])
def find_path():
    data = request.json or {}
    start_id = data.get('start_node')
    end_id = data.get('end_node')
    
    if not start_id or not end_id:
        return jsonify({"error": "Start and End nodes are required"}), 400
        
    result = engine.find_path(int(start_id), int(end_id))
    storage.save_route_query(int(start_id), int(end_id), result)
    return jsonify(result)

if __name__ == '__main__':
    # Check if data exists, if not, print warning
    if not os.path.exists(DATA_PATH):
        print(f"CRITICAL: Data file not found at {DATA_PATH}. Please run scripts/fetch_data.py first.")
    
    app.run(debug=True, port=5000)
