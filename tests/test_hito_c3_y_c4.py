import json
import unittest

from app.database import init_and_seed_db
from app.main import dispatch_request


def api_call(method: str, path: str, headers: dict | None = None, json_body: dict | None = None) -> tuple[int, dict | list]:
    raw = json.dumps(json_body).encode("utf-8") if json_body is not None else b""
    status, payload, _ = dispatch_request(method, path, headers or {}, raw)
    return status, payload


class TestExpressYaHitosC3yC4(unittest.TestCase):
    def setUp(self):
        init_and_seed_db(reset=True)

    def test_09_at07_discrepancia_10_vs_8_bloquea_disponibilidad(self):
        """AT-07 (S2-03): Existencia lógica 10, física 8 -> incidencia registrada y SKU bloqueado."""
        code, disp_antes = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-JUGO-03")
        self.assertEqual(code, 200)
        self.assertEqual(disp_antes["existencia_e"], 10)
        self.assertEqual(disp_antes["disponible"], 10)

        code, inc = api_call(
            "POST",
            "/api/v1/picking/discrepancia",
            json_body={
                "dark_store_id": "DS-NORTE",
                "sku_id": "SKU-JUGO-03",
                "conteo_fisico": 8,
                "picker_id": "PICKER-01",
                "motivo": "Conteo físico en anaquel 8 vs 10 lógico (AT-07)",
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(inc["existencia_logica"], 10)
        self.assertEqual(inc["conteo_fisico"], 8)
        self.assertEqual(inc["diferencia"], -2)
        self.assertEqual(inc["estado_sku_nuevo"], "INHABILITADO")
        self.assertEqual(inc["estado_incidencia"], "PENDIENTE_VERIFICACION_SUPERVISOR")

        _, disp_despues = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-JUGO-03")
        self.assertEqual(disp_despues["estado_sku"], "INHABILITADO")
        self.assertEqual(disp_despues["disponible"], 0)

        # Intentar comprar el SKU inhabilitado debe ser rechazado con 409 SKU_INHABILITADO
        st_compra, err = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-AT07-BLOQUEO"},
            json_body={
                "cliente_id": "CLI-AT07",
                "dark_store_id": "DS-NORTE",
                "lineas": [{"sku_id": "SKU-JUGO-03", "cantidad": 1}],
            },
        )
        self.assertEqual(st_compra, 409)
        self.assertEqual(err["error_code"], "SKU_INHABILITADO")

    def test_10_at08_pedido_5_lineas_una_faltante_continuan_4(self):
        """AT-08: Pedido pagado de 5 líneas con 1 no surtible -> 4 continúan y 1 se reembolsa."""
        lineas_5 = [
            {"sku_id": "SKU-AGUA-01", "cantidad": 1},
            {"sku_id": "SKU-CAFE-02", "cantidad": 1},
            {"sku_id": "SKU-JUGO-03", "cantidad": 1},
            {"sku_id": "SKU-LECHE-04", "cantidad": 1},
            {"sku_id": "SKU-PAN-05", "cantidad": 1},
        ]
        st, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-AT08-5LINEAS"},
            json_body={"cliente_id": "CLI-AT08", "dark_store_id": "DS-NORTE", "lineas": lineas_5},
        )
        self.assertEqual(st, 201)

        _, pago = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={"event_id": "EVT-AT08-PAY", "pedido_id": ped["pedido_id"], "tipo_evento": "PAGO_APROBADO"},
        )
        self.assertEqual(pago["estado_pedido"], "PAGADO")

        st_surt, surt = api_call(
            "POST",
            "/api/v1/picking/surtido-parcial",
            json_body={
                "pedido_id": ped["pedido_id"],
                "skus_faltantes": ["SKU-JUGO-03"],
                "picker_id": "PICKER-02",
                "motivo_faltante": "FALTANTE_FISICO_EN_PICKING",
            },
        )
        self.assertEqual(st_surt, 200)
        self.assertEqual(surt["estado_pedido"], "SURTIDO_PARCIAL")
        self.assertEqual(surt["total_lineas_surtidas"], 4)
        self.assertEqual(surt["total_lineas_canceladas"], 1)
        self.assertEqual(surt["monto_reembolso_confirmado"], 32.0)

    def test_11_at09_reembolso_parcial_repetido_una_sola_vez(self):
        """AT-09: Reembolso parcial repetido aplica el efecto económico simulado exactamente una vez."""
        _, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-AT09-REEMB"},
            json_body={
                "cliente_id": "CLI-AT09",
                "dark_store_id": "DS-NORTE",
                "lineas": [
                    {"sku_id": "SKU-JUGO-03", "cantidad": 1},
                    {"sku_id": "SKU-LECHE-04", "cantidad": 1},
                ],
            },
        )
        api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={"event_id": "EVT-AT09-PAY", "pedido_id": ped["pedido_id"], "tipo_evento": "PAGO_APROBADO"},
        )

        # Primer disparo de reembolso parcial por SKU-JUGO-03 ($32.00)
        st1, r1 = api_call(
            "POST",
            "/api/v1/payments/reembolso-parcial",
            json_body={"pedido_id": ped["pedido_id"], "sku_id": "SKU-JUGO-03", "monto": 32.0},
        )
        # Segundo disparo idéntico (reintento / doble clic)
        st2, r2 = api_call(
            "POST",
            "/api/v1/payments/reembolso-parcial",
            json_body={"pedido_id": ped["pedido_id"], "sku_id": "SKU-JUGO-03", "monto": 32.0},
        )
        self.assertEqual(st1, 200)
        self.assertEqual(st2, 200)
        self.assertFalse(r1["reembolso_duplicado_ignorado"])
        self.assertTrue(r2["reembolso_duplicado_ignorado"])
        self.assertEqual(r2["monto_reembolso_confirmado_en_pedido"], 32.0)

        _, estado = api_call("GET", "/api/v1/admin/estado-sistema")
        self.assertEqual(len(estado["reembolsos"]), 1)

    def test_12_c3_historial_auditoria_quien_cuando_porque_impacto(self):
        """C3 Punto 4: Consultar historial completo (quién, qué, cuándo, por qué y cómo impactó)."""
        _, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-C3-AUD"},
            json_body={
                "cliente_id": "CLI-AUD",
                "dark_store_id": "DS-NORTE",
                "lineas": [
                    {"sku_id": "SKU-JUGO-03", "cantidad": 1},
                    {"sku_id": "SKU-PAN-05", "cantidad": 1},
                ],
            },
        )
        api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={"event_id": "EVT-C3-AUD", "pedido_id": ped["pedido_id"], "tipo_evento": "PAGO_APROBADO"},
        )
        api_call(
            "POST",
            "/api/v1/picking/surtido-parcial",
            json_body={"pedido_id": ped["pedido_id"], "skus_faltantes": ["SKU-JUGO-03"], "picker_id": "PICKER-AUD"},
        )

        st, hist = api_call("GET", f"/api/v1/auditoria/historial?pedido_id={ped['pedido_id']}")
        self.assertEqual(st, 200)
        self.assertGreaterEqual(hist["total_movimientos"], 4)
        tipos = {m["que_cambio"] for m in hist["movimientos_auditables"]}
        self.assertIn("RESERVA", tipos)
        self.assertIn("COMPROMISO", tipos)
        self.assertIn("SALIDA_PICKING", tipos)
        self.assertIn("RECORTE_COMPROMISO", tipos)
        self.assertEqual(hist["detalle_pedido"]["pedido"]["estado_pedido"], "SURTIDO_PARCIAL")

    def test_13_c4_flujo_completo_compra_normal_extremo_a_extremo(self):
        """C4 Punto 1: Flujo de compra normal extremo a extremo (checkout -> pago -> surtido completo -> cuadre)."""
        st, ped = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-C4-NORMAL"},
            json_body={"cliente_id": "CLI-C4", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-CAFE-02", "cantidad": 2}]},
        )
        self.assertEqual(st, 201)

        _, pago = api_call(
            "POST",
            "/api/v1/payments/webhook",
            json_body={"event_id": "EVT-C4-NORMAL", "pedido_id": ped["pedido_id"], "tipo_evento": "PAGO_APROBADO"},
        )
        self.assertEqual(pago["estado_pedido"], "PAGADO")

        _, surt = api_call(
            "POST",
            "/api/v1/picking/surtido-parcial",
            json_body={"pedido_id": ped["pedido_id"], "skus_faltantes": [], "picker_id": "PICKER-OK"},
        )
        self.assertEqual(surt["estado_pedido"], "SURTIDO_COMPLETO")

        _, cuadre = api_call("GET", "/api/v1/inventario/DS-NORTE/SKU-CAFE-02/reconstruir")
        self.assertTrue(cuadre["cuadre_auditable_exacto"])
        self.assertEqual(cuadre["existencia_e_tabla"], 3)

    def test_14_c4_regresion_idempotencia_clave_reutilizada_422(self):
        """C4 Regresión: Reutilizar Idempotency-Key con distinto carrito debe devolver 422 CLAVE_REUTILIZADA."""
        st1, _ = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-REUTILIZADA-422"},
            json_body={"cliente_id": "CLI-14", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-LECHE-04", "cantidad": 1}]},
        )
        self.assertEqual(st1, 201)

        st2, err = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-REUTILIZADA-422"},
            json_body={"cliente_id": "CLI-14", "dark_store_id": "DS-NORTE", "lineas": [{"sku_id": "SKU-PAN-05", "cantidad": 2}]},
        )
        self.assertEqual(st2, 422)
        self.assertEqual(err["error_code"], "CLAVE_REUTILIZADA")

    def test_15_c4_regresion_carrito_multilinea_rollback_atomico(self):
        """C4 Regresión: Si una línea de un carrito no tiene stock, toda la transacción hace ROLLBACK."""
        st, err = api_call(
            "POST",
            "/api/v1/orders/checkout",
            headers={"Idempotency-Key": "K-ROLLBACK-15"},
            json_body={
                "cliente_id": "CLI-15",
                "dark_store_id": "DS-NORTE",
                "lineas": [
                    {"sku_id": "SKU-LECHE-04", "cantidad": 2},
                    {"sku_id": "SKU-AGUA-01", "cantidad": 5},  # Solo hay 1 -> debe abortar todo
                ],
            },
        )
        self.assertEqual(st, 409)
        self.assertEqual(err["error_code"], "SIN_STOCK")

        # Verificar que SKU-LECHE-04 no quedó reservado parcialmente
        _, disp = api_call("GET", "/api/v1/tiendas/DS-NORTE/disponibilidad?sku_id=SKU-LECHE-04")
        self.assertEqual(disp["reservado_r_vigente"], 0)
        self.assertEqual(disp["disponible"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)