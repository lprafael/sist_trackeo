import os
import uuid
import socket
import io
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Request, HTTPException, Response, Query, Depends, Form, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

import qrcode
import qrcode.image.svg

from .database import get_db, init_db
from .auth import (
    hash_password,
    verify_password,
    create_session_token,
    decode_session_token,
    is_google_oauth_configured,
    get_google_auth_url,
    exchange_google_code,
    ADMIN_DEFAULT_USER,
    ADMIN_DEFAULT_PASS
)
from .models import (
    ServiceStartRequest,
    GPSBatchUpload,
    ServiceFinishRequest,
    CheckpointCreate
)
from .services import (
    calculate_service_metrics,
    format_duration,
    generate_shapefile_zip,
    generate_geojson,
    generate_kml,
    generate_gpx,
    generate_csv
)

# Inicializar Base de Datos
init_db()

app = FastAPI(
    title="Sistema de Trackeo de Itinerarios de Buses",
    description="Generación de trazados Shapefile/GeoJSON y control de horarios mediante códigos QR de Salida y Llegada",
    version="1.0.0"
)

# Habilitar CORS para permitir llamadas desde dispositivos móviles en la red local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

COOKIE_NAME = "trackeo_session"

# Usuario por defecto para acceso público libre sin contraseña
DEFAULT_ADMIN_USER = {
    "uid": "usr_admin_public",
    "role": "admin",
    "name": "Administrador",
    "email": "admin@mopc.gov.py",
    "avatar": "",
    "pin": ""
}

def get_base_path(request: Request) -> str:
    """Detecta el prefijo base de URL para soportar subrutas como /monitoreo_vmt/trackeo o /trackeo"""
    prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    if prefix:
        return prefix
    env_prefix = os.getenv("BASE_PATH", "").rstrip("/")
    if env_prefix:
        return env_prefix
    root_path = request.scope.get("root_path", "").rstrip("/")
    if root_path:
        return root_path
    return ""

def get_lan_ip() -> str:
    """Detecta la dirección IP de la máquina en la red local (para generar QRs escaneables por móviles)"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def get_current_user(request: Request) -> Optional[dict]:
    """Obtiene el usuario autenticado a partir de la cookie de sesión o encabezado Bearer.
    Si no hay sesión iniciada, asigna automáticamente el perfil de Administrador para acceso libre sin contraseña."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    user = decode_session_token(token)
    if user:
        return user
    # Modo acceso libre sin contraseña
    return DEFAULT_ADMIN_USER

def require_admin_auth(request: Request) -> Optional[dict]:
    """Verifica si el usuario es administrador. En modo de acceso libre, siempre retorna el usuario activo."""
    return get_current_user(request)

def render_template(request: Request, name: str, context: Optional[dict] = None, status_code: int = 200):
    """Renderiza una plantilla Jinja2 inyectando automáticamente base_path, user y lan_ip"""
    ctx = dict(context) if context else {}
    base_path = get_base_path(request)
    ctx["base_path"] = base_path
    ctx["request"] = request
    if "user" not in ctx:
        ctx["user"] = get_current_user(request)
    if "lan_ip" not in ctx:
        ctx["lan_ip"] = get_lan_ip()
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=ctx,
        status_code=status_code
    )


# ==========================================
# RUTAS DE AUTENTICACIÓN (LOGIN / LOGOUT / GOOGLE)
# ==========================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: Optional[str] = None, error: Optional[str] = None):
    base_path = get_base_path(request)
    target = next if next else f"{base_path}/admin"
    return render_template(
        request,
        "login.html",
        {
            "next": target,
            "error": error,
            "google_configured": is_google_oauth_configured(),
            "user": None
        }
    )

@app.post("/auth/login-admin")
async def login_admin(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None)
):
    """Inicio de sesión local para administradores"""
    clean_user = username.strip()
    clean_pass = password.strip()
    base_path = get_base_path(request)
    target_next = next if next else f"{base_path}/admin"
    
    auth_ok = False
    admin_name = "Administrador Principal"
    admin_id = "usr_admin_default"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE role = 'admin' AND (email = ? OR id = ?)", (clean_user, clean_user))
        user_row = cursor.fetchone()
        
        if user_row and user_row["password_hash"]:
            if verify_password(clean_pass, user_row["password_hash"]):
                auth_ok = True
                admin_name = user_row["name"]
                admin_id = user_row["id"]
        elif clean_user == ADMIN_DEFAULT_USER and clean_pass == ADMIN_DEFAULT_PASS:
            auth_ok = True

    if not auth_ok:
        return render_template(
            request,
            "login.html",
            {
                "next": target_next,
                "error": "Usuario o contraseña de administrador incorrectos.",
                "google_configured": is_google_oauth_configured(),
                "user": None
            }
        )

    token = create_session_token(
        user_id=admin_id,
        role="admin",
        name=admin_name,
        email="admin@flotabuses.com"
    )

    resp = RedirectResponse(url=target_next, status_code=status.HTTP_302_FOUND)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, max_age=14*86400, samesite="lax")
    return resp

@app.post("/auth/login-driver")
async def login_driver(
    request: Request,
    pin_code: str = Form(...),
    next: Optional[str] = Form(None)
):
    """Inicio de sesión rápido de chofer por código de legajo / PIN"""
    clean_pin = pin_code.strip()
    base_path = get_base_path(request)
    target_next = next if next else f"{base_path}/driver"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE pin_code = ? AND role = 'driver' AND is_active = 1", (clean_pin,))
        driver_row = cursor.fetchone()

    if not driver_row:
        return render_template(
            request,
            "login.html",
            {
                "next": target_next,
                "error": f"No se encontró ningún chofer con el código o PIN '{clean_pin}'. Verifique su número de legajo.",
                "google_configured": is_google_oauth_configured(),
                "user": None
            }
        )

    token = create_session_token(
        user_id=driver_row["id"],
        role="driver",
        name=driver_row["name"],
        email=driver_row["email"] or "",
        pin_code=driver_row["pin_code"]
    )

    resp = RedirectResponse(url=target_next, status_code=status.HTTP_302_FOUND)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, max_age=14*86400, samesite="lax")
    return resp

@app.get("/auth/google/login")
async def google_login(request: Request, state: Optional[str] = None):
    """Inicia el flujo de autenticación con Google OAuth"""
    base_path = get_base_path(request)
    target_state = state or f"{base_path}/admin"
    if not is_google_oauth_configured():
        return RedirectResponse(url=f"{base_path}/login?error=Google+OAuth+no+esta+configurado+en+el+servidor", status_code=status.HTTP_302_FOUND)
    
    redirect_uri = f"{str(request.base_url).rstrip('/')}{base_path}/auth/google/callback"
    google_url = get_google_auth_url(redirect_uri, state=target_state)
    return RedirectResponse(url=google_url, status_code=status.HTTP_302_FOUND)

@app.get("/auth/google/callback")
async def google_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Recibe la respuesta de Google OAuth y crea la sesión del usuario"""
    base_path = get_base_path(request)
    dest_default = f"{base_path}/admin"
    if error or not code:
        return RedirectResponse(url=f"{base_path}/login?error=Inicio+con+Google+cancelado+o+fallido", status_code=status.HTTP_302_FOUND)

    redirect_uri = f"{str(request.base_url).rstrip('/')}{base_path}/auth/google/callback"
    google_user = await exchange_google_code(code, redirect_uri)
    
    if not google_user or "email" not in google_user:
        return RedirectResponse(url=f"{base_path}/login?error=No+se+pudo+obtener+el+perfil+de+Google", status_code=status.HTTP_302_FOUND)

    email = google_user["email"]
    name = google_user.get("name") or email.split("@")[0]
    google_sub = google_user.get("id") or google_user.get("sub")
    avatar = google_user.get("picture") or ""

    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    role = "driver"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE google_sub = ? OR email = ?", (google_sub, email))
        existing = cursor.fetchone()

        if existing:
            user_id = existing["id"]
            role = existing["role"]
            cursor.execute("UPDATE users SET avatar_url = ?, name = ? WHERE id = ?", (avatar, name, user_id))
        else:
            if "admin" in email.lower():
                role = "admin"
            cursor.execute("""
                INSERT INTO users (id, role, name, email, google_sub, avatar_url)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, role, name, email, google_sub, avatar))

    token = create_session_token(
        user_id=user_id,
        role=role,
        name=name,
        email=email,
        avatar_url=avatar
    )

    dest = state if state else (f"{base_path}/admin" if role == "admin" else f"{base_path}/driver")
    resp = RedirectResponse(url=dest, status_code=status.HTTP_302_FOUND)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, max_age=14*86400, samesite="lax")
    return resp

@app.get("/logout")
async def logout(request: Request, next: Optional[str] = None):
    """Cierra la sesión y borra la cookie"""
    base_path = get_base_path(request)
    dest = next or f"{base_path}/"
    resp = RedirectResponse(url=dest, status_code=status.HTTP_302_FOUND)
    resp.delete_cookie(COOKIE_NAME)
    return resp

@app.get("/api/me")
async def get_me(request: Request):
    """Retorna información del usuario actualmente autenticado"""
    user = get_current_user(request)
    if not user:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user}


# ==========================================
# RUTAS DE INTERFAZ WEB (HTML - ACCESO LIBRE)
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Vista principal: Panel de monitoreo de itinerarios accesible directamente sin contraseña"""
    return render_template(request, "admin.html", {"page": "admin"})

@app.get("/admin", response_class=HTMLResponse)
async def admin_view(request: Request):
    """Panel de Administración y Monitoreo satelital en vivo"""
    return render_template(request, "admin.html", {"page": "admin"})

@app.get("/driver", response_class=HTMLResponse)
async def driver_view(
    request: Request,
    action: Optional[str] = "salida", # salida o llegada
    code: Optional[str] = None,
    terminal: Optional[str] = None
):
    """Interfaz móvil para el chofer al escanear QR de salida o llegada"""
    return render_template(
        request,
        "driver.html",
        {
            "page": "driver",
            "action": action,
            "code": code,
            "terminal": terminal or ("Terminal de Salida" if action == "salida" else "Terminal de Llegada"),
        }
    )

@app.get("/qr", include_in_schema=False)
async def qr_alias(request: Request):
    base_path = get_base_path(request)
    return RedirectResponse(url=f"{base_path}/qrs", status_code=status.HTTP_302_FOUND)

@app.get("/qrs", response_class=HTMLResponse)
async def qrs_view(request: Request):
    """Página para generar e imprimir los códigos QR de Salida y Llegada"""
    return render_template(request, "qrs.html", {"page": "qrs"})

@app.get("/itinerario/{service_id}", response_class=HTMLResponse)
async def itinerary_detail_view(request: Request, service_id: str):
    """Página interactiva de detalle de un itinerario con visor de shape y métricas"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Itinerario no encontrado")
        
        service_dict = dict(srv)
        service_dict["duration_formatted"] = format_duration(service_dict.get("total_duration_sec") or 0)
        
        cursor.execute("SELECT COUNT(*) as count FROM gps_points WHERE service_id = ?", (service_id,))
        p_count = cursor.fetchone()["count"]

    return render_template(
        request,
        "detail.html",
        {
            "page": "detail",
            "service": service_dict,
            "points_count": p_count,
        }
    )


# ==========================================
# RUTAS DE API - TELEMETRÍA Y SERVICIOS
# ==========================================

@app.get("/api/server-info")
async def server_info(request: Request):
    """Retorna información del servidor e IP de red local para configurar la base de los QRs"""
    lan_ip = get_lan_ip()
    port = request.url.port or 8014
    base_path = get_base_path(request)
    host_header = request.headers.get("host") or f"{lan_ip}:{port}"
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return {
        "lan_ip": lan_ip,
        "port": port,
        "base_path": base_path,
        "default_base_url": f"{proto}://{host_header}{base_path}",
        "current_request_url": f"{proto}://{host_header}{base_path}"
    }

@app.post("/api/services/start")
async def start_service(payload: ServiceStartRequest, request: Request):
    """Registra la salida del bus e inicia el seguimiento del itinerario"""
    service_id = str(uuid.uuid4())
    now_iso = datetime.now().isoformat()
    
    current_u = get_current_user(request)
    assigned_user_id = payload.user_id or (current_u["uid"] if current_u else None)
    assigned_driver_name = (current_u["name"] if (current_u and current_u.get("role") == "driver") else (payload.driver_name or "Chofer")).strip()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO services (
                id, bus_number, driver_name, line_name, origin_name,
                start_time, status, points_count, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', 0, ?)
        """, (
            service_id,
            payload.bus_number.strip().upper(),
            assigned_driver_name,
            (payload.line_name or "Línea Principal").strip(),
            (payload.origin_name or "Terminal de Salida").strip(),
            now_iso,
            assigned_user_id
        ))

        # Si se envió ubicación inicial
        if payload.initial_location:
            loc = payload.initial_location
            cursor.execute("""
                INSERT INTO gps_points (
                    service_id, latitude, longitude, altitude, speed_kmh,
                    accuracy, heading, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                service_id,
                loc.latitude,
                loc.longitude,
                loc.altitude,
                loc.speed_kmh or 0.0,
                loc.accuracy,
                loc.heading,
                loc.timestamp or now_iso
            ))
            cursor.execute("UPDATE services SET points_count = 1 WHERE id = ?", (service_id,))

    return {
        "success": True,
        "service_id": service_id,
        "bus_number": payload.bus_number.strip().upper(),
        "start_time": now_iso,
        "status": "active",
        "message": f"Servicio iniciado con éxito para el Bus {payload.bus_number}"
    }

@app.post("/api/services/telemetry")
async def receive_telemetry(payload: GPSBatchUpload):
    """Recibe paquetes de coordenadas GPS desde el celular del chofer"""
    if not payload.points:
        return {"success": True, "saved": 0}

    with get_db() as conn:
        cursor = conn.cursor()
        
        # Verificar estado del servicio
        cursor.execute("SELECT status, start_time FROM services WHERE id = ?", (payload.service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
        if srv["status"] != "active":
            return {"success": False, "status": srv["status"], "message": "El servicio ya no está activo"}

        # Insertar lote de puntos
        rows = [
            (
                payload.service_id,
                p.latitude,
                p.longitude,
                p.altitude,
                p.speed_kmh or 0.0,
                p.accuracy,
                p.heading,
                p.timestamp
            )
            for p in payload.points
        ]
        
        cursor.executemany("""
            INSERT INTO gps_points (
                service_id, latitude, longitude, altitude, speed_kmh,
                accuracy, heading, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

        # Actualizar conteo de puntos y métricas preliminares
        cursor.execute("SELECT * FROM gps_points WHERE service_id = ? ORDER BY id ASC", (payload.service_id,))
        all_pts = [dict(r) for r in cursor.fetchall()]
        
        metrics = calculate_service_metrics(all_pts, srv["start_time"], None)
        
        cursor.execute("""
            UPDATE services SET
                points_count = ?,
                total_distance_km = ?,
                avg_speed_kmh = ?,
                max_speed_kmh = ?
            WHERE id = ?
        """, (
            metrics["points_count"],
            metrics["total_distance_km"],
            metrics["avg_speed_kmh"],
            metrics["max_speed_kmh"],
            payload.service_id
        ))

    return {
        "success": True,
        "saved": len(payload.points),
        "total_points": metrics["points_count"],
        "total_distance_km": metrics["total_distance_km"]
    }

@app.post("/api/services/finish")
async def finish_service(payload: ServiceFinishRequest):
    """Registra la llegada del bus al escanear el QR de llegada y finaliza el itinerario"""
    now_iso = payload.timestamp or datetime.now().isoformat()
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (payload.service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
        service_dict = dict(srv)

        # Si se envió punto GPS final
        if payload.final_location:
            loc = payload.final_location
            cursor.execute("""
                INSERT INTO gps_points (
                    service_id, latitude, longitude, altitude, speed_kmh,
                    accuracy, heading, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                payload.service_id,
                loc.latitude,
                loc.longitude,
                loc.altitude,
                loc.speed_kmh or 0.0,
                loc.accuracy,
                loc.heading,
                loc.timestamp or now_iso
            ))

        # Recuperar todos los puntos GPS para calcular métricas completas
        cursor.execute("SELECT * FROM gps_points WHERE service_id = ? ORDER BY id ASC", (payload.service_id,))
        all_pts = [dict(r) for r in cursor.fetchall()]

        dest_name = (payload.destination_name or service_dict.get("destination_name") or "Terminal de Llegada").strip()
        metrics = calculate_service_metrics(all_pts, service_dict["start_time"], now_iso)

        cursor.execute("""
            UPDATE services SET
                end_time = ?,
                destination_name = ?,
                status = 'completed',
                total_distance_km = ?,
                total_duration_sec = ?,
                avg_speed_kmh = ?,
                max_speed_kmh = ?,
                points_count = ?
            WHERE id = ?
        """, (
            now_iso,
            dest_name,
            metrics["total_distance_km"],
            metrics["total_duration_sec"],
            metrics["avg_speed_kmh"],
            metrics["max_speed_kmh"],
            metrics["points_count"],
            payload.service_id
        ))

        # Generar y persistir inmediatamente los archivos Shapefile en exports/shapes/
        try:
            srv_final = {**service_dict, **metrics, "end_time": now_iso, "destination_name": dest_name}
            generate_shapefile_zip(srv_final, all_pts)
        except Exception as err:
            print(f"Aviso al auto-guardar Shapefile al finalizar: {err}")

    return {
        "success": True,
        "service_id": payload.service_id,
        "status": "completed",
        "start_time": service_dict["start_time"],
        "end_time": now_iso,
        "duration_formatted": format_duration(metrics["total_duration_sec"]),
        "total_distance_km": metrics["total_distance_km"],
        "avg_speed_kmh": metrics["avg_speed_kmh"],
        "points_count": metrics["points_count"],
        "message": f"Servicio completado exitosamente para el Bus {service_dict['bus_number']}"
    }

@app.post("/api/services/{service_id}/cancel")
async def cancel_service(service_id: str):
    """Cancela un servicio activo"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE services SET status = 'cancelled' WHERE id = ?", (service_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return {"success": True, "message": "Servicio cancelado"}

@app.get("/api/services/active")
async def get_active_services():
    """Retorna todos los buses que están actualmente en recorrido con su última posición"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, 
                   g.latitude as last_lat, 
                   g.longitude as last_lon, 
                   g.speed_kmh as last_speed,
                   g.recorded_at as last_ping
            FROM services s
            LEFT JOIN (
                SELECT gp1.*
                FROM gps_points gp1
                INNER JOIN (
                    SELECT service_id, MAX(id) as max_id
                    FROM gps_points
                    GROUP BY service_id
                ) gp2 ON gp1.id = gp2.max_id
            ) g ON s.id = g.service_id
            WHERE s.status = 'active'
            ORDER BY s.start_time DESC
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        
        now_utc = datetime.utcnow()
        for r in rows:
            duration_sec = 0
            if r.get("start_time"):
                try:
                    s_dt = datetime.fromisoformat(r["start_time"].replace("Z", "+00:00"))
                    if s_dt.tzinfo is not None:
                        s_dt = s_dt.astimezone().replace(tzinfo=None)
                    duration_sec = max(0, int((now_utc - s_dt).total_seconds()))
                except Exception:
                    duration_sec = 0
            r["duration_formatted"] = format_duration(duration_sec)

    return {"active_services": rows}

@app.get("/api/services")
async def list_services(
    bus: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """Lista todos los servicios con filtros"""
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM services WHERE 1=1"
        params = []

        if bus:
            query += " AND bus_number LIKE ?"
            params.append(f"%{bus.strip()}%")
        if status:
            query += " AND status = ?"
            params.append(status.strip())

        query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]

        for r in rows:
            r["duration_formatted"] = format_duration(r.get("total_duration_sec") or 0)

        cursor.execute("SELECT COUNT(*) as total FROM services")
        total = cursor.fetchone()["total"]

    return {"total": total, "services": rows}

@app.get("/api/services/{service_id}")
async def get_service_detail(service_id: str):
    """Retorna los datos del servicio y todos sus puntos GPS"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")

        cursor.execute("SELECT * FROM gps_points WHERE service_id = ? ORDER BY id ASC", (service_id,))
        points = [dict(r) for r in cursor.fetchall()]

    service_dict = dict(srv)
    service_dict["duration_formatted"] = format_duration(service_dict.get("total_duration_sec") or 0)

    return {
        "service": service_dict,
        "points": points
    }


# ==========================================
# RUTAS DE EXPORTACIÓN DE SHAPES Y FORMATOS GIS
# ==========================================

@app.get("/api/services/{service_id}/shapefile")
async def export_shapefile(service_id: str):
    """Genera y descarga el archivo ZIP que contiene el ESRI Shapefile (.shp, .shx, .dbf, .prj)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
        cursor.execute("SELECT * FROM gps_points WHERE service_id = ? ORDER BY id ASC", (service_id,))
        points = [dict(r) for r in cursor.fetchall()]

    service_dict = dict(srv)
    zip_bytes = generate_shapefile_zip(service_dict, points)
    
    clean_bus = "".join(c for c in service_dict.get("bus_number", "bus") if c.isalnum() or c in ("-", "_"))
    filename = f"shapefile_itinerario_bus_{clean_bus}_{service_id[:8]}.zip"
    
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/services/{service_id}/geojson")
async def export_geojson(service_id: str):
    """Descarga el trazado en formato GeoJSON FeatureCollection"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
        cursor.execute("SELECT * FROM gps_points WHERE service_id = ? ORDER BY id ASC", (service_id,))
        points = [dict(r) for r in cursor.fetchall()]

    data = generate_geojson(dict(srv), points)
    clean_bus = "".join(c for c in dict(srv).get("bus_number", "bus") if c.isalnum() or c in ("-", "_"))
    filename = f"itinerario_bus_{clean_bus}_{service_id[:8]}.geojson"

    return Response(
        content=JSONResponse(content=data).body,
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/services/{service_id}/kml")
async def export_kml(service_id: str):
    """Descarga el recorrido en formato KML para Google Earth"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
        cursor.execute("SELECT * FROM gps_points WHERE service_id = ? ORDER BY id ASC", (service_id,))
        points = [dict(r) for r in cursor.fetchall()]

    kml_str = generate_kml(dict(srv), points)
    clean_bus = "".join(c for c in dict(srv).get("bus_number", "bus") if c.isalnum() or c in ("-", "_"))
    filename = f"itinerario_bus_{clean_bus}_{service_id[:8]}.kml"

    return Response(
        content=kml_str.encode("utf-8"),
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/services/{service_id}/gpx")
async def export_gpx(service_id: str):
    """Descarga el recorrido en formato GPX para GPS y software de navegación"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
        cursor.execute("SELECT * FROM gps_points WHERE service_id = ? ORDER BY id ASC", (service_id,))
        points = [dict(r) for r in cursor.fetchall()]

    gpx_str = generate_gpx(dict(srv), points)
    clean_bus = "".join(c for c in dict(srv).get("bus_number", "bus") if c.isalnum() or c in ("-", "_"))
    filename = f"itinerario_bus_{clean_bus}_{service_id[:8]}.gpx"

    return Response(
        content=gpx_str.encode("utf-8"),
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/services/{service_id}/csv")
async def export_csv(service_id: str):
    """Descarga la planilla CSV con todos los waypoints y marcas de tiempo"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        srv = cursor.fetchone()
        if not srv:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
        cursor.execute("SELECT * FROM gps_points WHERE service_id = ? ORDER BY id ASC", (service_id,))
        points = [dict(r) for r in cursor.fetchall()]

    csv_str = generate_csv(dict(srv), points)
    clean_bus = "".join(c for c in dict(srv).get("bus_number", "bus") if c.isalnum() or c in ("-", "_"))
    filename = f"itinerario_bus_{clean_bus}_{service_id[:8]}.csv"

    return Response(
        content=csv_str.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ==========================================
# GESTIÓN Y GENERACIÓN DE CÓDIGOS QR
# ==========================================

@app.get("/api/checkpoints")
async def list_checkpoints():
    """Lista todos los terminales y puntos de control registrados"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM checkpoints ORDER BY type DESC, name ASC")
        rows = [dict(r) for r in cursor.fetchall()]
    return {"checkpoints": rows}

@app.post("/api/checkpoints")
async def create_checkpoint(item: CheckpointCreate):
    """Crea una nueva estación o punto de control para QR"""
    chk_id = f"chk_{uuid.uuid4().hex[:8]}"
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO checkpoints (id, name, type, code, description, latitude, longitude)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                chk_id,
                item.name.strip(),
                item.type.strip().lower(),
                item.code.strip().upper(),
                item.description,
                item.latitude,
                item.longitude
            ))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Código de punto ya existe o inválido: {str(e)}")
    return {"success": True, "id": chk_id}

@app.get("/api/qr")
async def generate_qr_image(
    data: str = Query(..., description="Texto o URL que codificará el QR"),
    format: str = Query("svg", description="Formato de salida: svg o png"),
    size: int = Query(10, description="Tamaño de caja QR")
):
    """Genera dinámicamente una imagen de código QR en formato SVG o PNG de alta fidelidad"""
    if format.lower() == "svg":
        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(data, image_factory=factory, box_size=size)
        svg_content = img.to_string(encoding="unicode")
        return Response(content=svg_content, media_type="image/svg+xml")
    else:
        # Formato PNG
        qr = qrcode.QRCode(box_size=size, border=2)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")
