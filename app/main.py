"""Demo didáctica de monitoreo de aplicaciones: MonitorLab.

Los fallos y la latencia se INYECTAN explícitamente en modo demo;
no hay conexiones con datos ni servicios reales.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("monitorlab")

app = FastAPI(title="MonitorLab | Observabilidad y Monitoreo de Aplicaciones", version="1.0.0")

REQUESTS = Counter(
    "monitorlab_http_requests_total",
    "Solicitudes HTTP recibidas, etiquetadas por metodo, ruta y estado.",
    ["method", "route", "status"],
)
DURATION = Histogram(
    "monitorlab_http_request_duration_seconds",
    "Duracion observada de las solicitudes HTTP en segundos.",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
)


def record_log(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False))


@app.middleware("http")
async def instrument(request: Request, call_next):
    # /metrics y /health se excluyen para no confundir el tráfico real con el scraping.
    if request.url.path in ("/metrics", "/health"):
        return await call_next(request)

    started = time.perf_counter()
    request_id = str(uuid4())[:8]
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration = time.perf_counter() - started
        # El patrón de ruta (no el ID concreto) evita etiquetas de alta cardinalidad.
        route_obj = request.scope.get("route")
        route = getattr(route_obj, "path", request.url.path)
        REQUESTS.labels(request.method, route, str(status)).inc()
        DURATION.labels(request.method, route).observe(duration)
        record_log(
            "http_request", request_id=request_id, method=request.method,
            route=route, status=status, duration_ms=round(duration * 1000, 2),
        )


@app.get("/", response_class=HTMLResponse)
def home():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@app.get("/api/operaciones/{operacion_id}")
def consultar_operacion(operacion_id: int, modo: str = "normal"):
    if modo not in ("normal", "lento", "error"):
        raise HTTPException(status_code=400, detail="modo debe ser normal, lento o error")
    if modo == "lento":
        time.sleep(3)  # Latencia simulada solo con fines docentes.
    if modo == "error":
        record_log("operacion_error_simulado", operacion_id=operacion_id)
        raise HTTPException(status_code=500, detail="Falla simulada al consultar operacion")
    return {"id": operacion_id, "tipo": "consulta", "estado": "completada"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
