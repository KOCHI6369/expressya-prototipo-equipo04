import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import uuid

from app.database import DomainHttpError, atomic_transaction, get_connection, init_and_seed_db
from app.services import (
    _now,
    consultar_disponibilidad_tienda,
    crear_checkout_y_reserva,
    procesar_outbox_pendientes_conn,
    procesar_webhook_pasarela_simulada,
    reconstruir_saldo_auditable,
)

STATIC_INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


def dispatch_request(method: str, path_with_query: str, headers: dict, body_bytes: bytes = b"") -> tuple[int, dict | list | str, str]:
    """Despachador HTTP central usable tanto por ThreadingHTTPServer como por las pruebas automatizadas."""
    parsed = urlparse(path_with_query)
    path = parsed.path
    query = parse_qs(parsed.query)

    norm_headers = {k.lower(): v for k, v in (headers or {}).items()}
    body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

    try:
        if method == "GET" and path == "/":
            return 200, STATIC_INDEX.read_text(encoding="utf-8"), "text/html; charset=utf-8"

        if method == "POST" and path == "/api/v1/admin/reset-seed":
            init_and_seed_db(reset=True)
            return 200, {"status": "OK", "mensaje": "Base de datos reiniciada con las 5 Dark Stores y productos semilla."}, "application/json"

        if method == "GET" and path == "/api/v1/tiendas":
            conn = get_connection()
            try:
                rows = conn.execute("SELECT * FROM dark_store ORDER BY codigo_tienda ASC").fetchall()
                return 200, [dict(r) for r in rows], "application/json"
            finally:
                conn.close()

        if method == "GET" and path.startswith("/api/v1/tiendas/") and path.endswith("/disponibilidad"):
            parts = path.strip("/").split("/")
            store_id = parts[3]
            sku_id = query.get("sku_id", [None])[0]
            offset = float(query.get("simulated_offset_sec", [0.0])[0])
            items = consultar_disponibilidad_tienda(store_id, sku_id, offset)
            return 200, (items[0] if (sku_id and items) else items), "application/json"

        if method == "GET" and path.startswith("/api/v1/inventario/") and path.endswith("/reconstruir"):
            parts = path.strip("/").split("/")
            store_id = parts[3]
            sku_id = parts[4]
            return 200, reconstruir_saldo_auditable(store_id, sku_id), "application/json"

        if method == "POST" and path == "/api/v1/orders/checkout":
            idem_key = norm_headers.get("idempotency-key", "")
            corr_id = norm_headers.get("x-correlation-id") or f"CORR-{uuid.uuid4()}"
            code, resp = crear_checkout_y_reserva(
                idempotency_key=idem_key,
                correlation_id=corr_id,
                cliente_id=body.get("cliente_id", "CLI-DEMO-01"),
                dark_store_id=body.get("dark_store_id", "DS-NORTE"),
                lineas=body.get("lineas", []),
            )
            return code, resp, "application/json"

        if method == "POST" and path == "/api/v1/payments/webhook":
            resp = procesar_webhook_pasarela_simulada(
                event_id=body["event_id"],
                pedido_id=body["pedido_id"],
                modo_resultado=body.get("tipo_evento", "PAGO_APROBADO"),
                simulated_offset_sec=float(body.get("simulated_offset_sec", 0.0)),
                simular_caida_antes_de_notificar=bool(body.get("simular_caida_antes_de_notificar", False)),
            )
            return 200, resp, "application/json"

        if method == "POST" and path == "/api/v1/admin/recuperar-outbox":
            with atomic_transaction() as conn:
                procesados = procesar_outbox_pendientes_conn(conn, _now(0.0))
                return 200, {"status": "RECUPERADO", "eventos_outbox_procesados": procesados}, "application/json"

        if method == "GET" and path == "/api/v1/admin/estado-sistema":
            conn = get_connection()
            try:
                return 200, {
                    "pedidos": [dict(r) for r in conn.execute("SELECT * FROM pedido ORDER BY creado_epoch DESC LIMIT 20").fetchall()],
                    "reservas": [dict(r) for r in conn.execute("SELECT * FROM reserva_inventario ORDER BY creada_epoch DESC LIMIT 20").fetchall()],
                    "pagos": [dict(r) for r in conn.execute("SELECT * FROM transaccion_pago ORDER BY creada_epoch DESC LIMIT 20").fetchall()],
                    "reembolsos": [dict(r) for r in conn.execute("SELECT * FROM obligacion_reembolso ORDER BY creado_epoch DESC LIMIT 20").fetchall()],
                    "evento_outbox": [dict(r) for r in conn.execute("SELECT * FROM evento_outbox ORDER BY creado_epoch DESC LIMIT 20").fetchall()],
                    "evento_consumido": [dict(r) for r in conn.execute("SELECT * FROM evento_consumido ORDER BY procesado_epoch DESC LIMIT 20").fetchall()],
                }, "application/json"
            finally:
                conn.close()

        return 404, {"error_code": "NOT_FOUND", "detail": f"Ruta no encontrada: {method} {path}"}, "application/json"

    except DomainHttpError as e:
        return e.status_code, {"error_code": e.error_code, "detail": e.detail}, "application/json"


class ExpressYaRequestHandler(BaseHTTPRequestHandler):
    def _handle(self, method: str):
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length) if length > 0 else b""
        status, payload, content_type = dispatch_request(method, self.path, dict(self.headers), body_bytes)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if isinstance(payload, str):
            self.wfile.write(payload.encode("utf-8"))
        else:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def log_message(self, format, *args):
        pass


def run_server(port: int = 8000):
    init_and_seed_db(reset=False)
    server = ThreadingHTTPServer(("0.0.0.0", port), ExpressYaRequestHandler)
    print("======================================================================")
    print(f" Servidor ExpressYa (Hitos C1 y C2) activo en: http://localhost:{port}")
    print(" Presiona Ctrl+C para detener el servidor.")
    print("======================================================================")
    server.serve_forever()


if __name__ == "__main__":
    run_server(8000)
    