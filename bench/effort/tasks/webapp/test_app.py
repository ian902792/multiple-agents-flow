from html.parser import HTMLParser
import io
import json
import unittest
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

from app import make_app


def call(app, method, path, body=b"", content_type=None):
    environ = {}
    setup_testing_defaults(environ)
    environ.update(REQUEST_METHOD=method, PATH_INFO=path, CONTENT_LENGTH=str(len(body)), QUERY_STRING="")
    environ["wsgi.input"] = io.BytesIO(body)
    if content_type:
        environ["CONTENT_TYPE"] = content_type
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = int(status.split()[0])
        captured["headers"] = {k.lower(): v for k, v in headers}

    chunks = app(environ, start_response)
    try:
        data = b"".join(chunks)
    finally:
        getattr(chunks, "close", lambda: None)()
    return captured["status"], captured["headers"], data


def api(app, method, path, payload=None, raw=None):
    body = raw if raw is not None else (b"" if payload is None else json.dumps(payload).encode())
    return call(app, method, path, body, "application/json" if body else None)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.title, self.items, self._in, self._li = [], "", [], None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag in ("title", "li"):
            self._in = tag
            if tag == "li":
                self._li = {"attrs": attrs, "text": ""}
                self.items.append(self._li)

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "li":
            self._li["text"] += data


def page(app):
    status, headers, body = call(app, "GET", "/")
    parsed = Page()
    parsed.feed(body.decode())
    return status, headers, body, parsed


class HtmlPage(unittest.TestCase):
    def test_empty_page_structure(self):
        status, headers, body, parsed = page(make_app())
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        self.assertIn("charset=utf-8", headers["content-type"].lower())
        self.assertEqual(parsed.title.strip(), "Todos")
        forms = [a for t, a in parsed.tags if t == "form"]
        self.assertEqual([(f.get("method", "").lower(), f.get("action")) for f in forms], [("post", "/todos")])
        self.assertTrue(any(t == "label" and a.get("for") == "title" for t, a in parsed.tags))
        inputs = [a for t, a in parsed.tags if t == "input" and a.get("id") == "title"]
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0].get("name"), "title")
        self.assertIn("required", inputs[0])
        self.assertEqual(inputs[0].get("maxlength"), "100")
        self.assertTrue(any(t == "ul" and a.get("id") == "todos" for t, a in parsed.tags))
        self.assertEqual(parsed.items, [])

    def test_form_post_creates_todo_and_redirects(self):
        app = make_app()
        status, headers, _ = call(app, "POST", "/todos", urlencode({"title": "  Buy milk  "}).encode(),
                                  "application/x-www-form-urlencoded")
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/")
        _, _, _, parsed = page(app)
        self.assertEqual([(i["attrs"].get("data-id"), i["text"].strip()) for i in parsed.items], [("1", "Buy milk")])

    def test_form_post_rejects_blank_and_long_titles(self):
        app = make_app()
        for title in ("", "   ", "x" * 101):
            with self.subTest(title=title[:10]):
                status, headers, body = call(app, "POST", "/todos", urlencode({"title": title}).encode(),
                                             "application/x-www-form-urlencoded")
                self.assertEqual(status, 400)
                self.assertTrue(headers["content-type"].startswith("text/html"))
                self.assertIn(b"error", body.lower())
        self.assertEqual(api(app, "GET", "/api/todos")[2], b"[]")

    def test_titles_are_escaped_and_done_items_marked(self):
        app = make_app()
        api(app, "POST", "/api/todos", {"title": "<script>alert(1)</script> & \"q\""})
        api(app, "POST", "/api/todos", {"title": "Second"})
        api(app, "PATCH", "/api/todos/2", {"done": True})
        _, _, body, parsed = page(app)
        self.assertNotIn(b"<script>alert", body)
        self.assertEqual(parsed.items[0]["text"].strip(), "<script>alert(1)</script> & \"q\"")
        self.assertNotIn("done", parsed.items[0]["attrs"].get("class", "").split())
        self.assertIn("done", parsed.items[1]["attrs"].get("class", "").split())


class JsonApi(unittest.TestCase):
    def test_create_list_and_location(self):
        app = make_app()
        status, headers, body = api(app, "POST", "/api/todos", {"title": " Write tests "})
        self.assertEqual(status, 201)
        self.assertEqual(headers["content-type"].split(";")[0], "application/json")
        self.assertEqual(headers["location"], "/api/todos/1")
        self.assertEqual(json.loads(body), {"id": 1, "title": "Write tests", "done": False})
        api(app, "POST", "/api/todos", {"title": "Ship"})
        status, headers, body = api(app, "GET", "/api/todos")
        self.assertEqual(status, 200)
        self.assertEqual([t["title"] for t in json.loads(body)], ["Write tests", "Ship"])

    def test_create_validation(self):
        app = make_app()
        cases = [(b"{not json", 400), (b"[1, 2]", 400), (json.dumps({}).encode(), 422),
                 (json.dumps({"title": 5}).encode(), 422), (json.dumps({"title": "   "}).encode(), 422),
                 (json.dumps({"title": "x" * 101}).encode(), 422)]
        for raw, expected in cases:
            with self.subTest(raw=raw[:20]):
                status, headers, body = api(app, "POST", "/api/todos", raw=raw)
                self.assertEqual(status, expected)
                self.assertEqual(headers["content-type"].split(";")[0], "application/json")
                self.assertIsInstance(json.loads(body).get("error"), str)
        self.assertEqual(json.loads(api(app, "GET", "/api/todos")[2]), [])

    def test_patch_done(self):
        app = make_app()
        api(app, "POST", "/api/todos", {"title": "A"})
        status, _, body = api(app, "PATCH", "/api/todos/1", {"done": True})
        self.assertEqual((status, json.loads(body)), (200, {"id": 1, "title": "A", "done": True}))
        self.assertEqual(api(app, "PATCH", "/api/todos/1", {"done": "yes"})[0], 422)
        self.assertEqual(api(app, "PATCH", "/api/todos/1", {})[0], 422)
        self.assertEqual(api(app, "PATCH", "/api/todos/1", raw=b"nope")[0], 400)
        self.assertEqual(api(app, "PATCH", "/api/todos/9", {"done": False})[0], 404)
        self.assertTrue(json.loads(api(app, "GET", "/api/todos")[2])[0]["done"])

    def test_delete_and_ids_are_not_reused(self):
        app = make_app()
        api(app, "POST", "/api/todos", {"title": "A"})
        api(app, "POST", "/api/todos", {"title": "B"})
        status, _, body = api(app, "DELETE", "/api/todos/2")
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(api(app, "DELETE", "/api/todos/2")[0], 404)
        self.assertEqual(json.loads(api(app, "POST", "/api/todos", {"title": "C"})[2])["id"], 3)
        self.assertEqual([t["id"] for t in json.loads(api(app, "GET", "/api/todos")[2])], [1, 3])

    def test_apps_do_not_share_state(self):
        first = make_app()
        api(first, "POST", "/api/todos", {"title": "A"})
        self.assertEqual(json.loads(api(make_app(), "GET", "/api/todos")[2]), [])


class Routing(unittest.TestCase):
    def test_unknown_paths_and_ids(self):
        app = make_app()
        for method, path in (("GET", "/nope"), ("GET", "/api/todos/1/extra"), ("DELETE", "/api/todos/abc"),
                             ("PATCH", "/api/todos/0")):
            with self.subTest(path=path):
                self.assertEqual(api(app, method, path, {"done": True} if method == "PATCH" else None)[0], 404)

    def test_wrong_methods_answer_405_with_allow(self):
        app = make_app()
        api(app, "POST", "/api/todos", {"title": "A"})
        cases = {("DELETE", "/"): {"GET"}, ("GET", "/todos"): {"POST"}, ("PUT", "/api/todos"): {"GET", "POST"},
                 ("POST", "/api/todos/1"): {"PATCH", "DELETE"}}
        for (method, path), allowed in cases.items():
            with self.subTest(method=method, path=path):
                status, headers, _ = call(app, method, path)
                self.assertEqual(status, 405)
                self.assertEqual({m.strip() for m in headers["allow"].split(",")}, allowed)


if __name__ == "__main__":
    unittest.main()
