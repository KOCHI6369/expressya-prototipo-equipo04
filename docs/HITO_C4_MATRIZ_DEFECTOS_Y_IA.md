# Hito C4 — Matriz de Trazabilidad (15 Casos), Bitácora de Defectos y Defensa Crítica de IA

**Proyecto:** Plataforma de Comercio Rápido ExpressYa (5 Dark Stores)  
**Materia:** Ingeniería de Software · **Grupo:** 1501 · **Equipo:** 04  
**Integrantes:** García Galicia Leticia, González Briones Remedios Guadalupe, Galindo Castillo Sayid Amir, Molina Monroy José Ramón, Hernández González Nery Xiomara y Talavera Osorio Jorge.  
**Repositorio:** `https://github.com/KOCHI6369/expressya-prototipo-equipo04`  
**Comando de ejecución de las 15 pruebas:** `python -m unittest discover -s tests -v`

---

## 1. Matriz Requisito → Diseño → Código → Prueba → Resultado (15 Casos Automatizados)

| # | Requisito / Escenario (`AT`) | Decisión de Diseño (`SDD` / `ADR`) | Ubicación Exacta en Código | Prueba Automatizada (`unittest`) | Automatizado | Resultado |
| :-: | :--- | :--- | :--- | :--- | :---: | :---: |
| **1** | **C1:** 5 Dark Stores y reconstrucción auditable ($E = \sum \Delta E$) | Semilla inicial y bitácora inmutable `movimiento_inventario` (`INV-09`). | `app/database.py` (`init_and_seed_db`), `app/services.py` (`reconstruir_saldo_auditable`). | `tests/test_hitos_c1_y_c2.py::test_01_c1_cinco_tiendas_y_reconstruccion_auditable` | Sí | `OK` |
| **2** | **`AT-01`:** Última unidad con competencia real (8 hilos simultáneos) | Transacción `BEGIN IMMEDIATE` en SQLite `WAL` + `CHECK (C + R <= E)`. | `app/database.py` (`atomic_transaction`), `app/services.py` (`crear_checkout_y_reserva`). | `tests/test_hitos_c1_y_c2.py::test_02_at01_ultima_unidad_concurrencia_real` | Sí | `OK` |
| **3** | **`AT-02`:** Reserva válida a 299 s y expirada a 300 s exactos | Semántica estricta `eval_epoch < expira_epoch` (`S2-01`, Aclaración `9.12`). | `app/services.py` (`consultar_disponibilidad_tienda`, `expirar_reservas_vencidas_conn`). | `tests/test_hitos_c1_y_c2.py::test_03_at02_reserva_valida_a_299s_y_expirada_a_300s` | Sí | `OK` |
| **4** | **`AT-03`:** Pago rechazado libera inventario de inmediato | Transición a `RECHAZADO` + `LIBERACION` inmediata de `reservado_r`. | `app/services.py` (`procesar_webhook_pasarela_simulada`, rama `PAGO_RECHAZADO`). | `tests/test_hitos_c1_y_c2.py::test_04_at03_pago_rechazado_libera_inventario` | Sí | `OK` |
| **5** | **`AT-04`:** Pago confirmado después del TTL ($t \ge 300\text{ s}$) | Prohibido revivir reserva (`9.13`); pedido `CANCELADO` + reembolso 100%. | `app/services.py` (`procesar_webhook_pasarela_simulada`, rama tardía). | `tests/test_hitos_c1_y_c2.py::test_05_at04_pago_confirmado_despues_del_ttl_reembolsa_sin_revivir` | Sí | `OK` |
| **6** | **`AT-05`:** Idempotencia de checkout y webhook duplicado | `idempotency_key_checkout` + `PRIMARY KEY (event_id)` en `evento_pasarela`. | `app/services.py` (`crear_checkout_y_reserva`, `INSERT OR IGNORE INTO evento_pasarela`). | `tests/test_hitos_c1_y_c2.py::test_06_at05_idempotencia_checkout_y_webhook_duplicado` | Sí | `OK` |
| **7** | **`AT-06`:** Timeout financiero deja estado desconocido | Estado `RESULTADO_INCIERTO` sin reintento ciego ni liberación prematura. | `app/services.py` (`procesar_webhook_pasarela_simulada`, rama `TIMEOUT_INCIERTO`). | `tests/test_hitos_c1_y_c2.py::test_07_at06_timeout_financiero_estado_incierto` | Sí | `OK` |
| **8** | **`AT-10`:** Caída tras persistir y antes de notificar | Patrón *Outbox* (`evento_outbox`) + consumidor idempotente (`evento_consumido`, `S2-02`). | `app/services.py` (`procesar_outbox_pendientes_conn`). | `tests/test_hitos_c1_y_c2.py::test_08_at10_caida_logica_y_recuperacion_outbox_idempotente` | Sí | `OK` |
| **9** | **`AT-07`:** Discrepancia lógica 10 vs. física 8 en picking | Bloqueo inmediato `estado_sku = 'INHABILITADO'` + `incidencia_inventario` (`S2-03`). | `sql/01_schema.sql`, `app/services_c3.py` (`registrar_discrepancia_picking`). | `tests/test_hito_c3_y_c4.py::test_09_at07_discrepancia_10_vs_8_bloquea_disponibilidad` | Sí | `OK` |
| **10** | **`AT-08`:** Pedido de 5 líneas con 1 faltante | Surtido parcial: 4 líneas a `SURTIDA` (`SALIDA_PICKING`) y 1 a `CANCELADA_FALTANTE`. | `app/services_c3.py` (`procesar_surtido_parcial`). | `tests/test_hito_c3_y_c4.py::test_10_at08_pedido_5_lineas_una_faltante_continuan_4` | Sí | `OK` |
| **11** | **`AT-09`:** Reembolso parcial repetido aplicado una sola vez | `UNIQUE (pedido_id, linea_scope_key, motivo_reembolso)` + `cur.rowcount == 1`. | `app/services_c3.py` (`registrar_reembolso_parcial_idempotente`). | `tests/test_hito_c3_y_c4.py::test_11_at09_reembolso_parcial_repetido_una_sola_vez` | Sí | `OK` |
| **12** | **C3 Punto 4:** Historial auditable (quién, qué, cuándo, por qué, impacto) | Consulta trazable uniendo `movimiento_inventario`, `incidencia_inventario` y `pedido`. | `app/services_c3.py` (`consultar_historial_auditoria`). | `tests/test_hito_c3_y_c4.py::test_12_c3_historial_auditoria_quien_cuando_porque_impacto` | Sí | `OK` |
| **13** | **C4 Punto 1:** Compra normal extremo a extremo | Flujo completo `checkout` → `PAGO_APROBADO` → `SURTIDO_COMPLETO` → cuadre. | `app/services.py`, `app/services_c3.py`, `app/main.py`. | `tests/test_hito_c3_y_c4.py::test_13_c4_flujo_completo_compra_normal_extremo_a_extremo` | Sí | `OK` |
| **14** | **C4 Regresión:** Reutilizar `Idempotency-Key` con otro carrito | Validación de huella criptográfica `SHA-256` del payload (`422 CLAVE_REUTILIZADA`). | `app/services.py` (`crear_checkout_y_reserva`). | `tests/test_hito_c3_y_c4.py::test_14_c4_regresion_idempotencia_clave_reutilizada_422` | Sí | `OK` |
| **15** | **C4 Regresión:** Carrito multilínea con 1 SKU sin stock | Atomicidad ACID con `ROLLBACK` total en `atomic_transaction()`. | `app/database.py`, `app/services.py` (`crear_checkout_y_reserva`). | `tests/test_hito_c3_y_c4.py::test_15_c4_regresion_carrito_multilinea_rollback_atomico` | Sí | `OK` |

---

## 2. Registro de Defectos Encontrados, Correcciones y Regresión (Sección 8, Punto 3)

| ID | Defecto Detectado Durante Construcción / Integración | Causa Raíz | Corrección Aplicada | Prueba de Regresión Asociada |
| :-: | :--- | :--- | :--- | :--- |
| **DEF-01** | En el primer push de C1, `sql/01_schema.sql` y `app/database.py` se subieron con `0 bytes` y `__pycache__/` ensuciaba el repo. | Ejecución de `git add .` antes de guardar en VS Code y ausencia de `__pycache__/` en `.gitignore`. | Se actualizaron `.gitignore` y los commits con verificación previa vía `python -c`. | `test_01_c1_cinco_tiendas_y_reconstruccion_auditable` |
| **DEF-02** | `pytest` no estaba instalado en equipos heterogéneos del equipo, impidiendo reproducibilidad inmediata. | Dependencia externa no incluida en Python base en Windows/Linux. | Migración completa de la suite a `unittest` estándar de Python 3 (`0` dependencias externas). | `python -m unittest discover -s tests -v` (`15/15 OK`) |
| **DEF-03** | Error `ModuleNotFoundError: No module named 'app.services_c3'` al integrar rama `feature/c3-at07-discrepancia`. | Creación accidental de subcarpeta duplicada `app/app/services_c3.py` desde la interfaz web de GitHub. | Reubicación con `git mv app/app/services_c3.py app/services_c3.py` y validación de imports en `main.py`. | `test_09_at07_discrepancia_10_vs_8_bloquea_disponibilidad` |
| **DEF-04** | Riesgo de doble abono al reintentar un reembolso parcial por línea faltante. | Un `UPDATE pedido` sin verificar si la inserción en `obligacion_reembolso` fue nueva sumaría el monto dos veces. | Se condicionó el `UPDATE` estrictamente a `cur.rowcount == 1` tras `INSERT OR IGNORE` respaldado por `UNIQUE`. | `test_11_at09_reembolso_parcial_repetido_una_sola_vez` |

---

## 3. Defensa Crítica del Uso de IA (Sección 8, Punto 5 — Evidencia de Intervención Humana)

1. **Decisión APOYADA por IA (y verificada por el equipo):**
   - *Qué propuso la IA:* Implementar la prueba de concurrencia real **`AT-01`** con **`threading.Barrier(8)`** sobre `BEGIN IMMEDIATE` en SQLite `WAL` para forzar colisión en el mismo milisegundo sin depender de clics manuales.
   - *Por qué se aceptó:* Cumple estrictamente la **Regla 4.2** del documento de construcción y demuestra determinísticamente `1` ganador (`201`) y `7` rechazos (`409 SIN_STOCK`).
2. **Decisión MODIFICADA por el equipo:**
   - *Qué generó inicialmente la IA:* Comparación de vigencia de reserva con `<=` (`eval_epoch <= expira_epoch`).
   - *Intervención humana del equipo:* Al contrastar contra la aclaración **`9.12`** del cliente y **`S2-01`** (*"en $t = \text{vencimiento}$ ya está expirada"*), el equipo corrigió el operador a **`<` estricto** (`eval_epoch < expira_epoch`) para vigencia y **`>=`** para expiración, validándolo en `test_03_at02` (`299 s` válida vs. `300 s` expirada).
3. **Decisión RECHAZADA a la IA:**
   - *Qué sugirió la IA originalmente:* Desplegar 4 microservicios separados en contenedores Docker con PostgreSQL, RabbitMQ/Kafka y FastAPI/Uvicorn.
   - *Por qué se rechazó (`ADR-S3-01`):* Introducía complejidad accidental y puntos de fallo de red/instalación que dificultaban la reproducibilidad y defensa por cualquiera de los 6 integrantes. El equipo decidió consolidar un **Monolito Modular en Python 3 estándar + SQLite WAL + Outbox**, manteniendo intactos todos los invariantes de dominio del SDD.
