import os, json, threading
from flask import Flask, request, jsonify
from flask_cors import CORS

DATA_DIR = os.environ.get("DATA_DIR", "server_data")
os.makedirs(DATA_DIR, exist_ok=True)
LOCK = threading.Lock()

app = Flask(__name__)
CORS(app)

def _path(name):
    return os.path.join(DATA_DIR, name)

def _read_json(name, default):
    p = _path(name)
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(name, obj):
    tmp = _path(name + ".tmp")
    with LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _path(name))

@app.get("/api/health")
def health():
    return jsonify(ok=True)

# 1) Beacon map config
# GET: read current config; POST: replace config
@app.route("/api/beacons", methods=["GET", "POST"])
def beacons():
    if request.method == "GET":
        return jsonify(_read_json("config_beacon_map.json", {
            "beacons": {},
            "real_width_m": 45.0,
            "real_height_m": 29.8,
            "pixel_width": 675,
            "pixel_height": 437
        }))
    data = request.get_json(force=True)
    _write_json("config_beacon_map.json", data)
    return jsonify(status="ok")

# 2) Path nodes (setup_path_config.json)
@app.route("/api/pathnodes", methods=["GET", "POST"])
def pathnodes():
    if request.method == "GET":
        return jsonify(_read_json("setup_path_config.json", []))
    data = request.get_json(force=True)
    _write_json("setup_path_config.json", data)
    return jsonify(status="ok")

# 3) Stock
@app.route("/api/stock", methods=["GET", "POST"])
def stock():
    if request.method == "GET":
        return jsonify(_read_json("stock.json", []))
    data = request.get_json(force=True)
    _write_json("stock.json", data)
    return jsonify(status="ok")

# 4) Members and points
@app.route("/api/members", methods=["GET", "POST"])
def members():
    if request.method == "GET":
        return jsonify(_read_json("members.json", []))
    data = request.get_json(force=True)
    _write_json("members.json", data)
    return jsonify(status="ok")

# 5) Session and carts per device_id
# GET /api/session?device_id=pi-01
# PUT body: { "cart":[...], "mode":"guest|member", "member_id": "...", "last_step":"browse|checkout_pending|paid" }
@app.route("/api/session", methods=["GET", "PUT"])
def session():
    q = request.args.get("device_id", "").strip()
    if not q:
        return jsonify(error="device_id required"), 400
    sessions = _read_json("sessions.json", {})
    if request.method == "GET":
        return jsonify(sessions.get(q, {"cart": [], "mode": "guest", "member_id": None, "last_step": "browse"}))
    body = request.get_json(force=True)
    sessions[q] = body
    _write_json("sessions.json", sessions)
    return jsonify(status="ok")

# 6) Checkout endpoint
# body: { "device_id":"...", "cart":[{sku, qty}], "member_id": "... or null" }
# Behavior: decrement stock, add points, mark session last_step = "paid"
@app.post("/api/checkout")
def checkout():
    body = request.get_json(force=True)
    device_id = body.get("device_id")
    cart = body.get("cart", [])
    member_id = body.get("member_id")

    stock = _read_json("stock.json", [])
    sku_to_item = {it["sku"]: it for it in stock}

    for it in cart:
        sku = it["sku"]
        qty = int(it["qty"])
        if sku not in sku_to_item:
            return jsonify(error=f"unknown sku {sku}"), 400
        if sku_to_item[sku]["qty"] < qty:
            return jsonify(error=f"insufficient stock for {sku}"), 400

    for it in cart:
        sku_to_item[it["sku"]]["qty"] -= int(it["qty"])
    _write_json("stock.json", list(sku_to_item.values()))

    if member_id:
        members = _read_json("members.json", [])
        m = next((x for x in members if x.get("id") == member_id), None)
        if m:
            total = 0.0
            for it in cart:
                price = float(sku_to_item[it["sku"]]["price"])
                total += price * int(it["qty"])
            points_add = round(total * 0.05, 2)
            m["points"] = float(m.get("points", 0)) + points_add
            _write_json("members.json", members)

    sessions = _read_json("sessions.json", {})
    if device_id in sessions:
        s = sessions[device_id]
        s["last_step"] = "paid"
        s["cart"] = []
        _write_json("sessions.json", sessions)

    return jsonify(status="ok")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
