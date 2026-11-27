"""
OfficeKit Desktop Launcher (Lightweight Native Webview)
Runs the local FastAPI backend with native OS Webview (WebKit on Mac, WebView2 on Windows, WebKitGTK on Linux).
Bundle footprint: ~25 MB (vs 150MB+ Electron). Zero Node.js runtime overhead.
"""

import sys
import threading
import time
import uvicorn
import webview
from app import app

def run_api_server():
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="warning",
        access_log=False,
    )

def main():
    # Start the local FastAPI server in background thread
    server_thread = threading.Thread(target=run_api_server, daemon=True)
    server_thread.start()

    # Allow server to bind
    time.sleep(0.5)

    # Launch native OS hardware-accelerated webview window
    window = webview.create_window(
        title="OfficeKit — The Everyday Toolbox for your Computer",
        url="http://127.0.0.1:8000",
        width=1200,
        height=820,
        min_size=(900, 600),
        confirm_close=False
    )
    webview.start(debug=False)

if __name__ == "__main__":
    main()
