import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from maf import core, flows, ui


class LocalUITests(unittest.TestCase):
    def test_local_editor_requires_token_and_saves_a_named_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            core.init(repo, "economy")
            try:
                http = ui.server(repo)
            except PermissionError:
                self.skipTest("loopback sockets are disabled in this sandbox")
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 2)
            self.addCleanup(http.server_close)
            self.addCleanup(http.shutdown)
            url = f"http://127.0.0.1:{http.server_port}"
            with urlopen(url + "/") as response:
                html = response.read().decode()
            self.assertIn("Flow Studio", html)
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
            with urlopen(Request(url + "/api/mode", json.dumps({"name": "my-flow"}).encode(), headers=headers)) as response:
                self.assertEqual(json.load(response)["mode"], "my-flow")
            with self.assertRaises(HTTPError) as denied:
                urlopen(Request(url + "/api/mode", b'{}', headers=dict(headers, Origin="https://evil.example")))
            self.assertEqual(denied.exception.code, 403)
            denied.exception.close()


if __name__ == "__main__":
    unittest.main()
