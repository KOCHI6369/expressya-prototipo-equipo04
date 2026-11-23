import hashlib
import json
import time
import uuid
from app.database import DomainHttpError, atomic_transaction, get_connection

TTL_SECONDS = 300.0  # 5 minutos estrictos confirmados por el cliente (RN-03, S2-01, AT-02)


def _now(offset_sec: float = 0.0) -> float:
    return round(time.time() + float(offset_sec), 3)


def expirar_reservas_vencidas_conn(conn, eval_epoch: float) -> list[str]:
    """
    Expira todas las reservas donde eval_epoch >= expira_epoch (S2-01, AT-02: a los 300.000s YA está expirada).
    Libera reservado_r en inventario_tienda, registra movimiento LIBERACION y escribe EVT-01 en evento_outbox.
    """
    vencidas = conn.execute(
        """
        SELECT reserva_id, inventario_id, pedido_id, sku_id, cantidad_reservada
          FROM reserva_inventario
         WHERE estado_reserva IN ('ACTIVA', 'EN_PAGO')
           AND ? >= expira_epoch
        """,
        (eval_epoch,),
    ).fetchall()

    expiradas_ids = []
    for r in vencidas:
        conn.execute(
            """
            UPDATE reserva_inventario
               SET estado_reserva = 'EXPIRADA', motivo_liberacion = 'TTL_VENCIDO',
                   cerrada_epoch = ?, version_cas = version_cas + 1
             WHERE reserva_id = ? AND estado_reserva IN ('ACTIVA', 'EN_PAGO')
            """,
            (eval_epoch, r["reserva_id"]),
        )
        conn.execute(
            """
            UPDATE inventario_tienda
               SET reservado_r = reservado_r - ?, version_concurrency = version_concurrency + 1
             WHERE inventario_id = ?
            """,
            (r["cantidad_reservada"], r["inventario_id"]),
        )
        conn.execute(
            """
            INSERT INTO movimiento_inventario
                (movimiento_id, inventario_id, usuario_id, tipo_movimiento, delta_e, delta_r, delta_c, delta_h,
                 pedido_id, reserva_id, correlation_id, motivo_detalle, registrado_epoch)
            VALUES (?, ?, 'JOB-EXPIRACION', 'LIBERACION', 0, ?, 0, 0, ?, ?, 'TTL-300S', 'Expiración estricta a 300 s', ?)
            """,
            (str(uuid.uuid4()), r["inventario_id"], -r["cantidad_reservada"], r["pedido_id"], r["reserva_id"], eval_epoch),
        )
        evt_id = f"EVT-EXP-{r['reserva_id']}"
        payload = json.dumps({"reserva_id": r["reserva_id"], "pedido_id": r["pedido_id"], "expirada_epoch": eval_epoch})
        conn.execute(
            """
            INSERT OR IGNORE INTO evento_outbox
                (evento_id, agregado_id, tipo_evento, payload_json, correlation_id, estado_outbox, creado_epoch)
            VALUES (?, ?, 'EVT-01_ReservaExpirada', ?, 'TTL-300S', 'PENDIENTE', ?)
            """,
            (evt_id, r["pedido_id"], payload, eval_epoch),
        )
        expiradas_ids.append(r["reserva_id"])

    return expiradas_ids


def procesar_outbox_pendientes_conn(conn, eval_epoch: float) -> int:
    """
    Daemon / Consumidor Idempotente de Outbox (S2-02, AT-10):
    Lee eventos PENDIENTE y los aplica en COMP-ORD y COMP-PAY usando evento_consumido
    para garantizar que jamás se aplique ni compense dos veces el mismo evento.
    """
    pendientes = conn.execute(
        "SELECT * FROM evento_outbox WHERE estado_outbox = 'PENDIENTE' ORDER BY creado_epoch ASC"
    ).fetchall()
    procesados = 0
    for ev in pendientes:
        evt_id = ev["evento_id"]
        tipo = ev["tipo_evento"]
        data = json.loads(ev["payload_json"])

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO evento_consumido (evento_id, modulo_consumidor, tipo_evento, procesado_epoch)
            VALUES (?, 'COMP-ORD-PAY', ?, ?)
            """,
            (evt_id, tipo, eval_epoch),
        )
        if cur.rowcount == 1:
            if tipo == "EVT-01_ReservaExpirada":
                ped_id = data["pedido_id"]
                conn.execute(
                    "UPDATE pedido SET estado_pedido = 'CANCELADO' WHERE pedido_id = ? AND estado_pedido = 'PENDIENTE_PAGO'",
                    (ped_id,),
                )
                conn.execute(
                    "UPDATE transaccion_pago SET estado_pago = 'ANULADO_VOID' WHERE pedido_id = ? AND estado_pago = 'PENDIENTE_RESPUESTA'",
                    (ped_id,),
                )
            elif tipo == "EVT-05_ReembolsoSolicitado":
                ped_id = data["pedido_id"]
                monto = data["monto"]
                motivo = data["motivo"]
                scope = data.get("linea_scope_key", "TOTAL")
                conn.execute(
                    """
                    INSERT OR IGNORE INTO obligacion_reembolso
                        (reembolso_id, pedido_id, linea_scope_key, monto_a_reembolsar, motivo_reembolso,
                         estado_reembolso, idempotency_key_reembolso, creado_epoch)
                    VALUES (?, ?, ?, ?, ?, 'COMPLETADO', ?, ?)
                    """,
                    (str(uuid.uuid4()), ped_id, scope, monto, motivo, f"REF-{ped_id}-{scope}-{motivo}", eval_epoch),
                )
                conn.execute(
                    "UPDATE pedido SET monto_reembolso_confirmado = monto_reembolso_obligado WHERE pedido_id = ?",
                    (ped_id,),
                )

        conn.execute(
            "UPDATE evento_outbox SET estado_outbox = 'PUBLICADO', publicado_epoch = ? WHERE evento_id = ?",
            (eval_epoch, evt_id),
        )
        procesados += 1
    return procesados


def consultar_disponibilidad_tienda(dark_store_id: str, sku_id: str | None = None, simulated_offset_sec: float = 0.0) -> list[dict]:
    """
    C1 Punto 1 y AT-02: Calcula disponibilidad por tienda aplicando evaluación perezosa:
    cualquier reserva con eval_epoch >= expira_epoch (t >= 300.000 s) ya NO cuenta como reservada.
    """
    eval_epoch = _now(simulated_offset_sec)
    conn = get_connection()
    try:
        params = [eval_epoch, dark_store_id]
        sku_filter = ""
        if sku_id:
            sku_filter = "AND it.sku_id = ?"
            params.append(sku_id)

        rows = conn.execute(
            f"""
            SELECT
                it.inventario_id,
                it.dark_store_id,
                it.sku_id,
                p.nombre,
                p.precio_unitario_vigente,
                it.existencia_e,
                it.reservado_r AS reservado_r_bruto,
                COALESCE((
                    SELECT SUM(ri.cantidad_reservada)
                      FROM reserva_inventario ri
                     WHERE ri.inventario_id = it.inventario_id
                       AND ri.estado_reserva IN ('ACTIVA', 'EN_PAGO')
                       AND ? < ri.expira_epoch
                ), 0) AS reservado_r_vigente,
                it.comprometido_c,
                it.oculto_h,
                it.estado_sku
            FROM inventario_tienda it
            JOIN producto_sku p ON p.sku_id = it.sku_id
            WHERE it.dark_store_id = ? {sku_filter}
            ORDER BY it.sku_id ASC
            """,
            params,
        ).fetchall()

        resultado = []
        for r in rows:
            if r["estado_sku"] != "HABILITADO":
                disp = 0
            else:
                disp = max(0, r["existencia_e"] - r["comprometido_c"] - r["reservado_r_vigente"] - r["oculto_h"])
            resultado.append({
                "dark_store_id": r["dark_store_id"],
                "sku_id": r["sku_id"],
                "nombre": r["nombre"],
                "precio": r["precio_unitario_vigente"],
                "existencia_e": r["existencia_e"],
                "reservado_r_vigente": r["reservado_r_vigente"],
                "comprometido_c": r["comprometido_c"],
                "oculto_h": r["oculto_h"],
                "disponible": disp,
                "estado_sku": r["estado_sku"],
                "evaluado_en_offset_sec": simulated_offset_sec,
            })
        return resultado
    finally:
        conn.close()


def reconstruir_saldo_auditable(dark_store_id: str, sku_id: str) -> dict:
    """C1 Punto 4: Reconstruye E, R, C, H desde la bitácora inmutable movimiento_inventario."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                it.sku_id,
                it.dark_store_id,
                it.existencia_e,
                it.reservado_r,
                it.comprometido_c,
                it.oculto_h,
                COALESCE(SUM(m.delta_e), 0) AS sum_delta_e,
                COALESCE(SUM(m.delta_r), 0) AS sum_delta_r,
                COALESCE(SUM(m.delta_c), 0) AS sum_delta_c,
                COALESCE(SUM(m.delta_h), 0) AS sum_delta_h,
                COUNT(m.movimiento_id)      AS total_movimientos
            FROM inventario_tienda it
            LEFT JOIN movimiento_inventario m ON m.inventario_id = it.inventario_id
            WHERE it.dark_store_id = ? AND it.sku_id = ?
            GROUP BY it.inventario_id
            """,
            (dark_store_id, sku_id),
        ).fetchone()
        if not row:
            raise DomainHttpError(404, "SKU_NO_EXISTE", "SKU o tienda no encontrados")
        movs = conn.execute(
            """
            SELECT movimiento_id, tipo_movimiento, delta_e, delta_r, delta_c, delta_h,
                   pedido_id, reserva_id, correlation_id, motivo_detalle, registrado_epoch
              FROM movimiento_inventario
             WHERE inventario_id = (SELECT inventario_id FROM inventario_tienda WHERE dark_store_id=? AND sku_id=?)
             ORDER BY registrado_epoch ASC
            """,
            (dark_store_id, sku_id),
        ).fetchall()
        cuadra = (
            row["existencia_e"] == row["sum_delta_e"]
            and row["reservado_r"] == row["sum_delta_r"]
            and row["comprometido_c"] == row["sum_delta_c"]
        )
        return {
            "sku_id": row["sku_id"],
            "dark_store_id": row["dark_store_id"],
            "existencia_e_tabla": row["existencia_e"],
            "existencia_e_reconstruida": row["sum_delta_e"],
            "reservado_r_tabla": row["reservado_r"],
            "reservado_r_reconstruido": row["sum_delta_r"],
            "comprometido_c_tabla": row["comprometido_c"],
            "comprometido_c_reconstruido": row["sum_delta_c"],
            "cuadre_auditable_exacto": bool(cuadra),
            "total_movimientos": row["total_movimientos"],
            "movimientos": [dict(m) for m in movs],
        }
    finally:
        conn.close()


def crear_checkout_y_reserva(
    idempotency_key: str,
    correlation_id: str,
    cliente_id: str,
    dark_store_id: str,
    lineas: list[dict],
) -> tuple[int, dict]:
    """
    Hito C1 y C2 (AT-01, AT-02, AT-05):
    - Idempotente por Idempotency-Key (si mismo cuerpo -> devuelve la misma reserva sin renovar expira_epoch;
      si cuerpo distinto -> devuelve 422 CLAVE_REUTILIZADA).
    - Bloquea atómicamente en orden global de sku_id (sin sobreventa en AT-01).
    - Crea reserva con expira_epoch = creada_epoch + 300.0 s exactos.
    """
    if not idempotency_key:
        raise DomainHttpError(400, "VALORES_INVALIDOS", "Cabecera Idempotency-Key obligatoria")
    payload_canonical = json.dumps({"dark_store_id": dark_store_id, "lineas": sorted(lineas, key=lambda x: x["sku_id"])}, sort_keys=True)
    payload_hash = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()

    with atomic_transaction() as conn:
        now = _now(0.0)
        existente = conn.execute(
            "SELECT * FROM pedido WHERE idempotency_key_checkout = ?",
            (idempotency_key,),
        ).fetchone()
        if existente:
            if existente["hash_payload"] != payload_hash:
                raise DomainHttpError(422, "CLAVE_REUTILIZADA", "La misma Idempotency-Key se envió con un carrito distinto.")
            tx_pago = conn.execute("SELECT transaccion_pago_id, estado_pago FROM transaccion_pago WHERE pedido_id = ?", (existente["pedido_id"],)).fetchone()
            return 201, {
                "pedido_id": existente["pedido_id"],
                "dark_store_id": existente["dark_store_id"],
                "estado_pedido": existente["estado_pedido"],
                "creado_epoch": existente["creado_epoch"],
                "expira_epoch": existente["expira_reserva_epoch"],
                "expira_en_bd_sec": 300,
                "monto_total_cobrado": existente["monto_total_cobrado"],
                "transaccion_pago_id": tx_pago["transaccion_pago_id"] if tx_pago else None,
                "idempotente_reutilizado": True,
            }

        expirar_reservas_vencidas_conn(conn, now)
        procesar_outbox_pendientes_conn(conn, now)

        lineas_ordenadas = sorted(lineas, key=lambda x: x["sku_id"])
        subtotal = 0.0
        inventarios_map = {}

        for item in lineas_ordenadas:
            sku = item["sku_id"]
            cant = int(item["cantidad"])
            row = conn.execute(
                """
                SELECT it.*, p.precio_unitario_vigente
                  FROM inventario_tienda it
                  JOIN producto_sku p ON p.sku_id = it.sku_id
                 WHERE it.dark_store_id = ? AND it.sku_id = ?
                """,
                (dark_store_id, sku),
            ).fetchone()
            if not row:
                raise DomainHttpError(404, "SKU_NO_EXISTE", f"SKU {sku} no existe en {dark_store_id}")
            if row["estado_sku"] != "HABILITADO":
                raise DomainHttpError(409, "SKU_INHABILITADO", f"SKU {sku} inhabilitado por discrepancia en verificación")
            disp = max(0, row["existencia_e"] - row["comprometido_c"] - row["reservado_r"] - row["oculto_h"])
            if disp < cant:
                raise DomainHttpError(409, "SIN_STOCK", f"Sin stock suficiente para {sku} (disponible={disp}, solicitado={cant})")
            inventarios_map[sku] = row
            subtotal += round(row["precio_unitario_vigente"] * cant, 2)

        pedido_id = str(uuid.uuid4())
        expira_epoch = round(now + TTL_SECONDS, 3)
        costo_envio = 15.0
        monto_total = round(subtotal + costo_envio, 2)

        conn.execute(
            """
            INSERT INTO pedido
                (pedido_id, cliente_id, dark_store_id, idempotency_key_checkout, hash_payload,
                 estado_pedido, subtotal_mercancia_original, costo_envio, monto_total_cobrado,
                 creado_epoch, expira_reserva_epoch, correlation_id)
            VALUES (?, ?, ?, ?, ?, 'PENDIENTE_PAGO', ?, ?, ?, ?, ?, ?)
            """,
            (pedido_id, cliente_id, dark_store_id, idempotency_key, payload_hash, subtotal, costo_envio, monto_total, now, expira_epoch, correlation_id),
        )

        for item in lineas_ordenadas:
            sku = item["sku_id"]
            cant = int(item["cantidad"])
            inv_row = inventarios_map[sku]
            linea_id = str(uuid.uuid4())
            reserva_id = str(uuid.uuid4())

            conn.execute(
                """
                INSERT INTO linea_pedido
                    (linea_pedido_id, pedido_id, sku_id, cantidad_solicitada, precio_unitario_congelado)
                VALUES (?, ?, ?, ?, ?)
                """,
                (linea_id, pedido_id, sku, cant, inv_row["precio_unitario_vigente"]),
            )
            conn.execute(
                """
                INSERT INTO reserva_inventario
                    (reserva_id, inventario_id, pedido_id, sku_id, dark_store_id,
                     cantidad_reservada, estado_reserva, creada_epoch, expira_epoch)
                VALUES (?, ?, ?, ?, ?, ?, 'EN_PAGO', ?, ?)
                """,
                (reserva_id, inv_row["inventario_id"], pedido_id, sku, dark_store_id, cant, now, expira_epoch),
            )
            conn.execute(
                """
                UPDATE inventario_tienda
                   SET reservado_r = reservado_r + ?, version_concurrency = version_concurrency + 1
                 WHERE inventario_id = ?
                """,
                (cant, inv_row["inventario_id"]),
            )
            conn.execute(
                """
                INSERT INTO movimiento_inventario
                    (movimiento_id, inventario_id, usuario_id, tipo_movimiento, delta_e, delta_r, delta_c, delta_h,
                     pedido_id, reserva_id, correlation_id, motivo_detalle, registrado_epoch)
                VALUES (?, ?, ?, 'RESERVA', 0, ?, 0, 0, ?, ?, ?, 'Reserva en checkout (300 s)', ?)
                """,
                (str(uuid.uuid4()), inv_row["inventario_id"], cliente_id, cant, pedido_id, reserva_id, correlation_id, now),
            )

        tx_pago_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO transaccion_pago
                (transaccion_pago_id, pedido_id, monto_solicitado, estado_pago, idempotency_key_pasarela, creada_epoch)
            VALUES (?, ?, ?, 'PENDIENTE_RESPUESTA', ?, ?)
            """,
            (tx_pago_id, pedido_id, monto_total, f"PAY-{pedido_id}", now),
        )

        return 201, {
            "pedido_id": pedido_id,
            "dark_store_id": dark_store_id,
            "estado_pedido": "PENDIENTE_PAGO",
            "creado_epoch": now,
            "expira_epoch": expira_epoch,
            "expira_en_bd_sec": 300,
            "monto_total_cobrado": monto_total,
            "transaccion_pago_id": tx_pago_id,
            "idempotente_reutilizado": False,
        }


def procesar_webhook_pasarela_simulada(
    event_id: str,
    pedido_id: str,
    modo_resultado: str,
    simulated_offset_sec: float = 0.0,
    simular_caida_antes_de_notificar: bool = False,
) -> dict:
    """
    Hito C2 — Simulador Bancario Controlable y Procesador de Webhooks (AT-03, AT-04, AT-05, AT-06, AT-10).
    """
    with atomic_transaction() as conn:
        tx = conn.execute("SELECT * FROM transaccion_pago WHERE pedido_id = ?", (pedido_id,)).fetchone()
        ped = conn.execute("SELECT * FROM pedido WHERE pedido_id = ?", (pedido_id,)).fetchone()
        if not tx or not ped:
            raise DomainHttpError(404, "PEDIDO_NO_EXISTE", "Pedido o transacción de pago no encontrados")

        eval_epoch = round(ped["creado_epoch"] + float(simulated_offset_sec), 3) if simulated_offset_sec > 0 else _now(0.0)

        if modo_resultado == "TIMEOUT_INCIERTO":
            conn.execute(
                "UPDATE transaccion_pago SET estado_pago = 'RESULTADO_INCIERTO' WHERE pedido_id = ?",
                (pedido_id,),
            )
            return {
                "pedido_id": pedido_id,
                "estado_pago": "RESULTADO_INCIERTO",
                "estado_pedido": ped["estado_pedido"],
                "mensaje": "AT-06: Timeout financiero registrado. Prohibido crear segundo cobro hasta conciliar.",
            }

        dup = conn.execute(
            """
            INSERT OR IGNORE INTO evento_pasarela (event_id, transaccion_pago_id, pedido_id, tipo_evento, recibido_epoch)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, tx["transaccion_pago_id"], pedido_id, modo_resultado, eval_epoch),
        )
        if dup.rowcount == 0:
            ped_actual = conn.execute("SELECT * FROM pedido WHERE pedido_id = ?", (pedido_id,)).fetchone()
            return {
                "pedido_id": pedido_id,
                "webhook_duplicado_ignorado": True,
                "estado_pedido": ped_actual["estado_pedido"],
                "mensaje": "AT-05: Webhook duplicado detectado por event_id e ignorado sin efectos adicionales.",
            }

        reservas = conn.execute("SELECT * FROM reserva_inventario WHERE pedido_id = ?", (pedido_id,)).fetchall()

        if modo_resultado == "PAGO_RECHAZADO":
            conn.execute(
                "UPDATE transaccion_pago SET estado_pago = 'RECHAZADO', t2_webhook_epoch = ? WHERE pedido_id = ?",
                (eval_epoch, pedido_id),
            )
            for r in reservas:
                if r["estado_reserva"] in ("ACTIVA", "EN_PAGO"):
                    conn.execute(
                        """
                        UPDATE reserva_inventario
                           SET estado_reserva = 'LIBERADA', motivo_liberacion = 'PAGO_RECHAZADO',
                               cerrada_epoch = ?, version_cas = version_cas + 1
                         WHERE reserva_id = ?
                        """,
                        (eval_epoch, r["reserva_id"]),
                    )
                    conn.execute(
                        "UPDATE inventario_tienda SET reservado_r = reservado_r - ? WHERE inventario_id = ?",
                        (r["cantidad_reservada"], r["inventario_id"]),
                    )
                    conn.execute(
                        """
                        INSERT INTO movimiento_inventario
                            (movimiento_id, inventario_id, usuario_id, tipo_movimiento, delta_e, delta_r, delta_c, delta_h,
                             pedido_id, reserva_id, correlation_id, motivo_detalle, registrado_epoch)
                        VALUES (?, ?, 'WEBHOOK-PAY', 'LIBERACION', 0, ?, 0, 0, ?, ?, ?, 'Liberación inmediata por pago rechazado (AT-03)', ?)
                        """,
                        (str(uuid.uuid4()), r["inventario_id"], -r["cantidad_reservada"], pedido_id, r["reserva_id"], ped["correlation_id"], eval_epoch),
                    )
            conn.execute("UPDATE pedido SET estado_pedido = 'CANCELADO' WHERE pedido_id = ?", (pedido_id,))
            return {
                "pedido_id": pedido_id,
                "webhook_duplicado_ignorado": False,
                "resultado_inventario": "RESERVA_LIBERADA_POR_RECHAZO",
                "estado_pedido": "CANCELADO",
                "estado_pago": "RECHAZADO",
            }

        expira_epoch = reservas[0]["expira_epoch"]
        if eval_epoch < expira_epoch and reservas[0]["estado_reserva"] in ("ACTIVA", "EN_PAGO"):
            for r in reservas:
                conn.execute(
                    """
                    UPDATE reserva_inventario
                       SET estado_reserva = 'CONFIRMADA', confirmada_epoch = ?, version_cas = version_cas + 1
                     WHERE reserva_id = ?
                    """,
                    (eval_epoch, r["reserva_id"]),
                )
                conn.execute(
                    """
                    UPDATE inventario_tienda
                       SET reservado_r = reservado_r - ?, comprometido_c = comprometido_c + ?,
                           version_concurrency = version_concurrency + 1
                     WHERE inventario_id = ?
                    """,
                    (r["cantidad_reservada"], r["cantidad_reservada"], r["inventario_id"]),
                )
                conn.execute(
                    """
                    INSERT INTO movimiento_inventario
                        (movimiento_id, inventario_id, usuario_id, tipo_movimiento, delta_e, delta_r, delta_c, delta_h,
                         pedido_id, reserva_id, correlation_id, motivo_detalle, registrado_epoch)
                    VALUES (?, ?, 'WEBHOOK-PAY', 'COMPROMISO', 0, ?, ?, 0, ?, ?, ?, 'Compromiso de inventario por pago aprobado', ?)
                    """,
                    (str(uuid.uuid4()), r["inventario_id"], -r["cantidad_reservada"], r["cantidad_reservada"], pedido_id, r["reserva_id"], ped["correlation_id"], eval_epoch),
                )
            conn.execute(
                """
                UPDATE transaccion_pago
                   SET estado_pago = 'APROBADO', monto_capturado = monto_solicitado,
                       t2_webhook_epoch = ?, t3_confirmado_epoch = ?
                 WHERE pedido_id = ?
                """,
                (eval_epoch, eval_epoch, pedido_id),
            )
            conn.execute("UPDATE pedido SET estado_pedido = 'PAGADO' WHERE pedido_id = ?", (pedido_id,))
            return {
                "pedido_id": pedido_id,
                "webhook_duplicado_ignorado": False,
                "resultado_inventario": "COMPROMISO_OK",
                "estado_pedido": "PAGADO",
                "estado_pago": "APROBADO",
            }
        else:
            expirar_reservas_vencidas_conn(conn, eval_epoch)
            conn.execute(
                """
                UPDATE transaccion_pago
                   SET estado_pago = 'APROBADO', monto_capturado = monto_solicitado,
                       t2_webhook_epoch = ?, t3_confirmado_epoch = ?
                 WHERE pedido_id = ?
                """,
                (eval_epoch, eval_epoch, pedido_id),
            )
            conn.execute(
                """
                UPDATE pedido
                   SET estado_pedido = 'CANCELADO',
                       monto_reembolso_obligado = monto_total_cobrado
                 WHERE pedido_id = ?
                """,
                (pedido_id,),
            )
            evt_reemb_id = f"EVT-REF-LATE-{pedido_id}"
            payload_reemb = json.dumps({
                "pedido_id": pedido_id,
                "monto": ped["monto_total_cobrado"],
                "motivo": "PAGO_TARDIO_RESERVA_EXPIRADA",
                "linea_scope_key": "TOTAL",
            })
            conn.execute(
                """
                INSERT OR IGNORE INTO evento_outbox
                    (evento_id, agregado_id, tipo_evento, payload_json, correlation_id, estado_outbox, creado_epoch)
                VALUES (?, ?, 'EVT-05_ReembolsoSolicitado', ?, ?, 'PENDIENTE', ?)
                """,
                (evt_reemb_id, pedido_id, payload_reemb, ped["correlation_id"], eval_epoch),
            )

            if not simular_caida_antes_de_notificar:
                procesar_outbox_pendientes_conn(conn, eval_epoch)
                estado_reembolso = "COMPLETADO"
            else:
                estado_reembolso = "PENDIENTE_EN_OUTBOX_POR_CAIDA_SIMULADA"

            return {
                "pedido_id": pedido_id,
                "webhook_duplicado_ignorado": False,
                "resultado_inventario": "RESERVA_EXPIRADA_PAGO_TARDIO",
                "estado_pedido": "CANCELADO",
                "estado_pago": "APROBADO",
                "estado_reembolso_simulado": estado_reembolso,
                "caida_simulada_at10": simular_caida_antes_de_notificar,
            }