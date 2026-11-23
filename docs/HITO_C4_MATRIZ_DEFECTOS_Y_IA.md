# Hito C4 — Matriz de Casos, Defectos/Regresión y Defensa de IA

- **Proyecto:** ExpressYa (Hitos C3 y C4)[cite: 1]
- **Materia / Grupo / Equipo:** Ingeniería de Software — Grupo 1501 — Equipo 04[cite: 1]
- **Responsable del documento:** Talavera Osorio Jorge[cite: 4, 21]
- **Fecha de seguimiento:** Domingo 22 de noviembre de 2026[cite: 1]

---

## 1. Matriz Requisito → Diseño / Código → Prueba → Resultado (15 casos)

| Caso | Requisito / Escenario | Diseño / Código | Prueba | Automatizado | Estado / Resultado |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 01 | 5 Dark Stores cargadas, disponibilidad y cuadre `E = SUM(delta_e)` | Rutas y servicios C1 en `app/main.py` y `app/services.py`[cite: 1, 26] | `test_01_c1_cinco_tiendas_y_reconstruccion_auditable` (`pruebas/test_hitos_c1_y_c2.py`)[cite: 24, 25] | Sí (`unittest`)[cite: 22, 25] | Verificado en hitos previos (confirmar ejecución conjunta)[cite: 1, 2, 20] |
| 02 | Última unidad con concurrencia real (`AT-01`) | Reserva atómica con `BEGIN IMMEDIATE` y concurrencia | `test_02_at01_ultima_unidad_concurrencia_real` (`pruebas/test_hitos_c1_y_c2.py`)[cite: 24, 25] | Sí (`unittest`)[cite: 22, 25] | Verificado en hitos previos (confirmar ejecución conjunta)[cite: 1, 2, 20] |
| 03 | Reserva válida a 299 s y expirada a 300 s (`AT-02`) | Expiración TTL de reserva y validación temporal[cite: 1, 22] | `test_03_at02_reserva_valida_a_299s_y_expirada_a_300s` (`pruebas/test_hitos_c1_y_c2.py`)[cite: 24, 25] | Sí (`unittest`)[cite: 22, 25] | Verificado en hitos previos (confirmar ejecución conjunta)[cite: 1, 2, 20] |
| 04 | Pago rechazado libera inventario (`AT-03`) | Webhook de pago rechazado y liberación de reserva[cite: 1, 25] | `test_04_at03_pago_rechazado_libera_inventario` (`pruebas/test_hitos_c1_y_c2.py`)[cite: 24, 25] | Sí (`unittest`)[cite: 22, 25] | Verificado en hitos previos (confirmar ejecución conjunta)[cite: 1, 2, 20] |
| 05 | Pago tardío tras TTL genera reembolso sin revivir reserva (`AT-04`) | Manejo de pago posterior a expiración y reembolso simulado[cite: 1, 25] | `test_05_at04_pago_confirmado_despues_del_ttl_reembolsa_sin_revivir` (`pruebas/test_hitos_c1_y_c2.py`)[cite: 24, 25] | Sí (`unittest`)[cite: 22, 25] | Verificado en hitos previos (confirmar ejecución conjunta)[cite: 1, 2, 20] |
| 06 | Idempotencia en checkout y webhook duplicado (`AT-05`) | Clave de idempotencia y control de eventos repetidos[cite: 1, 25] | `test_06_at05_idempotencia_checkout_y_webhook_duplicado` (`pruebas/test_hitos_c1_y_c2.py`)[cite: 24, 25] | Sí (`unittest`)[cite: 22, 25] | Verificado en hitos previos (confirmar ejecución conjunta)[cite: 1, 2, 20] |
| 07 | Timeout financiero en estado incierto (`AT-06`) | Estado `RESULTADO_INCIERTO` en conciliación de pago[cite: 25] | `test_07_at06_timeout_financiero_estado_incierto` (`pruebas/test_hitos_c1_y_c2.py`)[cite: 24, 25] | Sí (`unittest`)[cite: 22, 25] | Verificado en hitos previos (confirmar ejecución conjunta)[cite: 1, 2, 20] |
| 08 | Caída simulada y recuperación Outbox idempotente (`AT-10`) | Persistencia Outbox y endpoint de recuperación idempotente[cite: 1, 25] | `test_08_at10_caida_logica_y_recuperacion_outbox_idempotente` (`pruebas/test_hitos_c1_y_c2.py`)[cite: 24, 25] | Sí (`unittest`)[cite: 22, 25] | Verificado en hitos previos (confirmar ejecución conjunta)[cite: 1, 2, 20] |
| 09 | Discrepancia 10 vs 8 bloquea disponibilidad (`AT-07`) | `registrar_discrepancia_picking` y ruta `POST /api/v1/picking/discrepancia`[cite: 8, 17, 19] | `test_09_at07_discrepancia_10_vs_8_bloquea_disponibilidad` (`pruebas/test_hito_c3_y_c4.py`)[cite: 19] | Sí (`unittest`)[cite: 22] | Pendiente de correr y validar contra integración final[cite: 2, 3, 20] |
| 10 | Pedido de 5 líneas con 1 faltante continúa con 4 (`AT-08`) | `procesar_surtido_parcial` y ruta `POST /api/v1/picking/surtido-parcial`[cite: 11, 17, 19] | `test_10_at08_pedido_5_lineas_una_faltante_continuan_4` (`pruebas/test_hito_c3_y_c4.py`)[cite: 19] | Sí (`unittest`)[cite: 22] | Pendiente de correr y validar contra integración final[cite: 2, 3, 20] |
| 11 | Reembolso parcial repetido aplicado una sola vez (`AT-09`) | `registrar_reembolso_parcial_idempotente` y ruta `POST /api/v1/payments/reembolso-parcial`[cite: 14, 17, 20] | `test_11_at09_reembolso_parcial_repetido_una_sola_vez` (`pruebas/test_hito_c3_y_c4.py`)[cite: 20] | Sí (`unittest`)[cite: 22] | Pendiente de correr y validar contra integración final[cite: 2, 3, 20] |
| 12 | Historial completo de auditoría (quién, cuándo, por qué, impacto) | `consultar_historial_auditoria` y ruta `GET /api/v1/auditoria/historial`[cite: 15, 17, 18, 20] | `test_12_c3_historial_auditoria_quien_cuando_porque_impacto` (`pruebas/test_hito_c3_y_c4.py`)[cite: 20] | Sí (`unittest`)[cite: 22] | Pendiente de correr y validar contra integración final[cite: 2, 3, 20] |
| 13 | Flujo completo de compra normal extremo a extremo | Checkout, pago aprobado, surtido completo y reconstrucción auditable[cite: 20] | `test_13_c4_flujo_completo_compra_normal_extremo_a_extremo` (`pruebas/test_hito_c3_y_c4.py`)[cite: 20] | Sí (`unittest`)[cite: 22] | Pendiente de correr y validar contra integración final[cite: 2, 3, 20] |
| 14 | Regresión: reutilizar `Idempotency-Key` con carrito distinto (`422`) | Validación de idempotencia ante payloads diferentes[cite: 20] | `test_14_c4_regresion_idempotencia_clave_reutilizada_422` (`pruebas/test_hito_c3_y_c4.py`)[cite: 20] | Sí (`unittest`)[cite: 22] | Pendiente de correr y validar contra integración final[cite: 2, 3, 20] |
| 15 | Regresión: carrito multi-SKU con faltante hace `ROLLBACK` completo | Atomicidad transaccional sin dejar reservas parciales ni saldo negativo[cite: 21] | `test_15_c4_regresion_multiples_skus_sin_saldo_negativo` (`pruebas/test_hito_c3_y_c4.py`)[cite: 21] | Sí (`unittest`)[cite: 22] | Pendiente de correr y validar contra integración final[cite: 2, 3, 20] |

---

## 2. Registro de Defectos Encontrados, Corrección y Regresión

*(Ajustar este apartado con los defectos reales confirmados por el equipo; la guía plantea los siguientes ejemplos de referencia[cite: 2, 22].)*

- **Defecto #1 — Archivos vacíos o ruido de archivos generados al subir cambios:** Evitar subir archivos sin guardar o temporales/bases de datos locales mediante `.gitignore` y revisión antes de confirmar[cite: 22]. **Regresión:** `test_01` y verificación de carga de esquema/base de datos[cite: 22, 25].
- **Defecto #2 — Dependencias externas de pruebas entre equipos:** Usar `unittest` estándar de Python evita exigir paquetes extra en cada máquina[cite: 22]. **Regresión:** Ejecución de la suite con `unittest` y prueba concurrente `test_02`[cite: 20, 22, 25].
- **Defecto #3 — Riesgo de duplicar reembolso parcial en reintentos:** Garantizar unicidad/idempotencia en la obligación de reembolso para que un reintento no sume dos veces el monto[cite: 7, 10, 22]. **Regresión:** `test_11_at09_reembolso_parcial_repetido_una_sola_vez`[cite: 20, 22].

---

## 3. Defensa Crítica de Uso de IA

*(Confirmar con el equipo que estas tres posturas correspondan a lo que ustedes acordaron y defendieron[cite: 2, 22].)*

- **Decisión APOYADA por IA:** Diseñar pruebas de concurrencia con hilos sincronizados (`threading.Barrier`) y transacciones inmediatas para comprobar exclusión mutua en lugar de depender solo de clics manuales[cite: 22, 25].
- **Decisión MODIFICADA por el equipo:** Ajustar límites o condiciones de borde (como la frontera exacta de expiración temporal de reservas) tras revisar las reglas y aclaraciones del dominio[cite: 22].
- **Decisión RECHAZADA a la IA:** Descartar arquitecturas distribuidas complejas con múltiples servicios/colas/bases externas cuando no aportan al alcance del prototipo y complican que todos los integrantes ejecuten y expliquen el sistema[cite: 22].
