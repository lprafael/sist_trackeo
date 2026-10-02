import os
import sys
import socket
import uvicorn

# Configurar salida de consola a UTF-8 para Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    lan_ip = get_lan_ip()
    port = int(os.getenv("PORT", 8014))
    base_path = os.getenv("BASE_PATH", "")
    
    print("\n" + "=" * 65)
    print(" >>> SISTEMA DE TRACKEO DE ITINERARIOS Y GENERADOR DE SHAPES <<<")
    print("=" * 65)
    print(f" Servidor iniciado en puerto {port}")
    if base_path:
        print(f"  * Ruta base configurada   : {base_path}")
    print(f"  * Panel de Monitoreo      : http://localhost:{port}{base_path}/admin")
    print(f"  * Acceso desde Movil / LAN: http://{lan_ip}:{port}{base_path}/admin")
    print(f"  * Impresion de Codigos QR : http://{lan_ip}:{port}{base_path}/qrs")
    print(f"  * WebApp de Chofer (Movil): http://{lan_ip}:{port}{base_path}/driver")
    print("=" * 65 + "\n")
    
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)

