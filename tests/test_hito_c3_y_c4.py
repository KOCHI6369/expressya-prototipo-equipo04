import json
import unittest
import uuid

from app.database import init_and_seed_db
from app.main import dispatch_request


def api_call(
    method: str,
    path: str,
    headers: dict | None = None,
    json_body: dict | None = None,
) -> tuple[int, dict | list]:
    raw = json.dumps(json_body).encode("utf-8") if json_body is not None else b""
    status, payload, _ = dispatch_request(method, path, headers or {}, raw)
    return status, payload


class TestExpressYaHitosC3yC4(unittest.TestCase):
    def setUp(self):
        init_and_seed_db(reset=True)

    def test_09_at07_discrepancia_10_vs_8_bloquea_disponibilidad(self):
        """AT-07: SKU-JUGO-03 pasa a INHABILITADO tras discrepancia 10 vs 8 y bloquea compra con 409."""
        code, resp = api_call(
            "POST",
            "/api/v1/picking/discrepancia",
            json_body={
                "dark_store_id": "DS-NORTE",
                "sku_id": "SKU-JUGO-03",
                "conteo_fisico": 8,
                "picker_id": "PICKER-01",
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(resp.get("estado_sku_nuevo"), "INHABILITADO")
        self.assertEqual(resp.get("disponible_para_venta"), 0)

        code_buy, resp_buy = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": f"K-AT09-{uuid.uuid4()}"},
            json_body={
                "cliente_id": "CLI-09",
                "dark_store_id": "DS-NORTE",
                "lineas": [{"sku_id": "SKU-JUGO-03", "cantidad": 1}],
            },
        )
        self.assertEqual(code_buy, 409)
        if isinstance(resp_buy, dict) and "codigo_error" in resp_buy:
            self.assertEqual(resp_buy["codigo_error"], "SKU_INHABILITADO")

    def test_10_at08_pedido_5_lineas_una_faltante_continuan_4(self):
        """AT-08: Pedido pagado de 5 líneas con 1 faltante deja 4 surtidas, 1 cancelada y estado SURTIDO_PARCIAL."""
        skus_5 = [
            {"sku_id": "SKU-AGUA-01", "cantidad": 1},
            {"sku_id": "SKU-CAFE-02", "cantidad": 1},
            {"sku_id": "SKU-JUGO-03", "cantidad": 1},
            {"sku_id": "SKU-LECHE-04", "cantidad": 1},
            {"sku_id": "SKU-PAN-05", "cantidad": 1},
        ]
        st_chk, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": f"K-AT10-CHK-{uuid.uuid4()}"},
            json_body={
                "cliente_id": "CLI-10",
                "dark_store_id": "DS-NORTE",
                "lineas": skus_5,
            },
        )
        self.assertEqual(st_chk, 201)
        pedido_id = ped["pedido_id"]

        st_pay, _ = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={
                "event_id": f"EVT-AT10-{uuid.uuid4()}",
                "pedido_id": pedido_id,
                "tipo_evento": "PAGO_APROBADO",
            },
        )
        self.assertEqual(st_pay, 200)

        st_pick, res = api_call(
            "POST",
            "/api/v1/picking/surtido-parcial",
            json_body={
                "pedido_id": pedido_id,
                "skus_faltantes": ["SKU-JUGO-03"],
                "picker_id": "PICKER-01",
            },
        )
        self.assertEqual(st_pick, 200)
        self.assertEqual(res.get("estado_pedido"), "SURTIDO_PARCIAL")
        self.assertEqual(res.get("total_lineas_surtidas"), 4)
        self.assertEqual(res.get("total_lineas_canceladas"), 1)

    def test_11_at09_reembolso_parcial_repetido_una_sola_vez(self):
        """AT-09: Reembolso parcial repetido 2 veces se aplica una sola vez sin duplicar el monto."""
        st_chk, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": f"K-AT11-CHK-{uuid.uuid4()}"},
            json_body={
                "cliente_id": "CLI-11",
                "dark_store_id": "DS-NORTE",
                "lineas": [
                    {"sku_id": "SKU-JUGO-03", "cantidad": 1},
                    {"sku_id": "SKU-PAN-05", "cantidad": 1},
                ],
            },
        )
        self.assertEqual(st_chk, 201)
        pedido_id = ped["pedido_id"]

        api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={
                "event_id": f"EVT-AT11-{uuid.uuid4()}",
                "pedido_id": pedido_id,
                "tipo_evento": "PAGO_APROBADO",
            },
        )
        api_call(
            "POST",
            "/api/v1/picking/surtido-parcial",
            json_body={
                "pedido_id": pedido_id,
                "skus_faltantes": ["SKU-JUGO-03"],
                "picker_id": "PICKER-01",
            },
        )

        body_remb = {
            "pedido_id": pedido_id,
            "sku_id": "SKU-JUGO-03",
            "monto": 32.0,
            "motivo": "FALTANTE_FISICO_EN_PICKING",
        }
        st_r1, r1 = api_call("POST", "/api/v1/payments/reembolso-parcial", json_body=body_remb)
        st_r2, r2 = api_call("POST", "/api/v1/payments/reembolso-parcial", json_body=body_remb)

        self.assertEqual(st_r1, 200)
        self.assertEqual(st_r2, 200)
        self.assertFalse(r1.get("reembolso_duplicado_ignorado"))
        self.assertTrue(r2.get("reembolso_duplicado_ignorado"))
        self.assertEqual(
            r1.get("monto_reembolso_confirmado_en_pedido"),
            r2.get("monto_reembolso_confirmado_en_pedido"),
        )

    def test_12_c3_historial_auditoria_quien_cuando_porque_impacto(self):
        """C3 Punto 4: Historial de auditoría devuelve quién, qué, cuándo, por qué e impacto en el pedido."""
        st_chk, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": f"K-AT12-CHK-{uuid.uuid4()}"},
            json_body={
                "cliente_id": "CLI-12",
                "dark_store_id": "DS-NORTE",
                "lineas": [
                    {"sku_id": "SKU-JUGO-03", "cantidad": 1},
                    {"sku_id": "SKU-PAN-05", "cantidad": 1},
                ],
            },
        )
        self.assertEqual(st_chk, 201)
        pedido_id = ped["pedido_id"]

        api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={
                "event_id": f"EVT-AT12-{uuid.uuid4()}",
                "pedido_id": pedido_id,
                "tipo_evento": "PAGO_APROBADO",
            },
        )
        api_call(
            "POST",
            "/api/v1/picking/surtido-parcial",
            json_body={
                "pedido_id": pedido_id,
                "skus_faltantes": ["SKU-JUGO-03"],
                "picker_id": "PICKER-01",
            },
        )

        st_aud, aud = api_call("GET", f"/api/v1/auditoria/historial?pedido_id={pedido_id}")
        self.assertEqual(st_aud, 200)
        movs = aud.get("movimientos_auditables", [])
        self.assertGreater(len(movs), 0)
        for mov in movs:
            self.assertIn("quien", mov)
            self.assertIn("que_cambio", mov)
            self.assertIn("cuando_epoch", mov)
            self.assertIn("porque", mov)
            self.assertIn("impacto_en_pedido", mov)

    def test_13_c4_flujo_completo_compra_normal_extremo_a_extremo(self):
        """C4: Compra normal de principio a fin (201 -> PAGADO -> SURTIDO_COMPLETO -> cuadre auditable)."""
        st_chk, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": f"K-AT13-CHK-{uuid.uuid4()}"},
            json_body={
                "cliente_id": "CLI-13",
                "dark_store_id": "DS-NORTE",
                "lineas": [{"sku_id": "SKU-PAN-05", "cantidad": 2}],
            },
        )
        self.assertEqual(st_chk, 201)
        pedido_id = ped["pedido_id"]

        st_pay, _ = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={
                "event_id": f"EVT-AT13-{uuid.uuid4()}",
                "pedido_id": pedido_id,
                "tipo_evento": "PAGO_APROBADO",
            },
        )
        self.assertEqual(st_pay, 200)

        st_pick, res = api_call(
            "POST",
            "/api/v1/picking/surtido-parcial",
            json_body={
                "pedido_id": pedido_id,
                "skus_faltantes": [],
                "picker_id": "PICKER-01",
            },
        )
        self.assertEqual(st_pick, 200)
        self.assertEqual(res.get("estado_pedido"), "SURTIDO_COMPLETO")

        st_cuadre, cuadre = api_call("GET", "/api/v1/inventario/DS-NORTE/SKU-PAN-05/reconstruir")
        self.assertEqual(st_cuadre, 200)
        self.assertTrue(cuadre.get("cuadre_auditable_exacto"))

    def test_14_c4_regresion_idempotencia_clave_reutilizada_422(self):
        """C4 Regresión: Reutilizar la misma Idempotency-Key con un carrito distinto debe rechazar con 422."""
        clave = f"K-AT14-{uuid.uuid4()}"
        st1, _ = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": clave},
            json_body={
                "cliente_id": "CLI-14",
                "dark_store_id": "DS-NORTE",
                "lineas": [{"sku_id": "SKU-PAN-05", "cantidad": 1}],
            },
        )
        self.assertEqual(st1, 201)

        st2, resp2 = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": clave},
            json_body={
                "cliente_id": "CLI-14",
                "dark_store_id": "DS-NORTE",
                "lineas": [{"sku_id": "SKU-LECHE-04", "cantidad": 2}],
            },
        )
        self.assertEqual(st2, 422)
        if isinstance(resp2, dict) and "codigo_error" in resp2:
            self.assertEqual(resp2["codigo_error"], "CLAVE_REUTILIZADA")

    def test_15_c4_regresion_multiples_skus_sin_saldo_negativo(self):
        """C4 Regresión: Carrito multi-SKU donde uno excede stock hace ROLLBACK completo sin dejar reservas."""
        st_bad, _ = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": f"K-AT15-{uuid.uuid4()}"},
            json_body={
                "cliente_id": "CLI-15",
                "dark_store_id": "DS-NORTE",
                "lineas": [
                    {"sku_id": "SKU-PAN-05", "cantidad": 1},
                    {"sku_id": "SKU-AGUA-01", "cantidad": 999},
                ],
            },
        )
        self.assertNotEqual(st_bad, 201)

        _, disp_pan = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-PAN-05")
        self.assertEqual(disp_pan.get("reservado_r_vigente"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
