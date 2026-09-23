import json
import os
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from maf import flows, ui


class LocalUITests(unittest.TestCase):
    def test_local_editor_requires_token_and_saves_a_named_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                try:
                    http = ui.server()
                except PermissionError:
                    self.skipTest("loopback sockets are disabled in this sandbox")
                thread = threading.Thread(target=http.serve_forever, daemon=True)
                thread.start()
                try:
                    url = f"http://127.0.0.1:{http.server_port}"
                    with urlopen(url + "/") as response:
                        html = response.read().decode()
                    self.assertIn("Flow Studio", html)
                    self.assertIn('id="coder-runtime"', html)
                    self.assertIn('id="main-runtime"', html)
                    self.assertIn('id="review-enabled"', html)
                    self.assertIn("claude-opus-5-5", html)
                    self.assertIn('id="set-default"', html)
                    with urlopen(url + "/guide") as response:
                        guide = response.read().decode()
                    self.assertIn("設計理念", guide)
                    self.assertIn("awaiting_approval", guide)
                    token = re.search(r'const token="([0-9a-f]+)"', html).group(1)
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(url + "/api/state")
                    self.assertEqual(denied.exception.code, 404)
                    denied.exception.close()
                    headers = {"X-MAF-Token": token, "Origin": url, "Content-Type": "application/json"}
                    flow = flows.templates()["quick"]
                    flow["roles"]["reviewer"]["effort"] = "high"
                    body = json.dumps({"name": "my-flow", "flow": flow}).encode()
                    with urlopen(Request(url + "/api/flow", body, headers=headers)) as response:
                        self.assertIn("my-flow", json.load(response)["flows"])
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(Request(url + "/api/mode", json.dumps({"name": "my-flow"}).encode(), headers=headers))
                    self.assertEqual(denied.exception.code, 400)
                    denied.exception.close()
                    with urlopen(Request(url + "/api/settings", b'{"herdr_enabled": true}', headers=headers)) as response:
                        self.assertTrue(json.load(response)["settings"]["herdr_enabled"])
                    with urlopen(Request(url + "/api/default", b'{"name": "my-flow"}', headers=headers)) as response:
                        self.assertEqual(json.load(response)["settings"]["default_flow"], "my-flow")
                    with urlopen(Request(url + "/api/default", b'{"name": "codex-pi"}', headers=headers)) as response:
                        saved = json.load(response)["settings"]
                        self.assertEqual(saved["default_flow"], "my-flow")
                        self.assertEqual(saved["codex_default_flow"], "codex-pi")
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(Request(url + "/api/settings", b'{}', headers=dict(headers, Origin="https://evil.example")))
                    self.assertEqual(denied.exception.code, 403)
                    denied.exception.close()
                finally:
                    http.shutdown()
                    http.server_close()
                    thread.join(2)


if __name__ == "__main__":
    unittest.main()
