import os, json, threading
from flask import Flask, request, jsonify
from flask_cors import CORS

# Flask 앱 생성 및 설정
app = Flask(__name__)
CORS(app)  # 다른 장치(Pi)에서도 접근 가능하도록 허용

DATA_DIR = os.environ.get("DATA_DIR", "server_data")
os.makedirs(DATA_DIR, exist_ok=True)
LOCK = threading.Lock()

# --------------------------------------------------
# 🔒 인증 키 (Pi 기기별 고유키)
# 각 Pi는 요청 헤더에 자신의 키를 실어 보냄
# --------------------------------------------------
VALID_KEYS = {
    "pi-01": "A7K9-22FQ-ZYX1",
    "pi-02": "L9D3-55TN-WBA4"
}

def verify_key():
    """Authorization 헤더에서 유효한 키가 있는지 확인"""
    auth_header = request.headers.get("Authorization", "")
    for key in VALID_KEYS.values():
        if key in auth_header:
            return True
    return False

@app.before_request
def check_auth():
    """모든 API 요청 전에 키를 검증"""
    if request.path.startswith("/api/"):  # /api/ 로 시작하는 요청만 보호
        if not verify_key():
            return jsonify({"error": "unauthorized"}), 401

# --------------------------------------------------
# JSON 파일 입출력 함수
# --------------------------------------------------
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

# --------------------------------------------------
# API 엔드포인트 정의
# --------------------------------------------------

@app.get("/api/health")
def health():
    """서버 상태 확인용 엔드포인트"""
    return jsonify(ok=True)

@app.route("/api/beacons", methods=["GET", "POST"])
def beacons():
    """비콘 좌표 및 맵 크기 정보 저장/로드"""
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

@app.route("/api/pathnodes", methods=["GET", "POST"])
def pathnodes():
    """길찾기용 노드 정보 저장/로드"""
    if request.method == "GET":
        return jsonify(_read_json("setup_path_config.json", []))
    data = request.get_json(force=True)
    _write_json("setup_path_config.json", data)
    return jsonify(status="ok")

@app.route("/api/stock", methods=["GET", "POST"])
def stock():
    """상품 재고 저장/로드"""
    if request.method == "GET":
        return jsonify(_read_json("stock.json", []))
    data = request.get_json(force=True)
    _write_json("stock.json", data)
    return jsonify(status="ok")

@app.route("/api/members", methods=["GET", "POST"])
def members():
    """회원 정보 저장/로드"""
    if request.method == "GET":
        return jsonify(_read_json("members.json", []))
    data = request.get_json(force=True)
    _write_json("members.json", data)
    return jsonify(status="ok")

@app.route("/api/session", methods=["GET", "PUT"])
def session():
    """장바구니, 로그인 상태 등 Pi별 세션 관리"""
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

@app.post("/api/checkout")
def checkout():
    """결제 처리: 재고 차감 및 포인트 적립"""
    body = request.get_json(force=True)
    device_id = body.get("device_id")
    cart = body.get("cart", [])
    member_id = body.get("member_id")

    # 재고 로드
    stock = _read_json("stock.json", [])
    sku_to_item = {it["sku"]: it for it in stock}

    # 재고 수량 확인
    for it in cart:
        sku = it["sku"]
        qty = int(it["qty"])
        if sku not in sku_to_item:
            return jsonify(error=f"unknown sku {sku}"), 400
        if sku_to_item[sku]["qty"] < qty:
            return jsonify(error=f"insufficient stock for {sku}"), 400

    # 재고 차감
    for it in cart:
        sku_to_item[it["sku"]]["qty"] -= int(it["qty"])
    _write_json("stock.json", list(sku_to_item.values()))

    # 회원일 경우 포인트 적립
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

    # 세션 상태 변경 (결제 완료)
    sessions = _read_json("sessions.json", {})
    if device_id in sessions:
        s = sessions[device_id]
        s["last_step"] = "paid"
        s["cart"] = []
        _write_json("sessions.json", sessions)

    return jsonify(status="ok")

# --------------------------------------------------
# 메인 실행부
# --------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
