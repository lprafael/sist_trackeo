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
    port = 8000
    
    print("\n" + "=" * 65)
    print(" >>> SISTEMA DE TRACKEO DE ITINERARIOS Y GENERADOR DE SHAPES <<<")
    print("=" * 65)
    print(f" Servidor iniciado en puerto {port}")
    print(f"  * Panel de Administracion : http://localhost:{port}/admin")
    print(f"  * Acceso desde Movil / LAN: http://{lan_ip}:{port}/admin")
    print(f"  * Impresion de Codigos QR : http://{lan_ip}:{port}/qrs")
    print(f"  * WebApp de Chofer (Movil): http://{lan_ip}:{port}/driver")
    print("=" * 65 + "\n")
    
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)

