"""
FinGroww SaaS Platform — Lightweight Zero-Dependency ASGI-to-WSGI Bridge.
Allows FastAPI to serve all existing Flask routes and static pages seamlessly during migration.
"""

import io
from typing import Callable
from anyio.to_thread import run_sync


class WSGIToASGI:
    """Wraps a synchronous WSGI callable (Flask app) inside an ASGI 3.0 interface."""

    def __init__(self, wsgi_app: Callable):
        self.wsgi_app = wsgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return

        # Read entire request body from ASGI receive
        body_chunks = []
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break
        body = b"".join(body_chunks)

        # Build WSGI environ
        headers = scope.get("headers", [])
        server = scope.get("server") or ("127.0.0.1", 80)
        client = scope.get("client") or ("127.0.0.1", 0)

        environ = {
            "REQUEST_METHOD": scope["method"],
            "SCRIPT_NAME": scope.get("root_path", ""),
            "PATH_INFO": scope["path"],
            "QUERY_STRING": scope.get("query_string", b"").decode("latin1"),
            "SERVER_NAME": server[0],
            "SERVER_PORT": str(server[1]),
            "REMOTE_ADDR": client[0],
            "REMOTE_PORT": str(client[1]),
            "SERVER_PROTOCOL": f"HTTP/{scope.get('http_version', '1.1')}",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": scope.get("scheme", "http"),
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
            "CONTENT_LENGTH": str(len(body)),
        }

        for raw_name, raw_val in headers:
            name = raw_name.decode("latin1").upper().replace("-", "_")
            val = raw_val.decode("latin1")
            if name == "CONTENT_TYPE":
                environ["CONTENT_TYPE"] = val
            elif name == "CONTENT_LENGTH":
                environ["CONTENT_LENGTH"] = val
            else:
                http_key = f"HTTP_{name}"
                if http_key in environ:
                    environ[http_key] = f"{environ[http_key]},{val}"
                else:
                    environ[http_key] = val

        status_holder = []
        headers_holder = []

        def start_response(status_str, response_headers, exc_info=None):
            status_code = int(status_str.split(" ", 1)[0])
            status_holder.append(status_code)
            raw_headers = [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in response_headers]
            headers_holder.append(raw_headers)

        def _invoke_wsgi():
            chunks = []
            result = self.wsgi_app(environ, start_response)
            try:
                for chunk in result:
                    if chunk:
                        chunks.append(chunk)
            finally:
                if hasattr(result, "close"):
                    result.close()
            return b"".join(chunks)

        response_body = await run_sync(_invoke_wsgi)
        status_code = status_holder[0] if status_holder else 500
        response_headers = headers_holder[0] if headers_holder else []

        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": response_headers,
        })
        await send({
            "type": "http.response.body",
            "body": response_body,
        })
