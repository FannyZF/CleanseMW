import os
import re
import json
import hashlib
import time
import logging
import threading

import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ── Runtime configuration (in-memory, thread-safe) ─────────────────────
_config_lock = threading.Lock()
_config: dict = {}


def _default_config() -> dict:
    return {
        "its_base_url": os.environ.get("ITS_BASE_URL", "").rstrip("/"),
        "its_apikey": os.environ.get("ITS_APIKEY", ""),
        "its_apisecret": os.environ.get("ITS_APISECRET", ""),
        "its_usertoken": os.environ.get("ITS_USERTOKEN", ""),
        "address_api_url": os.environ.get("ADDRESS_API_URL", "http://101.32.239.62:18933/api/v1"),
        "address_api_key": os.environ.get("ADDRESS_API_KEY", ""),
    }


def _load_config():
    global _config
    cfg = _default_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k in cfg:
                if k in saved and saved[k]:
                    cfg[k] = saved[k]
        except Exception as exc:
            logger.warning("Failed to load config.json: %s", exc)
    with _config_lock:
        _config = cfg


def _save_config(new_cfg: dict):
    global _config
    with _config_lock:
        for k in _config:
            if k in new_cfg and new_cfg[k] is not None:
                _config[k] = str(new_cfg[k]).strip()
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(_config, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to save config.json: %s", exc)


def _get_config():
    with _config_lock:
        return dict(_config)


_load_config()


# ── ITS API helpers ────────────────────────────────────────────────────
def _its_sign(body_str: str):
    cfg = _get_config()
    timestamp = str(int(time.time()))
    raw = f"{cfg['its_apikey']}{cfg['its_apisecret']}{cfg['its_usertoken']}{timestamp}{body_str}"
    signature = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return timestamp, signature


def _its_headers(body_str: str):
    cfg = _get_config()
    timestamp, signature = _its_sign(body_str)
    return {
        "apikey": cfg["its_apikey"],
        "signature": signature,
        "timestamp": timestamp,
        "usertoken": cfg["its_usertoken"],
        "Content-Type": "application/json;charset=UTF-8",
    }


# ── Step 1: Fetch order info from ITS ──────────────────────────────────
def fetch_order_info(customer_order_no: str):
    body = {"customerOrderNo": customer_order_no}
    body_str = json.dumps(body, ensure_ascii=False)
    headers = _its_headers(body_str)
    base_url = _get_config()["its_base_url"]

    logger.info("Fetching order info for %s", customer_order_no)
    resp = requests.post(
        f"{base_url}/its-api/cs/api/getOrderInfo",
        headers=headers,
        data=body_str.encode("utf-8"),
        timeout=30,
    )
    result = resp.json()

    if result.get("code") != 0:
        return None, result.get("msg", "Unknown error")

    consignee = result["data"]["consignee"]
    province = consignee.get("consigneeProvince") or ""
    city = consignee.get("consigneeCity") or ""
    district = consignee.get("consigneeDistrict") or ""
    address = consignee.get("consigneeAddress") or ""
    postcode = consignee.get("consigneePostcode") or ""

    raw_address = f"{province}{city}{district}{address}".strip()

    return {
        "customerOrderNo": customer_order_no,
        "province": province,
        "city": city,
        "district": district,
        "address": address,
        "postcode": postcode,
        "raw_address": raw_address,
        "provided_zipcode": postcode,
    }, None


# ── Step 3: Batch cleanse addresses via API Hub ────────────────────────
def cleanse_addresses_batch(items: list):
    cfg = _get_config()
    batch = [
        {
            "order_id": item["customerOrderNo"],
            "raw_address": item["raw_address"],
            "provided_zipcode": item["provided_zipcode"],
        }
        for item in items
    ]

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": cfg["address_api_key"],
    }

    logger.info("Cleansing %d addresses", len(batch))
    resp = requests.post(
        f"{cfg['address_api_url']}/jp/cleanse/address",
        headers=headers,
        json=batch,
        timeout=120,
    )
    return resp.json()


def extract_cleanse_result(cleanse_response: dict) -> dict:
    results_map = {}

    # Batch format: {"status":"success","results":[{...}]}
    if "results" in cleanse_response:
        for r in cleanse_response["results"]:
            ref_id = r.get("reference_id", "")
            data = r.get("data", {})
            addr_data = data.get("address", {})
            jp_addr = addr_data.get("japanese_address", "")
            is_valid = addr_data.get("is_valid", False)
            verdict = addr_data.get("verdict_level", "unknown")
            zip_data = data.get("zipcode", {})
            suggested = zip_data.get("suggested_correct")
            provided = zip_data.get("provided", "")
            cleansed_zip = suggested if suggested else provided
            results_map[ref_id] = {
                "cleansed_address": jp_addr,
                "cleansed_zip": cleansed_zip,
                "is_valid": is_valid,
                "verdict_level": verdict,
            }
        return results_map

    # Single-item format (fallback)
    ref_id = cleanse_response.get("reference_id", "")
    data = cleanse_response.get("data", {})
    addr_data = data.get("address", {})
    jp_addr = addr_data.get("japanese_address", "")
    is_valid = addr_data.get("is_valid", False)
    verdict = addr_data.get("verdict_level", "unknown")
    zip_data = data.get("zipcode", {})
    suggested = zip_data.get("suggested_correct")
    provided = zip_data.get("provided", "")
    cleansed_zip = suggested if suggested else provided
    results_map[ref_id] = {
        "cleansed_address": jp_addr,
        "cleansed_zip": cleansed_zip,
        "is_valid": is_valid,
        "verdict_level": verdict,
    }
    return results_map


# ── ZipCloud for unverified address correction ─────────────────────────
def lookup_zipcloud(zipcode: str) -> str:
    if not zipcode:
        return ""
    clean = re.sub(r"[^\d]", "", zipcode)
    if len(clean) != 7:
        return ""
    try:
        resp = requests.get(f"http://zipcloud.ibsnet.co.jp/api/search?zipcode={clean}", timeout=10)
        data = resp.json()
        if data.get("status") == 200 and data.get("results"):
            r = data["results"][0]
            return f"{r.get('address1', '')}{r.get('address2', '')}{r.get('address3', '')}"
    except Exception:
        pass
    return ""


def extract_digit_candidates(raw_address: str) -> list:
    if not raw_address:
        return []
    candidates = re.findall(r"\d+", raw_address)
    # filter out likely zipcodes (exactly 7 digits) and very long numbers
    return [c for c in candidates if len(c) != 7 and len(c) <= 5]
def update_order_its(customer_order_no: str, cleansed_address: str, cleansed_postcode: str):
    body = {
        "customerOrderNo": customer_order_no,
        "consignee": {
            "consigneeCountry": "JP",
            "consigneeProvince": " ",
            "consigneeCity": " ",
            "consigneeDistrict": " ",
            "consigneeAddress": cleansed_address,
            "consigneePostcode": cleansed_postcode,
        },
    }
    body_str = json.dumps(body, ensure_ascii=False)
    headers = _its_headers(body_str)
    base_url = _get_config()["its_base_url"]

    logger.info("Updating order %s", customer_order_no)
    resp = requests.post(
        f"{base_url}/its-api/cs/api/updateOrder",
        headers=headers,
        data=body_str.encode("utf-8"),
        timeout=30,
    )
    return resp.json()


# ── Task store (in-memory, between steps) ──────────────────────────────
_task_lock = threading.Lock()
_task_store: dict = {}


def _parse_order_numbers(raw_text: str):
    raw_text = raw_text.replace(",", "\n")
    order_numbers = [line.strip() for line in raw_text.splitlines() if line.strip()]
    seen = set()
    return [x for x in order_numbers if not (x in seen or seen.add(x))]


# ── Routes ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET", "POST"])
def config_handler():
    if request.method == "GET":
        cfg = _get_config()
        return jsonify(cfg)
    else:
        data = request.get_json(silent=True) or {}
        _save_config(data)
        cfg = _get_config()
        return jsonify({"status": "saved", "config": cfg})


# ── STEP 1: 从 ITS 获取订单信息 ────────────────────────────────────────
@app.route("/api/step1", methods=["POST"])
def step1_fetch_orders():
    data = request.get_json(silent=True) or {}
    raw_text = data.get("order_numbers", "")
    order_numbers = _parse_order_numbers(raw_text)

    if not order_numbers:
        return jsonify({"error": "请提供至少一个订单号"}), 400

    logger.info("[Step 1] Fetching %d order(s)", len(order_numbers))

    results = []
    success_items = []
    for order_no in order_numbers:
        item, error = fetch_order_info(order_no)
        if error:
            results.append({
                "customerOrderNo": order_no,
                "status": "error",
                "message": error,
            })
        else:
            results.append({
                "customerOrderNo": item["customerOrderNo"],
                "province": item["province"],
                "city": item["city"],
                "district": item["district"],
                "address": item["address"],
                "postcode": item["postcode"],
                "status": "success",
            })
            success_items.append(item)

    # Store intermediate data keyed by a task_id
    import uuid
    task_id = uuid.uuid4().hex[:12]
    with _task_lock:
        _task_store[task_id] = {
            "order_numbers": order_numbers,
            "success_items": success_items,
        }

    total = len(order_numbers)
    success = len(success_items)
    return jsonify({
        "task_id": task_id,
        "results": results,
        "summary": {"total": total, "success": success, "error": total - success},
    })


# ── STEP 2: 调用地址清洗 API ───────────────────────────────────────────
@app.route("/api/step2", methods=["POST"])
def step2_cleanse():
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")

    with _task_lock:
        task = _task_store.get(task_id)

    if not task:
        return jsonify({"error": "任务已过期，请从第一步重新开始"}), 400

    success_items = task["success_items"]
    logger.info("[Step 2] Cleansing %d address(es)", len(success_items))

    BATCH_SIZE = 100
    results = []
    all_cleansed = {}
    unverified = []

    for i in range(0, len(success_items), BATCH_SIZE):
        sub_batch = success_items[i : i + BATCH_SIZE]
        try:
            cleanse_resp = cleanse_addresses_batch(sub_batch)
            if cleanse_resp.get("status") == "success":
                cleanse_map = extract_cleanse_result(cleanse_resp)
                all_cleansed.update(cleanse_map)
                for item in sub_batch:
                    order_no = item["customerOrderNo"]
                    cdata = cleanse_map.get(order_no, {})
                    if cdata.get("cleansed_address"):
                        is_valid = cdata.get("is_valid", False)
                        verdict = cdata.get("verdict_level", "")
                        result = {
                            "customerOrderNo": order_no,
                            "raw_address": item["raw_address"],
                            "provided_zipcode": item["provided_zipcode"],
                            "cleansed_address": cdata["cleansed_address"],
                            "cleansed_zipcode": cdata["cleansed_zip"],
                            "is_valid": is_valid,
                            "verdict_level": verdict,
                            "status": "verified" if is_valid else "unverified",
                        }
                        results.append(result)
                        if not is_valid:
                            unverified.append(order_no)
                    else:
                        results.append({
                            "customerOrderNo": order_no,
                            "raw_address": item["raw_address"],
                            "provided_zipcode": item["provided_zipcode"],
                            "status": "error",
                            "message": "地址清洗未返回有效结果",
                        })
            else:
                error_msg = cleanse_resp.get("message", "地址清洗失败")
                for item in sub_batch:
                    results.append({
                        "customerOrderNo": item["customerOrderNo"],
                        "raw_address": item["raw_address"],
                        "provided_zipcode": item["provided_zipcode"],
                        "status": "error",
                        "message": error_msg,
                    })
        except Exception as exc:
            logger.exception("[Step 2] Batch failed")
            for item in sub_batch:
                results.append({
                    "customerOrderNo": item["customerOrderNo"],
                    "raw_address": item["raw_address"],
                    "provided_zipcode": item["provided_zipcode"],
                    "status": "error",
                    "message": str(exc),
                })

    # Store cleanse results
    with _task_lock:
        _task_store[task_id]["all_cleansed"] = all_cleansed
        _task_store[task_id]["success_items"] = success_items

    # Enrich unverified orders with ZipCloud data and digit candidates
    unverified_details = []
    for item in success_items:
        order_no = item["customerOrderNo"]
        cdata = all_cleansed.get(order_no, {})
        if cdata.get("cleansed_address") and not cdata.get("is_valid", False):
            zipcode = cdata.get("cleansed_zip", "") or item.get("provided_zipcode", "")
            town = lookup_zipcloud(zipcode)
            digits = extract_digit_candidates(item.get("raw_address", ""))
            unverified_details.append({
                "customerOrderNo": order_no,
                "raw_address": item["raw_address"],
                "zipcode": zipcode,
                "town_name": town,
                "digit_candidates": digits,
                "cleansed_zipcode": cdata["cleansed_zip"],
            })

    total = len(success_items)
    verified_count = sum(1 for r in results if r.get("status") == "verified")
    error_count = sum(1 for r in results if r["status"] == "error")
    return jsonify({
        "task_id": task_id,
        "results": results,
        "unverified": unverified_details,
        "summary": {
            "total": total,
            "verified": verified_count,
            "unverified": len(unverified_details),
            "error": error_count,
        },
    })


# ── 手动修正 ────────────────────────────────────────────────────────────
@app.route("/api/correct", methods=["POST"])
def save_corrections():
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")
    corrections = data.get("corrections", {})

    with _task_lock:
        task = _task_store.get(task_id)

    if not task:
        return jsonify({"error": "任务已过期"}), 400

    all_cleansed = task.get("all_cleansed", {})
    for order_no, corrected_addr in corrections.items():
        if order_no in all_cleansed:
            all_cleansed[order_no]["cleansed_address"] = corrected_addr
            all_cleansed[order_no]["is_valid"] = True

    with _task_lock:
        _task_store[task_id]["all_cleansed"] = all_cleansed

    return jsonify({"status": "saved", "corrected": list(corrections.keys())})


# ── STEP 3: 更新订单回 ITS ─────────────────────────────────────────────
@app.route("/api/step3", methods=["POST"])
def step3_update():
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")

    with _task_lock:
        task = _task_store.get(task_id)

    if not task:
        return jsonify({"error": "任务已过期，请从第一步重新开始"}), 400

    success_items = task["success_items"]
    all_cleansed = task.get("all_cleansed", {})
    logger.info("[Step 3] Updating %d order(s)", len(success_items))

    results = []
    for item in success_items:
        order_no = item["customerOrderNo"]
        cdata = all_cleansed.get(order_no, {})

        if not cdata.get("cleansed_address"):
            results.append({
                "customerOrderNo": order_no,
                "status": "skip",
                "message": "无清洗结果，跳过更新",
            })
            continue

        if not cdata.get("is_valid", False):
            results.append({
                "customerOrderNo": order_no,
                "cleansed_address": cdata["cleansed_address"],
                "cleansed_zipcode": cdata["cleansed_zip"],
                "status": "skip",
                "message": "地址未通过验证，跳过更新",
            })
            continue

        cleansed_address = cdata["cleansed_address"]
        cleansed_zip = cdata["cleansed_zip"]
        try:
            update_resp = update_order_its(order_no, cleansed_address, cleansed_zip)
            if update_resp.get("code") == 0:
                results.append({
                    "customerOrderNo": order_no,
                    "cleansed_address": cleansed_address,
                    "cleansed_zipcode": cleansed_zip,
                    "status": "success",
                    "message": "更新成功",
                })
            else:
                results.append({
                    "customerOrderNo": order_no,
                    "cleansed_address": cleansed_address,
                    "cleansed_zipcode": cleansed_zip,
                    "status": "error",
                    "message": update_resp.get("msg", "更新失败"),
                })
        except Exception as exc:
            logger.exception("[Step 3] Update failed for %s", order_no)
            results.append({
                "customerOrderNo": order_no,
                "cleansed_address": cleansed_address,
                "cleansed_zipcode": cleansed_zip,
                "status": "error",
                "message": str(exc),
            })

    total = len(success_items)
    success = sum(1 for r in results if r["status"] == "success")
    return jsonify({
        "results": results,
        "summary": {"total": total, "success": success, "error": total - success},
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 19933))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port)
