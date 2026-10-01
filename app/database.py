import sqlite3
import os
from contextlib import contextmanager
from typing import Generator

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trackeo.db")

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Tabla de servicios / viajes de buses
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            bus_number TEXT NOT NULL,
            driver_name TEXT,
            line_name TEXT,
            origin_name TEXT DEFAULT 'Terminal Origen',
            destination_name TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            status TEXT NOT NULL DEFAULT 'active', -- active, completed, cancelled
            total_distance_km REAL DEFAULT 0.0,
            total_duration_sec INTEGER DEFAULT 0,
            avg_speed_kmh REAL DEFAULT 0.0,
            max_speed_kmh REAL DEFAULT 0.0,
            points_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        );
        """)
        
        # Tabla de puntos GPS registrados durante el recorrido
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS gps_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude REAL,
            speed_kmh REAL DEFAULT 0.0,
            accuracy REAL,
            heading REAL,
            recorded_at TEXT NOT NULL,
            server_received_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
        );
        """)
        
        # Indices para acelerar consultas de mapa y exportación
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gps_service_id ON gps_points(service_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gps_recorded_at ON gps_points(recorded_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_status ON services(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_bus ON services(bus_number);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_dates ON services(start_time, end_time);")

        # Tabla de terminales / paradas para generación de QRs
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL, -- salida, llegada, intermedio
            code TEXT UNIQUE NOT NULL,
            description TEXT,
            latitude REAL,
            longitude REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Tabla de usuarios (Administradores y Choferes)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'driver', -- admin o driver
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            pin_code TEXT UNIQUE,
            password_hash TEXT,
            avatar_url TEXT,
            google_sub TEXT UNIQUE,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_pin ON users(pin_code);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")

        # Intentar añadir columna user_id a services si no existe
        try:
            cursor.execute("ALTER TABLE services ADD COLUMN user_id TEXT REFERENCES users(id);")
        except Exception:
            pass # Ya existe

        # Insertar checkpoints por defecto si no existen
        cursor.execute("SELECT COUNT(*) as count FROM checkpoints")
        if cursor.fetchone()["count"] == 0:
            cursor.execute("""
                INSERT INTO checkpoints (id, name, type, code, description)
                VALUES 
                ('chk_salida_1', 'Terminal de Salida (Base)', 'salida', 'SALIDA_PRINCIPAL', 'Punto de partida del servicio de buses'),
                ('chk_llegada_1', 'Terminal de Llegada (Destino)', 'llegada', 'LLEGADA_PRINCIPAL', 'Punto de destino final del servicio de buses')
            """)

        # Insertar usuario Administrador por defecto si no existe
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'admin'")
        if cursor.fetchone()["count"] == 0:
            from .auth import hash_password, ADMIN_DEFAULT_USER, ADMIN_DEFAULT_PASS
            admin_pwd_hash = hash_password(ADMIN_DEFAULT_PASS)
            cursor.execute("""
                INSERT INTO users (id, role, name, email, password_hash)
                VALUES ('usr_admin_default', 'admin', 'Administrador Principal', 'admin@flotabuses.com', ?)
            """, (admin_pwd_hash,))

        # Insertar choferes de ejemplo con PIN si no existen
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'driver'")
        if cursor.fetchone()["count"] == 0:
            cursor.execute("""
                INSERT INTO users (id, role, name, pin_code)
                VALUES 
                ('drv_101', 'driver', 'Carlos Giménez', '101'),
                ('drv_102', 'driver', 'Ramón Benítez', '102'),
                ('drv_103', 'driver', 'Jorge Duarte', '103'),
                ('drv_104', 'driver', 'Miguel Ángel Acosta', '104'),
                ('drv_105', 'driver', 'Víctor Hugo Silva', '105')
            """)
