import socket
import socketserver
import threading
import unittest

from hydra_guard.netproxy import FilteringProxy, host_allowed


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1024)
        self.request.sendall(b"echo:" + data)


class ProxyTest(unittest.TestCase):
    def test_patterns(self):
        self.assertTrue(host_allowed("api.example.com", ["api.example.com"]))
        self.assertTrue(host_allowed("API.Example.com.", ["api.example.com"]))
        self.assertFalse(host_allowed("evil-api.example.com", ["api.example.com"]))
        self.assertTrue(host_allowed("a.b.example.com", ["*.example.com"]))
        self.assertTrue(host_allowed("example.com", ["*.example.com"]))
        self.assertFalse(host_allowed("example.com.evil.org", ["*.example.com"]))
        self.assertFalse(host_allowed("notexample.com", ["*.example.com"]))
        self.assertTrue(host_allowed("anything", ["*"]))
        self.assertFalse(host_allowed("anything", []))

    def _connect(self, port, target):
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        return s, s.recv(1024)

    def test_connect_allow_and_block(self):
        server = socketserver.TCPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        try:
            with FilteringProxy(["127.0.0.1"]) as proxy:
                s, head = self._connect(proxy.tcp_port, f"127.0.0.1:{port}")
                self.assertIn(b"200", head.split(b"\r\n")[0])
                s.sendall(b"hi")
                self.assertEqual(s.recv(1024), b"echo:hi")
                s.close()

                s, head = self._connect(proxy.tcp_port, "evil.example:443")
                self.assertIn(b"403", head.split(b"\r\n")[0])
                s.close()
                blocked = [e for e in proxy.events if not e.allowed]
                self.assertEqual([(e.host, e.port) for e in blocked], [("evil.example", 443)])
        finally:
            server.shutdown()
            server.server_close()

    def test_ask_grants_session_exception(self):
        asked = []

        def ask(host, port):
            asked.append(host)
            return host == "ok.example"

        with FilteringProxy([], ask=ask) as proxy:
            self.assertTrue(proxy.decide("ok.example", 443))
            self.assertTrue(proxy.decide("ok.example", 443))  # remembered for the session
            self.assertFalse(proxy.decide("no.example", 443))
        self.assertEqual(asked, ["ok.example", "no.example"])
        self.assertEqual(proxy.session_exceptions, ["ok.example"])


if __name__ == "__main__":
    unittest.main()
