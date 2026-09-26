"""A tiny todo web app on the standard library's WSGI interface. Implement make_app().

make_app() returns a new WSGI application with its own empty in-memory store. Todo ids start at 1,
increase by one per created todo, and are never reused after a delete. Todos keep creation order.
A todo is {"id": int, "title": str, "done": bool}; titles are stripped and must be 1-100 characters.

Routes
- GET /             200 text/html; charset=utf-8. A full HTML document whose <title> is "Todos". It contains
                    <form method="post" action="/todos"> with <label for="title"> and
                    <input id="title" name="title" required maxlength="100">, and <ul id="todos"> with one
                    <li data-id="ID"> per todo holding its HTML-escaped title; a done todo's <li> has class="done".
- POST /todos       application/x-www-form-urlencoded field "title". Valid: create the todo and answer
                    303 with "Location: /". Invalid: 400 text/html page that contains the word "error".
- GET /api/todos    200 application/json list of todos.
- POST /api/todos   JSON body {"title": str}. 201 with the todo as JSON and "Location: /api/todos/ID".
                    Body that is not valid JSON or not an object: 400 {"error": message}.
                    Missing, non-string, blank or too long title: 422 {"error": message}.
- PATCH /api/todos/ID   JSON body {"done": bool}. 200 with the updated todo. Unknown id: 404.
                        Body not a JSON object: 400. Missing or non-bool "done": 422.
- DELETE /api/todos/ID  204 with an empty body. Unknown id: 404.

Every JSON response uses Content-Type "application/json" and every error body is {"error": message}.
A known path with an unsupported method answers 405 with an "Allow" header listing the supported
methods, comma-separated. Any other path answers 404.
"""


def make_app():
    raise NotImplementedError
