import os
import hmac
import hashlib
import base64
import json
import time
from typing import Optional, Dict, Any
from urllib.parse import urlencode
import httpx
from dotenv import load_dotenv

# Cargar variables de entorno desde .env si existe
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "trackeo_buses_super_secret_key_2026")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
ADMIN_DEFAULT_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_DEFAULT_PASS = os.getenv("ADMIN_PASSWORD", "admin123")

def hash_password(password: str) -> str:
    """Genera hash seguro PBKDF2-HMAC-SHA256 con salt aleatorio."""
    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return f"{salt.hex()}${pwd_hash.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Verifica si la contraseña coincide con el hash almacenado."""
    try:
        salt_hex, hash_hex = stored_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
        computed_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return hmac.compare_digest(computed_hash, expected_hash)
    except Exception:
        return False

def create_session_token(user_id: str, role: str, name: str, email: str = "", avatar_url: str = "", pin_code: str = "", expires_days: int = 14) -> str:
    """Crea un token de sesión firmado criptográficamente con HMAC-SHA256."""
    payload = {
        "uid": user_id,
        "role": role, # 'admin' o 'driver'
        "name": name,
        "email": email,
        "avatar": avatar_url,
        "pin": pin_code,
        "exp": int(time.time()) + (expires_days * 86400)
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"

def decode_session_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Verifica la firma y expiración del token de sesión."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            return None
        
        # Rellenar padding para base64 si es necesario
        padding = len(payload_b64) % 4
        if padding > 0:
            payload_b64 += "=" * (4 - padding)
        
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return None # Expirado
        return payload
    except Exception:
        return None

def is_google_oauth_configured() -> bool:
    """Indica si las credenciales de Google OAuth están configuradas."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

def get_google_auth_url(redirect_uri: str, state: str = "admin") -> str:
    """Construye la URL de redirección hacia Google Sign-In."""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": state
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

async def exchange_google_code(code: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
    """Intercambia el código de autorización por los datos del usuario en Google."""
    if not is_google_oauth_configured():
        return None
    
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(token_url, data=token_data)
        if token_resp.status_code != 200:
            return None
        
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            return None
        
        userinfo_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo_resp.status_code != 200:
            return None
        
        return userinfo_resp.json()
