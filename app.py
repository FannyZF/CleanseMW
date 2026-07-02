import os
import re
import json
import hashlib
import time
import logging
import threading

import requests
from flask import Flask, render_template, request, jsonify
from pypinyin import lazy_pinyin, Style

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
    try:
        resp = requests.post(
            f"{base_url}/its-api/cs/api/getOrderInfo",
            headers=headers,
            data=body_str.encode("utf-8"),
            timeout=30,
        )
    except requests.exceptions.ConnectionError:
        return None, "ITS 服务连接失败，请检查 ITS_BASE_URL 地址和网络"
    except requests.exceptions.Timeout:
        return None, "ITS 服务请求超时"
    except Exception as exc:
        return None, f"ITS 接口请求异常: {exc}"

    if resp.status_code != 200:
        snippet = resp.text[:200] if resp.text else ""
        return None, f"ITS 返回 HTTP {resp.status_code}: {snippet}"

    try:
        result = resp.json()
    except Exception:
        snippet = resp.text[:200] if resp.text else ""
        return None, f"ITS 返回非 JSON 格式: {snippet}"

    if result.get("code") != 0:
        return None, result.get("msg", "Unknown error")

    consignee = result["data"]["consignee"]
    province = consignee.get("consigneeProvince") or ""
    city = consignee.get("consigneeCity") or ""
    district = consignee.get("consigneeDistrict") or ""
    address = consignee.get("consigneeAddress") or ""
    postcode = consignee.get("consigneePostcode") or ""
    consignee_name = consignee.get("consigneeName") or ""

    raw_address = f"{province}{city}{district}{address}".strip()

    return {
        "customerOrderNo": customer_order_no,
        "province": province,
        "city": city,
        "district": district,
        "address": address,
        "postcode": postcode,
        "consigneeName": consignee_name,
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
    try:
        resp = requests.post(
            f"{cfg['address_api_url']}/jp/cleanse/address",
            headers=headers,
            json=batch,
            timeout=60,
        )
        return resp.json()
    except requests.exceptions.Timeout:
        logger.error("Address cleansing timed out after 60s")
        return {"status": "error", "message": "地址清洗接口超时"}
    except Exception as exc:
        logger.error("Address cleansing request failed: %s", exc)
        return {"status": "error", "message": str(exc)}


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


# ── Name cleansing via API Hub ─────────────────────────────────────────
def cleanse_names_batch(items: list):
    cfg = _get_config()
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": cfg["address_api_key"],
    }
    api_url = f"{cfg['address_api_url']}/jp/cleanse/name"

    all_results = []
    for item in items:
        if not item.get("consigneeName"):
            continue
        body = {
            "order_id": item["customerOrderNo"],
            "raw_name": item["consigneeName"],
        }
        try:
            resp = requests.post(api_url, headers=headers, json=body, timeout=15)
            data = resp.json()
            if data.get("status") == "success":
                all_results.append(data)
        except requests.exceptions.Timeout:
            logger.error("Name cleanse timeout for %s", item["customerOrderNo"])
        except Exception as exc:
            logger.error("Name cleanse failed for %s: %s", item["customerOrderNo"], exc)

    logger.info("Cleansed %d/%d names", len(all_results), len(items))
    return {"status": "success", "results": all_results} if all_results else {}


def extract_name_result(name_response: dict) -> dict:
    results_map = {}
    if "results" in name_response:
        for r in name_response["results"]:
            ref_id = r.get("reference_id", "")
            data = r.get("data", {})
            name_data = data.get("name", {})
            results_map[ref_id] = {
                "original_name": name_data.get("original", ""),
                "japanese_katakana": name_data.get("japanese_katakana", ""),
                "japanese_kanji": name_data.get("japanese_kanji", ""),
                "english_romaji": name_data.get("english_romaji", ""),
            }
        return results_map

    # Single-item fallback
    ref_id = name_response.get("reference_id", "")
    data = name_response.get("data", {})
    name_data = data.get("name", {})
    results_map[ref_id] = {
        "original_name": name_data.get("original", ""),
        "japanese_katakana": name_data.get("japanese_katakana", ""),
        "japanese_kanji": name_data.get("japanese_kanji", ""),
        "english_romaji": name_data.get("english_romaji", ""),
    }
    return results_map


def _detect_name_lang(name: str) -> str:
    if not name:
        return "other"
    has_kana = any("\u3040" <= c <= "\u30ff" for c in name)
    if has_kana:
        return "japanese"
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in name)
    if has_cjk:
        return "chinese"
    if any(c.isalpha() and ord(c) < 128 for c in name):
        return "english"
    return "other"


def _is_romaji_valid(romaji: str) -> bool:
    if not romaji:
        return False
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in romaji)
    has_latin = any(c.isalpha() and ord(c) < 128 for c in romaji)
    return has_latin and not has_cjk


def _resolve_consignee_name(raw_name: str, ndata: dict) -> tuple:
    """Return (consigneeName, consigneeCompany) based on language detection."""
    lang = _detect_name_lang(raw_name)
    katakana = ndata.get("japanese_katakana", "")
    kanji = ndata.get("japanese_kanji", "")
    romaji = ndata.get("english_romaji", "")

    if lang == "english":
        return (kanji or katakana, raw_name)
    elif _is_romaji_valid(romaji):
        return (raw_name, romaji)
    else:
        return (katakana, _chinese_to_romaji(raw_name))


def _chinese_to_romaji(name: str) -> str:
    if not name:
        return ""
    parts = lazy_pinyin(name, style=Style.NORMAL, errors="ignore")
    return " ".join(parts).title()


def _parse_japanese_address(full_addr: str) -> tuple:
    """Split Japanese address into (province, city, district, address)."""
    province = city = district = address = ""
    if not full_addr:
        return province, city, district, address
    remaining = full_addr

    for suffix in ["都", "道", "府", "県"]:
        idx = remaining.find(suffix)
        if idx >= 0:
            province = remaining[:idx + 1]
            remaining = remaining[idx + 1:]
            break

    idx_shi = remaining.find("市")
    idx_ku = remaining.find("区")
    if idx_shi >= 0 and (idx_ku < 0 or idx_shi < idx_ku):
        city = remaining[:idx_shi + 1]
        remaining = remaining[idx_shi + 1:]
    elif idx_ku >= 0:
        city = remaining[:idx_ku + 1]
        remaining = remaining[idx_ku + 1:]

    idx_machi = remaining.find("町")
    if idx_machi >= 0:
        district = remaining[:idx_machi + 1]
        address = remaining[idx_machi + 1:]
    else:
        digit_match = re.search(r"\d", remaining)
        if digit_match:
            idx = digit_match.start()
            district = remaining[:idx]
            address = remaining[idx:]
        else:
            address = remaining

    return province, city, district, address


def _fix_street_number(address: str) -> str:
    return re.sub(r"(\d+)\s+(\d+)", r"\1-\2", address)


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
def update_order_its(customer_order_no: str, cleansed_address: str, cleansed_postcode: str,
                     consignee_name: str = "", consignee_company: str = "",
                     province: str = "", city: str = "", district: str = ""):
    consignee = {"consigneeCountry": "JP"}

    if cleansed_address:
        consignee["consigneeProvince"] = province or " "
        consignee["consigneeCity"] = city or " "
        consignee["consigneeDistrict"] = district or " "
        consignee["consigneeAddress"] = cleansed_address
        consignee["consigneePostcode"] = cleansed_postcode
    if consignee_name:
        consignee["consigneeName"] = consignee_name
    if consignee_company:
        consignee["consigneeCompany"] = consignee_company
    body = {
        "customerOrderNo": customer_order_no,
        "consignee": consignee,
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


@app.route("/api/test-its", methods=["POST"])
def test_its():
    """Test ITS API connectivity and return detailed diagnostic info."""
    data = request.get_json(silent=True) or {}
    test_order = data.get("order_no", "TEST")
    cfg = _get_config()

    body = {"customerOrderNo": test_order}
    body_str = json.dumps(body, ensure_ascii=False)
    timestamp = str(int(time.time()))
    raw_sign = f"{cfg['its_apikey']}{cfg['its_apisecret']}{cfg['its_usertoken']}{timestamp}{body_str}"
    signature = hashlib.md5(raw_sign.encode("utf-8")).hexdigest()
    base_url = cfg["its_base_url"]
    url = f"{base_url}/its-api/cs/api/getOrderInfo"

    info = {
        "url": url,
        "timestamp": timestamp,
        "body": body_str,
        "sign_raw": raw_sign[:50] + "...",
        "apikey_len": len(cfg["its_apikey"]),
        "apisecret_len": len(cfg["its_apisecret"]),
        "usertoken_len": len(cfg["its_usertoken"]),
    }

    try:
        resp = requests.post(url, headers={
            "apikey": cfg["its_apikey"],
            "signature": signature,
            "timestamp": timestamp,
            "usertoken": cfg["its_usertoken"],
            "Content-Type": "application/json;charset=UTF-8",
        }, data=body_str.encode("utf-8"), timeout=30)
        info["http_status"] = resp.status_code
        info["response_preview"] = resp.text[:500]
        try:
            info["response_json"] = resp.json()
        except Exception:
            pass
    except requests.exceptions.ConnectionError as e:
        info["error"] = f"连接失败: {e}"
    except requests.exceptions.Timeout:
        info["error"] = "请求超时 (30s)"
    except Exception as e:
        info["error"] = str(e)

    return jsonify(info)


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
                "consigneeName": item["consigneeName"],
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


# ── STEP 2a: 地址去重 ──────────────────────────────────────────────────
@app.route("/api/step2a", methods=["POST"])
def step2a_address():
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")

    with _task_lock:
        task = _task_store.get(task_id)

    if not task:
        return jsonify({"error": "任务已过期，请从第一步重新开始"}), 400

    success_items = task["success_items"]
    logger.info("[Step 2a] Deduplicating %d address(es)", len(success_items))

    results = []
    all_cleansed = {}

    for item in success_items:
        order_no = item["customerOrderNo"]
        province = item.get("province", "")
        city = item.get("city", "")
        district = item.get("district", "")
        address = item.get("address", "")
        postcode = item.get("postcode", "")

        cleaned = address
        for part in [province, city, district]:
            if part and part in cleaned:
                cleaned = cleaned.replace(part, "", 1)
        cleaned = cleaned.strip()

        all_cleansed[order_no] = {
            "cleansed_address": cleaned,
            "cleansed_zip": postcode,
            "is_valid": True,
        }

        results.append({
            "customerOrderNo": order_no,
            "raw_address": item["raw_address"],
            "province": province,
            "city": city,
            "district": district,
            "original_address": address,
            "cleansed_address": cleaned,
            "provided_zipcode": postcode,
            "cleansed_zipcode": postcode,
            "status": "success",
        })

    with _task_lock:
        _task_store[task_id]["all_cleansed"] = all_cleansed
        _task_store[task_id]["success_items"] = success_items

    total = len(success_items)
    return jsonify({
        "task_id": task_id,
        "results": results,
        "unverified": [],
        "summary": {"total": total, "verified": total, "unverified": 0, "error": 0},
    })


# ── STEP 2b: 姓名清洗 ──────────────────────────────────────────────────
@app.route("/api/step2b", methods=["POST"])
def step2b_name():
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")

    with _task_lock:
        task = _task_store.get(task_id)

    if not task:
        return jsonify({"error": "任务已过期，请从第一步重新开始"}), 400

    success_items = task["success_items"]
    logger.info("[Step 2b] Cleansing %d name(s)", len(success_items))

    all_names = {}
    results = []

    try:
        name_resp = cleanse_names_batch(success_items)
        if name_resp.get("status") == "success":
            all_names = extract_name_result(name_resp)
            for item in success_items:
                order_no = item["customerOrderNo"]
                ndata = all_names.get(order_no, {})
                raw_name = item.get("consigneeName", "")
                res_name, res_company = _resolve_consignee_name(raw_name, ndata) if ndata else ("", "")
                all_names[order_no] = ndata
                all_names[order_no]["resolved_name"] = res_name
                all_names[order_no]["resolved_company"] = res_company
                results.append({
                    "customerOrderNo": order_no,
                    "original_name": ndata.get("original_name", raw_name),
                    "english_romaji": res_company,
                    "consigneeName": res_name,
                    "consigneeCompany": res_company,
                    "status": "success" if ndata else "error",
                    "message": "" if ndata else "姓名清洗无结果",
                })
    except Exception as exc:
        logger.exception("[Step 2b] Name cleansing failed")

    with _task_lock:
        _task_store[task_id]["all_names"] = all_names

    total = len(success_items)
    success = sum(1 for r in results if r["status"] == "success")
    return jsonify({
        "task_id": task_id,
        "results": results,
        "summary": {"total": total, "success": success, "error": total - success},
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
    all_names = task.get("all_names", {})
    logger.info("[Step 3] Updating %d order(s)", len(success_items))

    results = []
    for item in success_items:
        order_no = item["customerOrderNo"]
        cdata = all_cleansed.get(order_no, {})
        ndata = all_names.get(order_no, {})

        has_address = bool(cdata.get("cleansed_address"))
        has_name = bool(ndata.get("resolved_name"))

        if not has_address and not has_name:
            results.append({
                "customerOrderNo": order_no,
                "status": "skip",
                "message": "无地址和姓名清洗数据，跳过更新",
            })
            continue

        cleansed_address = cdata.get("cleansed_address", "")
        cleansed_zip = cdata.get("cleansed_zip", item.get("postcode", ""))
        province, city, district, street = "", "", "", ""

        if cleansed_address:
            province, city, district, street = _parse_japanese_address(cleansed_address)
            street = _fix_street_number(street)

        consignee_name = ndata.get("resolved_name", item.get("consigneeName", ""))
        consignee_company = ndata.get("resolved_company", "")

        try:
            update_resp = update_order_its(
                order_no, street or cleansed_address, cleansed_zip,
                consignee_name, consignee_company,
                province, city, district,
            )
            if update_resp.get("code") == 0:
                results.append({
                    "customerOrderNo": order_no,
                    "cleansed_address": cleansed_address,
                    "cleansed_zipcode": cleansed_zip,
                    "original_name": consignee_name,
                    "english_romaji": consignee_company,
                    "status": "success",
                    "message": "更新成功",
                })
            else:
                results.append({
                    "customerOrderNo": order_no,
                    "cleansed_address": cleansed_address,
                    "cleansed_zipcode": cleansed_zip,
                    "original_name": consignee_name,
                    "english_romaji": consignee_company,
                    "status": "error",
                    "message": update_resp.get("msg", "更新失败"),
                })
        except Exception as exc:
            logger.exception("[Step 3] Update failed for %s", order_no)
            results.append({
                "customerOrderNo": order_no,
                "cleansed_address": cleansed_address,
                "cleansed_zipcode": cleansed_zip,
                "original_name": consignee_name,
                "english_romaji": consignee_company,
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
