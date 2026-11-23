import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "expressya_real.db"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "01_schema.sql"

# Candado reentrante a nivel de proceso + BEGIN IMMEDIATE a nivel de archivo SQLite (WAL)
_WRITE_LOCK = threading.RLock()


class DomainHttpError(Exception):
    def __init__(self, status_code: int, error_code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn


@contextmanager
def atomic_transaction():
    """
    Ejecuta una transacción ACID con bloqueo exclusivo inmediato (BEGIN IMMEDIATE),
    serializando operaciones concurrentes sobre la última unidad (AT-01).
    Si ocurre cualquier excepción o violación de CHECK (como C + R > E), hace ROLLBACK automático.
    """
    with _WRITE_LOCK:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()


def init_and_seed_db(reset: bool = False):
    """Inicializa el esquema físico y carga las 5 Dark Stores y productos semilla (Hito C1)."""
    with _WRITE_LOCK:
        if reset and DB_PATH.exists():
            DB_PATH.unlink()
        conn = get_connection()
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute("BEGIN IMMEDIATE;")
            count = conn.execute("SELECT COUNT(*) FROM dark_store").fetchone()[0]
            if count == 0:
                now = round(time.time(), 3)
                stores = [
                    ("DS-NORTE",    "DS-01", "Dark Store Norte (Satélite)",    "Naucalpan / Satélite"),
                    ("DS-SUR",      "DS-02", "Dark Store Sur (Coyoacán)",      "Coyoacán / Del Valle"),
                    ("DS-CENTRO",   "DS-03", "Dark Store Centro (Reforma)",    "Cuauhtémoc / Juárez"),
                    ("DS-PONIENTE", "DS-04", "Dark Store Poniente (Polanco)",  "Miguel Hidalgo"),
                    ("DS-ORIENTE",  "DS-05", "Dark Store Oriente (Iztacalco)", "Iztacalco / Venustiano"),
                ]
                conn.executemany(
                    "INSERT INTO dark_store (dark_store_id, codigo_tienda, nombre, zona_cobertura) VALUES (?, ?, ?, ?)",
                    stores,
                )
                skus = [
                    ("SKU-AGUA-01",  "750100000001", "Agua Mineral 600ml (Última Unidad AT-01)", "Bebidas",   18.00),
                    ("SKU-CAFE-02",  "750100000002", "Café de Grano 500g (TTL 299s/300s AT-02)", "Abarrotes", 145.00),
                    ("SKU-JUGO-03",  "750100000003", "Jugo de Naranja 1L (Discrepancia 10 vs 8)","Bebidas",   32.00),
                    ("SKU-LECHE-04", "750100000004", "Leche Entera 1L",                          "Lácteos",   28.00),
                    ("SKU-PAN-05",   "750100000005", "Pan Artesanal",                            "Panadería", 55.00),
                ]
                conn.executemany(
                    "INSERT INTO producto_sku (sku_id, codigo_barras, nombre, categoria, precio_unitario_vigente) VALUES (?, ?, ?, ?, ?)",
                    skus,
                )
                stock_inicial_norte = {
                    "SKU-AGUA-01": 1,   # E = 1 para AT-01 (Última unidad concurrente)
                    "SKU-CAFE-02": 5,   # E = 5 para AT-02 (Expiración 299s vs 300s)
                    "SKU-JUGO-03": 10,  # E = 10 para AT-07 (Discrepancia 10 vs 8)
                    "SKU-LECHE-04": 10,
                    "SKU-PAN-05": 10,
                }
                for st_id, _, _, _ in stores:
                    for sku_id, _, _, _, _ in skus:
                        qty = stock_inicial_norte[sku_id] if st_id == "DS-NORTE" else 8
                        inv_id = f"INV-{st_id}-{sku_id}"
                        conn.execute(
                            "INSERT INTO inventario_tienda (inventario_id, sku_id, dark_store_id, existencia_e, reservado_r, comprometido_c, oculto_h) VALUES (?, ?, ?, ?, 0, 0, 0)",
                            (inv_id, sku_id, st_id, qty),
                        )
                        conn.execute(
                            "INSERT INTO movimiento_inventario (movimiento_id, inventario_id, usuario_id, tipo_movimiento, delta_e, delta_r, delta_c, delta_h, correlation_id, motivo_detalle, registrado_epoch) VALUES (?, ?, 'SYSTEM-SEED', 'INGRESO_INICIAL', ?, 0, 0, 0, 'SEED-INIT', 'Carga inicial verificada', ?)",
                            (f"MOV-INIT-{inv_id}", inv_id, qty, now),
                        )
            conn.execute("COMMIT;")
        finally:
            conn.close()
            