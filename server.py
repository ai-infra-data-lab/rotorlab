"""Loopback-only, offline UI. No uploaded model files are written on the server."""
import argparse
import json
import secrets
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from model import InputError, sample_model, validate_model

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
SOLVER_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def send(self, status, content, mime="application/json; charset=utf-8"):
        if not isinstance(content, bytes):
            content = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(content)

    def json(self, obj, status=200):
        self.send(status, json.dumps(obj, ensure_ascii=False, allow_nan=False))

    def trusted_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def do_GET(self):
        if not self.trusted_host():
            return self.json({"error": "Invalid Host"}, 403)
        path = urlsplit(self.path).path
        if path == "/api/sample":
            return self.json(sample_model())
        if path == "/api/health":
            return self.json({"ok": True, "app": "RotorLab", "version": "0.1.0"})
        if path == "/":
            html = (ROOT / "static/index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self.send(200, html, "text/html; charset=utf-8")
        if path == "/plotly.min.js":
            from plotly.offline import get_plotlyjs
            return self.send(200, get_plotlyjs(), "text/javascript; charset=utf-8")
        files = {"/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path in files:
            name, mime = files[path]
            return self.send(200, (ROOT / "static" / name).read_bytes(), mime)
        self.json({"error": "Not found"}, 404)

    def do_POST(self):
        if not self.trusted_host() or self.headers.get("X-RotorLab-Token") != TOKEN:
            return self.json({"error": "この画面から操作してください。"}, 403)
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
            return self.json({"error": "Invalid Origin"}, 403)
        if self.path not in ("/api/validate", "/api/analyze"):
            return self.json({"error": "Not found"}, 404)
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 300000:
                return self.json({"error": "モデルは300KB以内にしてください。"}, 413)
            data = json.loads(self.rfile.read(size))
            valid = validate_model(data)
            if self.path == "/api/validate":
                return self.json({"ok": True, "model": valid})
            if not SOLVER_LOCK.acquire(blocking=False):
                return self.json({"error": "別の計算を実行中です。完了後に再実行してください。"}, 409)
            try:
                from engine import analyze
                result = analyze(valid)
                self.json(result)
            finally:
                SOLVER_LOCK.release()
        except (InputError, ValueError, TypeError, KeyError, OverflowError) as exc:
            self.json({"error": str(exc)}, 400)
        except Exception:
            traceback.print_exc()
            self.json({"error": "計算を完了できませんでした。起動ウィンドウのログを確認してください。"}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        raise SystemExit(f"起動できません。別のポートを --port 8766 で指定してください。\n{exc}")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"RotorLab: {url}\n終了: このウィンドウで Ctrl+C", flush=True)
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
