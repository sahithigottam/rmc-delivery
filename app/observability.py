"""Low-volume, stdout-only operational logging."""
import json
import logging
import re
import sys
from time import perf_counter
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger(__name__)
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
_TOKEN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_SECRET = re.compile(
    r"(?i)\b(authorization|bearer|api[_-]?key|password|secret|token)\b"
    r"[\s:=]+[^\s,;]+"
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = _URL.sub("[url omitted]", record.getMessage())
        message = _TOKEN.sub("[token omitted]", message)
        message = _SECRET.sub("[credential omitted]", message)
        result = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        request_id = request_id_context.get()
        if request_id:
            result["request_id"] = request_id
        for field in ("event", "method", "route", "status_code", "duration_ms",
                      "operation", "dependency_status"):
            if hasattr(record, field):
                result[field] = getattr(record, field)
        if record.exc_info:
            error_type, _, tb = record.exc_info
            result["error_type"] = error_type.__name__ if error_type else "Unknown"
            # Exception messages and source lines may contain URLs, secrets or user input.
            result["stack"] = [
                {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(tb)
            ]
        return json.dumps(result, ensure_ascii=True)


def configure_logging(level: str, *, production: bool = False) -> None:
    numeric_level = logging.getLevelNamesMapping().get(level.upper())
    if numeric_level is None:
        raise ValueError("LOG_LEVEL must be a valid logging level")
    if production:
        numeric_level = max(logging.INFO, numeric_level)
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_rmc_stdout", False):
            root.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)
    handler.setFormatter(JsonLogFormatter())
    handler._rmc_stdout = True
    root.addHandler(handler)
    root.setLevel(numeric_level)
    for name in ("httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    access.disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        server = logging.getLogger(name)
        server.handlers.clear()
        server.propagate = True


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp, slow_request_ms: int = 2000):
        self.app = app
        self.slow_request_ms = slow_request_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Generate our own ID: never log an untrusted incoming header.
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        context = request_id_context.set(request_id)
        started = perf_counter()
        status = 500
        streaming = False
        response_started = False

        def report() -> None:
            duration_ms = round((perf_counter() - started) * 1000)
            route = scope.get("route")
            path = getattr(route, "path", "<unmatched>")
            level = logging.ERROR if status >= 500 else logging.WARNING
            if status < 400 and duration_ms < self.slow_request_ms:
                level = logging.DEBUG
            logger.log(
                level, "http_request method=%s route=%s status=%s duration_ms=%s",
                scope["method"], path, status, duration_ms,
                extra={"event": "http_request", "method": scope["method"],
                       "route": path, "status_code": status, "duration_ms": duration_ms},
            )

        async def send_response(message: Message) -> None:
            nonlocal status, streaming, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                streaming = headers.get("content-type", "").startswith("text/event-stream")
                response_started = True
                if streaming:
                    report()
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception:
            status = 500
            logger.exception("http_request_failed method=%s route=%s response_started=%s",
                             scope["method"], getattr(scope.get("route"), "path", "<unmatched>"),
                             response_started)
            raise
        finally:
            if not streaming:
                report()
            request_id_context.reset(context)
