"""Request guards of the local service; no replay or data is needed."""

import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

from sentinelid import server


class ServerGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.saved = server.HOSTS
        server.HOSTS = {f"127.0.0.1:{cls.port}", f"localhost:{cls.port}"}
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.HOSTS = cls.saved

    def request(self, method, path, host=None, headers=None, body=b""):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest(method, path, skip_host=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        for k, v in (headers or {}).items():
            connection.putheader(k, v)
        if "Content-Length" not in (headers or {}):
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        status = connection.getresponse().status
        connection.close()
        return status

    def test_rebound_host_is_rejected(self):
        # A DNS-rebound page sends its own name as Host and as Origin; both must not pass.
        evil = f"attacker.example:{self.port}"
        self.assertEqual(self.request("GET", "/api/cases", host=evil), 403)
        origin = {"Origin": "http://" + evil}
        self.assertEqual(self.request("POST", "/api/review", host=evil, headers=origin), 403)

    def test_cross_origin_post_is_rejected(self):
        origin = {"Origin": "http://attacker.example"}
        self.assertEqual(self.request("POST", "/api/pause", headers=origin), 400)

    def test_only_declared_commands_are_routed(self):
        self.assertEqual(self.request("POST", "/anything/start"), 404)
        self.assertEqual(self.request("GET", "/../config.json"), 404)

    def test_negative_length_is_refused(self):
        self.assertEqual(self.request("POST", "/api/review", headers={"Content-Length": "-1"}), 400)


if __name__ == "__main__":
    unittest.main()
