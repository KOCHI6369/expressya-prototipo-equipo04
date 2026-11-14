CREATE TABLE IF NOT EXISTS dark_store (
    dark_store_id    TEXT PRIMARY KEY,
    codigo_tienda    TEXT NOT NULL UNIQUE,
    nombre           TEXT NOT NULL,
    zona_cobertura   TEXT NOT NULL,
    estado_operativo TEXT NOT NULL DEFAULT 'ACTIVA' CHECK (estado_operativo IN ('ACTIVA', 'SUSPENDIDA'))
);

CREATE TABLE IF NOT EXISTS producto_sku (
    sku_id                  TEXT PRIMARY KEY,
    codigo_barras           TEXT NOT NULL UNIQUE,
    nombre                  TEXT NOT NULL,
    categoria               TEXT NOT NULL,
    precio_unitario_vigente REAL NOT NULL CHECK (precio_unitario_vigente > 0)
);

CREATE TABLE IF NOT EXISTS inventario_tienda (
    inventario_id       TEXT PRIMARY KEY,
    sku_id              TEXT NOT NULL REFERENCES producto_sku(sku_id),
    dark_store_id       TEXT NOT NULL REFERENCES dark_store(dark_store_id),
    existencia_e        INTEGER NOT NULL DEFAULT 0,
    reservado_r         INTEGER NOT NULL DEFAULT 0,
    comprometido_c      INTEGER NOT NULL DEFAULT 0,
    oculto_h            INTEGER NOT NULL DEFAULT 0,
    estado_sku          TEXT NOT NULL DEFAULT 'HABILITADO'
        CHECK (estado_sku IN ('HABILITADO', 'INHABILITADO', 'EN_REVERIFICACION')),
    version_concurrency INTEGER NOT NULL DEFAULT 1,
    UNIQUE (sku_id, dark_store_id),
    -- INV-01: Ningún contador puede ser negativo jamás
    CONSTRAINT chk_inv01_no_negativos
        CHECK (existencia_e >= 0 AND reservado_r >= 0 AND comprometido_c >= 0 AND oculto_h >= 0),
    -- INV-02: Comprometido + Reservado nunca supera la Existencia física registrada
    CONSTRAINT chk_inv02_c_mas_r_menor_igual_e
        CHECK (comprometido_c + reservado_r <= existencia_e)
);

CREATE TABLE IF NOT EXISTS reserva_inventario (
    reserva_id         TEXT PRIMARY KEY,
    inventario_id      TEXT NOT NULL REFERENCES inventario_tienda(inventario_id),
    pedido_id          TEXT NOT NULL,
    sku_id             TEXT NOT NULL,
    dark_store_id      TEXT NOT NULL,
    cantidad_reservada INTEGER NOT NULL CHECK (cantidad_reservada > 0),
    cantidad_recortada INTEGER NOT NULL DEFAULT 0 CHECK (cantidad_recortada >= 0),
    estado_reserva     TEXT NOT NULL DEFAULT 'ACTIVA'
        CHECK (estado_reserva IN ('ACTIVA', 'EN_PAGO', 'CONFIRMADA', 'LIBERADA', 'EXPIRADA')),
    surtido_iniciado   INTEGER NOT NULL DEFAULT 0,
    creada_epoch       REAL NOT NULL,
    expira_epoch       REAL NOT NULL,
    confirmada_epoch   REAL,
    cerrada_epoch      REAL,
    motivo_liberacion  TEXT NOT NULL DEFAULT 'NINGUNO',
    version_cas        INTEGER NOT NULL DEFAULT 1,
    UNIQUE (pedido_id, sku_id),
    -- INV-13 y S2-01: Duración exacta e inmutable de 300 segundos (5 minutos)
    CONSTRAINT chk_ttl_300s CHECK (ROUND(expira_epoch - creada_epoch, 3) = 300.0)
);

CREATE TABLE IF NOT EXISTS movimiento_inventario (
    movimiento_id    TEXT PRIMARY KEY,
    inventario_id    TEXT NOT NULL REFERENCES inventario_tienda(inventario_id),
    usuario_id       TEXT NOT NULL,
    tipo_movimiento  TEXT NOT NULL
        CHECK (tipo_movimiento IN (
            'INGRESO_INICIAL', 'INGRESO_CUARENTENA', 'LIBERACION_CUARENTENA',
            'RESERVA', 'LIBERACION', 'COMPROMISO', 'RECORTE_COMPROMISO',
            'SALIDA_PICKING', 'MERMA_GERENTE', 'FALTANTE_PICKING',
            'AJUSTE_DISCREPANCIA', 'COMPENSACION_CONTEO'
        )),
    delta_e          INTEGER NOT NULL DEFAULT 0,
    delta_r          INTEGER NOT NULL DEFAULT 0,
    delta_c          INTEGER NOT NULL DEFAULT 0,
    delta_h          INTEGER NOT NULL DEFAULT 0,
    pedido_id        TEXT,
    reserva_id       TEXT,
    correlation_id   TEXT NOT NULL,
    motivo_detalle   TEXT,
    registrado_epoch REAL NOT NULL
);

-- INV-05: Exactamente un movimiento COMPROMISO por cada reserva_id
CREATE UNIQUE INDEX IF NOT EXISTS idx_uq_un_compromiso_por_reserva
    ON movimiento_inventario (reserva_id)
    WHERE tipo_movimiento = 'COMPROMISO';

CREATE TABLE IF NOT EXISTS pedido (
    pedido_id                   TEXT PRIMARY KEY,
    cliente_id                  TEXT NOT NULL,
    dark_store_id               TEXT NOT NULL,
    idempotency_key_checkout    TEXT NOT NULL UNIQUE,
    hash_payload                TEXT NOT NULL,
    estado_pedido               TEXT NOT NULL DEFAULT 'PENDIENTE_PAGO'
        CHECK (estado_pedido IN (
            'PENDIENTE_PAGO', 'PAGADO', 'EN_PICKING', 'SURTIDO_COMPLETO',
            'SURTIDO_PARCIAL', 'DESPACHADO', 'ENTREGADO',
            'RECHAZADO_SIN_STOCK', 'CANCELADO', 'CANCELADO_TOTAL'
        )),
    subtotal_mercancia_original REAL NOT NULL CHECK (subtotal_mercancia_original >= 0),
    costo_envio                 REAL NOT NULL DEFAULT 15.0,
    monto_total_cobrado         REAL NOT NULL CHECK (monto_total_cobrado >= 0),
    subtotal_mercancia_surtida  REAL NOT NULL DEFAULT 0.0,
    monto_reembolso_obligado    REAL NOT NULL DEFAULT 0.0,
    monto_reembolso_confirmado  REAL NOT NULL DEFAULT 0.0,
    creado_epoch                REAL NOT NULL,
    expira_reserva_epoch        REAL NOT NULL,
    correlation_id              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS linea_pedido (
    linea_pedido_id           TEXT PRIMARY KEY,
    pedido_id                 TEXT NOT NULL REFERENCES pedido(pedido_id),
    sku_id                    TEXT NOT NULL,
    cantidad_solicitada       INTEGER NOT NULL CHECK (cantidad_solicitada > 0),
    cantidad_surtida          INTEGER NOT NULL DEFAULT 0,
    cantidad_cancelada        INTEGER NOT NULL DEFAULT 0,
    precio_unitario_congelado REAL NOT NULL CHECK (precio_unitario_congelado > 0),
    estado_linea              TEXT NOT NULL DEFAULT 'PENDIENTE',
    motivo_cancelacion_linea  TEXT NOT NULL DEFAULT 'NINGUNO',
    UNIQUE (pedido_id, sku_id)
);

CREATE TABLE IF NOT EXISTS transaccion_pago (
    transaccion_pago_id      TEXT PRIMARY KEY,
    pedido_id                TEXT NOT NULL UNIQUE REFERENCES pedido(pedido_id),
    monto_solicitado         REAL NOT NULL,
    monto_capturado          REAL NOT NULL DEFAULT 0.0,
    estado_pago              TEXT NOT NULL DEFAULT 'PENDIENTE_RESPUESTA'
        CHECK (estado_pago IN (
            'PENDIENTE_RESPUESTA', 'RESULTADO_INCIERTO',
            'APROBADO', 'RECHAZADO', 'ANULADO_VOID'
        )),
    idempotency_key_pasarela TEXT NOT NULL UNIQUE,
    t1_autorizado_epoch      REAL,
    t2_webhook_epoch         REAL,
    t3_confirmado_epoch      REAL,
    creada_epoch             REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS evento_pasarela (
    event_id            TEXT PRIMARY KEY,
    transaccion_pago_id TEXT NOT NULL REFERENCES transaccion_pago(transaccion_pago_id),
    pedido_id           TEXT NOT NULL,
    tipo_evento         TEXT NOT NULL,
    recibido_epoch      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS obligacion_reembolso (
    reembolso_id              TEXT PRIMARY KEY,
    pedido_id                 TEXT NOT NULL REFERENCES pedido(pedido_id),
    linea_scope_key           TEXT NOT NULL DEFAULT 'TOTAL',
    monto_a_reembolsar        REAL NOT NULL CHECK (monto_a_reembolsar > 0),
    motivo_reembolso          TEXT NOT NULL,
    estado_reembolso          TEXT NOT NULL DEFAULT 'SOLICITADO'
        CHECK (estado_reembolso IN (
            'SOLICITADO', 'ENVIADO_RESULTADO_INCIERTO',
            'REINTENTANDO', 'REVISION_MANUAL', 'COMPLETADO'
        )),
    idempotency_key_reembolso TEXT NOT NULL UNIQUE,
    creado_epoch              REAL NOT NULL,
    UNIQUE (pedido_id, linea_scope_key, motivo_reembolso)
);

CREATE TABLE IF NOT EXISTS evento_outbox (
    evento_id       TEXT PRIMARY KEY,
    agregado_id     TEXT NOT NULL,
    tipo_evento     TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    correlation_id  TEXT NOT NULL,
    estado_outbox   TEXT NOT NULL DEFAULT 'PENDIENTE'
        CHECK (estado_outbox IN ('PENDIENTE', 'PUBLICADO', 'ERROR_DEAD_LETTER')),
    intentos        INTEGER NOT NULL DEFAULT 0,
    creado_epoch    REAL NOT NULL,
    publicado_epoch REAL
);

CREATE TABLE IF NOT EXISTS evento_consumido (
    evento_id         TEXT NOT NULL,
    modulo_consumidor TEXT NOT NULL,
    tipo_evento       TEXT NOT NULL,
    procesado_epoch   REAL NOT NULL,
    PRIMARY KEY (evento_id, modulo_consumidor)
);
