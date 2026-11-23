import json
import threading
import unittest
import uuid

from app.database import init_and_seed_db
from app.main import dispatch_request


def api_call(method: str, path: str, headers: dict | None = None, json_body: dict | None = None) -> tuple[int, dict | list]:
    raw = json.dumps(json_body).encode("utf-8") if json_body is not None else b""
    status, payload, _ = dispatch_request(method, path, headers or {}, raw)
    return status, payload


class TestExpressYaHitosC1yC2(unittest.TestCase):
    def setUp(self):
        init_and_seed_db(reset=True)

    def test_01_c1_cinco_tiendas_y_reconstruccion_auditable(self):
        """C1 Punto 1 y 4: 5 Dark Stores cargadas, disponibilidad por tienda y cuadre E = SUM(delta_e)."""
        code, tiendas = api_call("GET", "/api/v1/tiendas")
        self.assertEqual(code, 200)
        self.assertEqual(len(tiendas), 5)

        code, disp = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-AGUA-01")
        self.assertEqual(disp["existencia_e"], 1)
        self.assertEqual(disp["disponible"], 1)

        code, cuadre = api_call("GET", "/api/v1/inventario/DS-NORTE/SKU-AGUA-01/reconstruir")
        self.assertTrue(cuadre["cuadre_auditable_exacto"])

    def test_02_at01_ultima_unidad_concurrencia_real(self):
        """AT-01 (Regla 4.2): 8 hilos concurrentes compiten al unísono por la última unidad (Agua E=1)."""
        num_hilos = 8
        barrera = threading.Barrier(num_hilos)
        codigos = []

        def intentar_reserva(idx: int):
            barrera.wait()  # Todos los hilos disparan en el mismo milisegundo
            st, _ = api_call(
                "POST",
                "/api/v1/orders/checkout",
                headers={"Idempotency-Key": f"K-AT01-{idx}-{uuid.uuid4()}"},
                json_body={
                    "cliente_id": f"CLI-{idx}",
                    "dark_store_id": "DS-NORTE",
                    "lineas": [{"sku_id": "SKU-AGUA-01", "cantidad": 1}],
                },
            )
            codigos.append(st)

        hilos = [threading.Thread(target=intentar_reserva, args=(i,)) for i in range(num_hilos)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        self.assertEqual(codigos.count(201), 1, f"Exactamente 1 debe ganar, resultados: {codigos}")
        self.assertEqual(codigos.count(409), num_hilos - 1)

        _, disp = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-AGUA-01")
        self.assertEqual(disp["disponible"], 0)
        self.assertEqual(disp["reservado_r_vigente"], 1)

        _, cuadre = api_call("GET", "/api/v1/inventario/DS-NORTE/SKU-AGUA-01/reconstruir")
        self.assertTrue(cuadre["cuadre_auditable_exacto"])

    def test_03_at02_reserva_valida_a_299s_y_expirada_a_300s(self):
        """AT-02: Reserva válida a los 299 s y expirada exactamente a los 300 s; sin compromiso posterior."""
        st, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-AT02-TEST"},
            json_body={"cliente_id": "CLI-02", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-CAFE-02", "cantidad": 2}]},
        )
        self.assertEqual(st, 201)

        # A los 299 segundos sigue válida (disponible = 5 - 2 = 3)
        _, d299 = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-CAFE-02&simulated_offset_sec=299")
        self.assertEqual(d299["disponible"], 3)
        self.assertEqual(d299["reservado_r_vigente"], 2)

        # A los 300 segundos exactos ya está expirada (disponible = 5)
        _, d300 = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-CAFE-02&simulated_offset_sec=300")
        self.assertEqual(d300["disponible"], 5)
        self.assertEqual(d300["reservado_r_vigente"], 0)

        # Intentar comprometer a los 300 s rechaza el compromiso
        _, w = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={"event_id": "EVT-AT02-300", "pedido_id": ped["pedido_id"], "tipo_evento": "PAGO_APROBADO", "simulated_offset_sec": 300},
        )
        self.assertEqual(w["resultado_inventario"], "RESERVA_EXPIRADA_PAGO_TARDIO")
        self.assertEqual(w["estado_pedido"], "CANCELADO")

    def test_04_at03_pago_rechazado_libera_inventario(self):
        """AT-03: Pago rechazado libera la reserva de inmediato sin retener inventario."""
        _, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-AT03-TEST"},
            json_body={"cliente_id": "CLI-03", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-LECHE-04", "cantidad": 3}]},
        )
        _, w = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={"event_id": "EVT-AT03-REJ", "pedido_id": ped["pedido_id"], "tipo_evento": "PAGO_RECHAZADO"},
        )
        self.assertEqual(w["estado_pedido"], "CANCELADO")
        _, disp = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-LECHE-04")
        self.assertEqual(disp["disponible"], 10)
        self.assertEqual(disp["reservado_r_vigente"], 0)

    def test_05_at04_pago_confirmado_despues_del_ttl_reembolsa_sin_revivir(self):
        """AT-04: Pago confirmado en t=305s no revive la reserva y genera reembolso simulado."""
        _, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-AT04-TEST"},
            json_body={"cliente_id": "CLI-04", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-PAN-05", "cantidad": 2}]},
        )
        _, w = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={"event_id": "EVT-AT04-LATE", "pedido_id": ped["pedido_id"], "tipo_evento": "PAGO_APROBADO", "simulated_offset_sec": 305},
        )
        self.assertEqual(w["resultado_inventario"], "RESERVA_EXPIRADA_PAGO_TARDIO")
        self.assertEqual(w["estado_reembolso_simulado"], "COMPLETADO")
        _, estado = api_call("GET", "/api/v1/admin/estado-sistema")
        self.assertEqual(len(estado["reembolsos"]), 1)
        self.assertEqual(estado["reembolsos"][0]["motivo_reembolso"], "PAGO_TARDIO_RESERVA_EXPIRADA")

    def test_06_at05_idempotencia_checkout_y_webhook_duplicado(self):
        """AT-05: Repetir checkout por timeout o enviar 2 veces el mismo webhook no duplica efectos."""
        body = {"cliente_id": "CLI-05", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-LECHE-04", "cantidad": 2}]}
        _, r1 = api_call("POST", "/api/v1/orders/checkout", headers={"Idempotency-Key": "K-IDEM-05"}, json_body=body)
        _, r2 = api_call("POST", "/api/v1/orders/checkout", headers={"Idempotency-Key": "K-IDEM-05"}, json_body=body)
        self.assertEqual(r1["pedido_id"], r2["pedido_id"])
        self.assertTrue(r2["idempotente_reutilizado"])

        _, w1 = api_call("POST", "/api/v1/payments/webhook", json_body={"event_id": "EVT-DUP-1", "pedido_id": r1["pedido_id"], "tipo_evento": "PAGO_APROBADO"})
        _, w2 = api_call("POST", "/api/v1/payments/webhook", json_body={"event_id": "EVT-DUP-1", "pedido_id": r1["pedido_id"], "tipo_evento": "PAGO_APROBADO"})
        self.assertFalse(w1["webhook_duplicado_ignorado"])
        self.assertTrue(w2["webhook_duplicado_ignorado"])

        _, disp = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-LECHE-04")
        self.assertEqual(disp["comprometido_c"], 2)

    def test_07_at06_timeout_financiero_estado_incierto(self):
        """AT-06: Timeout financiero deja el pago en RESULTADO_INCIERTO hasta conciliación."""
        _, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-AT06-TEST"},
            json_body={"cliente_id": "CLI-06", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-PAN-05", "cantidad": 1}]},
        )
        _, w = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={"event_id": "EVT-TO-06", "pedido_id": ped["pedido_id"], "tipo_evento": "TIMEOUT_INCIERTO"},
        )
        self.assertEqual(w["estado_pago"], "RESULTADO_INCIERTO")

    def test_08_at10_caida_logica_y_recuperacion_outbox_idempotente(self):
        """AT-10: Caída tras persistir cambio y antes de notificar: estado y evento recuperables sin duplicar."""
        _, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-AT10-TEST"},
            json_body={"cliente_id": "CLI-10", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-PAN-05", "cantidad": 1}]},
        )
        _, w = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={
                "event_id": "EVT-AT10-CRASH",
                "pedido_id": ped["pedido_id"],
                "tipo_evento": "PAGO_APROBADO",
                "simulated_offset_sec": 305,
                "simular_caida_antes_de_notificar": True,
            },
        )
        self.assertTrue(w["caida_simulada_at10"])
        self.assertEqual(w["estado_reembolso_simulado"], "PENDIENTE_EN_OUTBOX_POR_CAIDA_SIMULADA")

        _, estado_antes = api_call("GET", "/api/v1/admin/estado-sistema")
        pendientes = [e for e in estado_antes["evento_outbox"] if e["estado_outbox"] == "PENDIENTE"]
        self.assertGreaterEqual(len(pendientes), 1)
        self.assertEqual(len(estado_antes["reembolsos"]), 0)

        # Recuperar Outbox 2 veces seguidas para demostrar idempotencia (S2-02)
        _, rec1 = api_call("POST", "/api/v1/admin/recuperar-outbox")
        _, rec2 = api_call("POST", "/api/v1/admin/recuperar-outbox")
        self.assertGreaterEqual(rec1["eventos_outbox_procesados"], 1)
        self.assertEqual(rec2["eventos_outbox_procesados"], 0)

        _, estado_despues = api_call("GET", "/api/v1/admin/estado-sistema")
        self.assertEqual(len(estado_despues["reembolsos"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)