"""Local replay, evidence inspection and versioned analyst feedback."""

import fcntl
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import joblib

from .ingestion import ROOT, digest
from .pipeline import WorkloadReplay, configuration, verify_model
from .presentation import RunPresentation
from .store import WorkloadStore


class WorkloadService:
    def __init__(self):
        self.store = WorkloadStore()
        self.thread = None
        self.stop = threading.Event()
        self.error = None
        self.config = configuration()
        self.gate = None
        self.input_names = []
        self.readiness_error = None
        try:
            verify_model()
            bundle = joblib.load(ROOT / self.config["deployment"]["model"])
            self.gate = bundle["gates"][self.config["deployment"]["gate"]]
            self.input_names = bundle["names"]
        except (OSError, ValueError) as e:
            self.readiness_error = str(e)
        self.presentation = RunPresentation(self.store, self.config, self.gate, digest(ROOT / "config.json"))

    def summary(self):
        r = self.store.summary()
        external = False
        with self.store.path.with_suffix(".lock").open("a+") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(probe, fcntl.LOCK_UN)
            except BlockingIOError:
                external = True
        r["ready"] = self.gate is not None
        r["readiness_error"] = self.readiness_error
        r["running"] = external or bool(self.thread and self.thread.is_alive())
        r["error"] = self.error
        r.update(json.loads((ROOT / "results.json").read_text()))
        r["pipeline"] = {
            "sources": self.config["sources"],
            "gate": self.gate,
            "input_names": self.input_names,
            "queue": self.config["queue"],
            "reference_days": self.config["reference_windows"][0],
            "reference_lag_days": self.config["reference_lag_days"],
            "scoring_period": self.config["final"],
            "feature_contract": "behavior-workload-v4",
        }
        return r

    def command(self, action):
        if action == "pause":
            self.stop.set()
            return self.summary()
        if self.thread and self.thread.is_alive():
            raise ValueError("Pause the running worker first")
        if action == "new":
            p = WorkloadReplay(new=True)
            p.close()
            return self.summary()
        if action != "start":
            raise ValueError("Unknown command")
        self.stop.clear()
        self.error = None

        def work():
            p = None
            try:
                p = WorkloadReplay()
                while not self.stop.is_set() and p.status != "completed":
                    p.step()
            except Exception as e:
                self.error = str(e)
            finally:
                if p:
                    p.close()

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        return self.summary()


SERVICE = None


class Handler(BaseHTTPRequestHandler):
    def send(self, obj, status=200):
        b = json.dumps(obj, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        try:
            url = urlparse(self.path)
            q = parse_qs(url.query)

            def get(k, d=""):
                return q.get(k, [d])[0]

            if url.path == "/api/summary":
                return self.send(SERVICE.summary())
            if url.path == "/api/cases":
                return self.send(
                    SERVICE.store.queue(
                        search=get("search"),
                        status=get("status", "all"),
                        offset=max(0, int(get("offset", "0"))),
                    )
                )
            if url.path == "/api/case":
                return self.send(SERVICE.store.detail(get("id"), max(0, int(get("offset", "0")))))
            if url.path == "/api/demo":
                return self.send(SERVICE.presentation.snapshot(int(get("step", "0"))))
            if url.path not in ["/", "/workload.js", "/style.css"]:
                return self.send({"error": "Not found"}, 404)
            p = ROOT / "dashboard" / ("workload.html" if url.path == "/" else url.path[1:])
            b = p.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/html"
                if url.path == "/"
                else "application/javascript"
                if p.suffix == ".js"
                else "text/css",
            )
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)
        except Exception as e:
            self.send({"error": str(e)}, 400)

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            host = self.headers.get("Host")
            if origin and urlparse(origin).netloc != host:
                raise ValueError("Origin rejected")
            n = int(self.headers.get("Content-Length", "0"))
            if n > 20000:
                raise ValueError("Request too large")
            payload = json.loads(self.rfile.read(n) or b"{}")
            action = self.path.rsplit("/", 1)[-1]
            if action == "review":
                return self.send(
                    SERVICE.store.review(
                        payload["id"],
                        int(payload["version"]),
                        payload["status"],
                        payload["disposition"],
                        payload.get("note", ""),
                    )
                )
            return self.send(SERVICE.command(action))
        except Exception as e:
            self.send({"error": str(e)}, 400)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


def serve(host="127.0.0.1", port=8767):
    global SERVICE
    SERVICE = WorkloadService()
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        SERVICE.stop.set()
        server.server_close()
