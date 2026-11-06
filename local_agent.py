

import os
import threading

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

import fingerprint_sdk

REMOTE_API = os.environ.get("FP_REMOTE_API", "https://gdp-fg-uat.interior.gov.kh")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

_device_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


@app.route("/api/local/health")
def health():
    """Lets the frontend check the agent is running before starting the fingerprint step."""
    return jsonify({"ok": True, "remote_api": REMOTE_API})


@app.route("/api/local/fingerprint/scan", methods=["POST"])
def scan():
    acquired = _device_lock.acquire(blocking=True, timeout=3.0)  # a bit more patience
    if not acquired:
        return jsonify({
            "ok": False,
            "error": "Reader is busy with another scan. Please wait a moment and try again."
        }), 409

    try:
        log("[LOCAL] Waiting for finger on the reader...")
        template, image = fingerprint_sdk.capture_fingerprint_with_image()
        fingerprint_sdk.print_capture_report(template, label="CAPTURE")

        payload = {"ok": True, "template": template}
        if image:
            payload["image"] = image
        return jsonify(payload)

    except Exception as e:
        log(f"[LOCAL SCAN ERROR] {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

    finally:
        try:
            _device_lock.release()
        except RuntimeError:
            pass
            
@app.route("/api/local/fingerprint/verify", methods=["POST"])
def verify():
    """
    1:N identify. Captures a fresh scan, fetches every stored template
    from the remote backend, and matches locally (dpfj.dll can't run on
    the Linux server). Returns the matched user's full profile if found.
    """
    if not _device_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Reader is busy with another scan."}), 409

    try:
        log("[LOCAL] Waiting for finger on the reader (verify)...")
        candidate, image = fingerprint_sdk.capture_fingerprint_with_image()

        try:
            resp = requests.get(f"{REMOTE_API}/api/verify/fingerprint-templates", timeout=10)
            resp.raise_for_status()
            templates = resp.json().get("templates", [])
        except requests.RequestException as e:
            return jsonify({"ok": False, "error": f"Could not reach remote server: {e}"}), 502

        for entry in templates:
            if fingerprint_sdk.match_two_templates(entry["template"], candidate):
                user_id = entry["user_id"]
                finger_key = entry["finger_key"]
                log(f"[LOCAL VERIFY] MATCH -> user={user_id} finger={finger_key}")

                # fetch the full profile for display
                try:
                    user_resp = requests.get(f"{REMOTE_API}/api/users/{user_id}", timeout=10)
                    user_data = user_resp.json().get("user", {})
                except requests.RequestException:
                    user_data = {"id": user_id}

                payload = {
                    "ok": True, "match": True,
                    "finger_matched": finger_key,
                    "user": user_data,
                }
                if image:
                    payload["image"] = image
                return jsonify(payload)

        log("[LOCAL VERIFY] NO MATCH")
        payload = {"ok": True, "match": False}
        if image:
            payload["image"] = image
        return jsonify(payload)
    except Exception as e:
        log(f"[LOCAL VERIFY ERROR] {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        _device_lock.release()


if __name__ == "__main__":
    print(f"Local fingerprint agent starting - http://127.0.0.1:5001 (remote: {REMOTE_API})")
    app.run(host="127.0.0.1", port=5001, threaded=True, debug=False)
