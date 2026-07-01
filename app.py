"""Toy FastAPI service for the Module 11 Core Skills Drill.

Two endpoints (POST /echo, GET /sum) on an in-memory app. Your job:

  1. Declare three Prometheus metrics at module scope (requests_total,
     request_latency_seconds, inflight_requests).
  2. Implement three ASGI middlewares (RequestId, StructuredLogging, Metrics)
     and add them to the app in the correct order.
  3. Mount /metrics via prometheus_client.make_asgi_app().

The published Drill page is the canonical task list. The autograder verifies
the metrics surface, header behavior, and a JSON log line is emitted.
"""

import contextvars
import json
import logging
import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from starlette.middleware.base import BaseHTTPMiddleware


requests_total = Counter(
    "requests_total",
    "Total HTTP requests",
    ["path", "status"],
)
request_latency_seconds = Histogram(
    "request_latency_seconds",
    "Request latency in seconds",
    ["path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)
inflight_requests = Gauge("inflight_requests", "In-flight requests")

request_id_var = contextvars.ContextVar("request_id", default="")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - started) * 1000
        logging.getLogger("app").info(
            json.dumps(
                {
                    "ts": time.time(),
                    "level": "INFO",
                    "request_id": request_id_var.get(),
                    "path": request.url.path,
                    "status": response.status_code,
                    "latency_ms": latency_ms,
                }
            )
        )
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/metrics"):
            return await call_next(request)

        inflight_requests.inc()
        started = time.perf_counter()
        try:
            response = await call_next(request)
            elapsed = time.perf_counter() - started
            requests_total.labels(
                path=request.url.path,
                status=str(response.status_code),
            ).inc()
            request_latency_seconds.labels(path=request.url.path).observe(elapsed)
            return response
        finally:
            inflight_requests.dec()


class EchoRequest(BaseModel):
    message: str


app = FastAPI(title="M11 Drill — Toy FastAPI Service")


app.add_middleware(MetricsMiddleware)
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(RequestIdMiddleware)


app.mount("/metrics", make_asgi_app())


# ---------------------------------------------------------------------------
# Endpoints (do not modify — these are what the autograder hits with traffic).
# ---------------------------------------------------------------------------


@app.post("/echo")
def echo(req: EchoRequest):
    return {"echo": req.message}


@app.get("/sum")
def sum_endpoint(a: int = 0, b: int = 0):
    return {"sum": a + b}
