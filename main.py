import os
import threading
import time

from local_agent import app

FRONTEND_URL = os.environ.get("FP_FRONTEND_URL", "https://gdp-fg-uat.interior.gov.kh")
LOCAL_PORT = 5001

# Default = do NOT open browser
# Set FP_OPEN_BROWSER=1 if you want it to open the browser
OPEN_BROWSER = os.environ.get("FP_OPEN_BROWSER", "0") == "1"


def run_server():
    app.run(host="127.0.0.1", port=LOCAL_PORT, threaded=True)


if __name__ == "__main__":
    print(f"Local Fingerprint Agent starting on http://127.0.0.1:{LOCAL_PORT}")
    print(f"Remote API : {os.environ.get('FP_REMOTE_API', 'hhttps://gdp-fg-uat.interior.gov.kh')}")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    time.sleep(1)  # give Flask a moment to bind

    if OPEN_BROWSER:
        try:
            import webbrowser
            webbrowser.open(FRONTEND_URL)
            print(f"Opened browser → {FRONTEND_URL}")
        except Exception as e:
            print(f"Could not open browser: {e}")
    else:
        print("Browser will NOT open (FP_OPEN_BROWSER=0)")

    print("Agent is running. Press Ctrl+C to stop.")
    server_thread.join()