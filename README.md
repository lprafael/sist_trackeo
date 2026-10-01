# 🚍 Sistema de Trackeo de Itinerarios y Generador de Shapes GPS para Buses

Aplicación web integral para el **relevamiento de itinerarios de buses**, cálculo exacto de **horarios de salida y llegada**, tiempos de viaje, distancias y **generación automática de trazados espaciales (Shapefile `.shp`, GeoJSON, KML, GPX y CSV)** mediante códigos **QR**.

---

## 💡 ¿Cómo funciona el Sistema?

```
 [QR DE SALIDA]                     [EN TRÁNSITO]                     [QR DE LLEGADA]
 (Terminal Origen)               (GPS Celular Chofer)               (Terminal Destino)
        │                                 │                                  │
        ▼                                 ▼                                  ▼
1. Chofer escanea QR           2. WebApp graba ruta:              3. Chofer escanea QR:
   con su celular.                • Coordenadas GPS (WGS84)          • Fija horario de llegada
   Ingresa:                       • Velocidad y altitud              • Calcula tiempo total
   - Nº de Bus                    • Buffer offline (sin señal)       • Calcula distancia (km)
   - Chofer / Línea               • Pantalla activa (WakeLock)       • Genera SHAPEFILE (.zip)
```

1. **Punto de Salida**: En la terminal o cabecera se coloca el cartel impreso del **QR de Salida**.
2. **Inicio del Servicio**: El chofer escanea el QR con la cámara de su celular. Se abre la WebApp en el navegador del teléfono y se le solicita ingresar el **Número de Bus** (ej. *Bus 42* o *Coche 105*).
3. **Seguimiento en Vivo**:
   - Al pulsar *Iniciar*, se registra el **horario de salida exacto** (timestamp de servidor y GPS).
   - El celular activa el **Wake Lock** (evita que la pantalla se apague y el sistema operativo suspenda el GPS) y empieza a capturar waypoints cada segundo con alta precisión.
   - En pantalla el chofer ve su velocímetro digital, tiempo transcurrido, distancia recorrida y un mini-mapa en tiempo real.
   - **Tolerancia a pérdida de señal móvil (Offline-first)**: Si el bus pasa por zonas rurales o túneles sin cobertura 4G, los puntos se almacenan localmente en el teléfono (`localStorage` / cola en memoria) y se sincronizan automáticamente con el servidor apenas recupera conexión.
4. **Punto de Llegada**: Al arribar a la terminal de destino, el chofer escanea el **QR de Llegada** (con la cámara integrada en la WebApp o con la cámara de su celular):
   - Se fija el **horario de llegada exacto**.
   - Se calcula la **duración total del viaje** y la **velocidad media/máxima**.
   - Se genera el **trazado espacial del itinerario** listo para descargar.
5. **Panel de Monitoreo (Admin)**:
   - Mapa interactivo en tiempo real con todos los buses en tránsito.
   - Tabla histórica con filtros por número de bus y estado.
   - Descarga directa de **Shapefile ESRI (.zip con .shp, .shx, .dbf, .prj WGS84)**, **GeoJSON**, **KML** (Google Earth), **GPX** y **CSV**.

---

## 🔐 Sistema de Autenticación Híbrido (Google OAuth + PIN Chofer + Admin)

El sistema cuenta con tres métodos integrados de acceso:

1. **Para Administradores (Panel `/admin`)**:
   - Usuario y contraseña local: Usuario `admin`, Contraseña por defecto `admin123` (configurable en `.env`).
   - Protege el mapa de monitoreo, historial de viajes y descargas de shapes.

2. **Para Choferes (WebApp Móvil `/driver`)**:
   - **Inicio Rápido con PIN / Legajo**: El chofer ingresa únicamente su número de legajo (ej: `101`, `102`...). Su nombre se asocia automáticamente a la salida sin necesidad de tipear.
   - Choferes de prueba precargados: `101` (Carlos Giménez), `102` (Ramón Benítez), `103` (Jorge Duarte), `104` (Miguel Acosta), `105` (Víctor Silva).

3. **Google OAuth 2.0 (Google Sign-In)**:
   - Permite a choferes y administradores iniciar sesión con 1 toque usando su cuenta de Google.
   - Para habilitarlo en tu servidor o dominio:
     1. Ve a [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
     2. Crea un **ID de cliente de OAuth (Aplicación web)**.
     3. Agrega como URI de redirección autorizada: `http://<tu-servidor-o-dominio>:8000/auth/google/callback`.
     4. Copia tu `Client ID` y `Client Secret` en el archivo `.env`:
        ```env
        GOOGLE_CLIENT_ID=tu_cliente_id.apps.googleusercontent.com
        GOOGLE_CLIENT_SECRET=tu_cliente_secret
        ```

---

## 🛠️ Tecnologías Utilizadas

- **Backend**: Python 3.10+ / FastAPI / Uvicorn (rápido, asíncrono y liviano).
- **Base de Datos**: SQLite con modo **WAL (Write-Ahead Logging)** para alta concurrencia de lecturas y escrituras GPS.
- **Motor GIS & Shapefiles**: Librería pura `pyshp` (genera Shapefiles nativos con proyección EPSG:4326 sin requerir binarios externos de C++ o GDAL).
- **Frontend**: HTML5, Vanilla CSS moderno, Web Audio API (efectos de sonido sintetizados en el móvil) y Leaflet.js para mapas interactivos.
- **Móvil**: HTML5 Geolocation API (`enableHighAccuracy`), Screen WakeLock API y `Html5Qrcode` para escaneo de cámara.

---

## 🚀 Puesta en Marcha Rápida (Local o Servidor)

### 1. Requisitos
- Python 3.10 o superior instalado.

### 2. Instalación de Dependencias
```bash
# Crear entorno virtual (opcional pero recomendado)
python -m venv venv

# En Windows:
.\venv\Scripts\activate

# En Linux / Mac:
source venv/bin/activate

# Instalar librerías
pip install -r requirements.txt
```

### 3. Iniciar el Servidor
```bash
python run.py
```

El servidor detectará automáticamente la dirección IP local de tu máquina e imprimirá los enlaces:
- **Panel de Control / Monitoreo**: `http://localhost:8000/admin`
- **Generador e Impresión de QRs**: `http://<IP_SERVIDOR>:8000/qrs`
- **WebApp para Celulares (Chofer)**: `http://<IP_SERVIDOR>:8000/driver`

---

## 📱 Acceso desde Celulares en la Red

1. Asegúrate de que el celular del chofer esté conectado a la misma red Wi-Fi que el servidor (o configura un dominio/IP pública si el servidor está en la nube o VPS).
2. Abre en tu navegador la página de **Códigos QR** (`http://localhost:8000/qrs`).
3. Verás los dos carteles con sus QRs correspondientes listos para probar o imprimir:
   - **QR Verde (Salida)**: Apunta a `http://<IP_SERVIDOR>:8000/driver?action=salida&terminal=Terminal+Salida`
   - **QR Rojo (Llegada)**: Apunta a `http://<IP_SERVIDOR>:8000/driver?action=llegada&terminal=Terminal+Llegada`
4. Puedes hacer clic en **"Imprimir Carteles QR"** para obtener hojas en tamaño A4 con el diseño listo para pegar en las cabeceras de línea.

---

## 🗺️ Formatos de Salida del Trazado (Shapes)

Al finalizar cada servicio (o en cualquier momento desde el panel), se pueden descargar:
1. **ESRI Shapefile (.zip)**:
   - `itinerario_bus_XXX.shp`: Capa vectorial tipo `Polyline` con la geometría completa de la ruta.
   - `itinerario_bus_XXX.shx`: Índice de geometría.
   - `itinerario_bus_XXX.dbf`: Atributos (`BUS_NUM`, `CHOFER`, `LINEA`, `ORIGEN`, `DESTINO`, `F_SALIDA`, `F_LLEGADA`, `DURAC_SEG`, `DIST_KM`, `VEL_PROM`, `VEL_MAX`, `CANT_PTS`).
   - `itinerario_bus_XXX.prj`: Definición de proyección WGS84 (EPSG:4326).
   - `itinerario_bus_XXX_puntos.*`: Capa vectorial tipo `Point` con cada waypoint GPS individual y su velocidad/altitud registrada.
   - `LEAME_METADATOS.txt`: Resumen ejecutivo del servicio.
2. **GeoJSON (`.geojson`)**: Listo para importar en QGIS, ArcGIS Online, Mapbox o visores web.
3. **KML (`.kml`)**: Para visualizar el recorrido 3D directamente en Google Earth.
4. **GPX (`.gpx`)**: Estándar GPS compatible con Garmin y navegadores satelitales.
5. **CSV (`.csv`)**: Planilla con todas las lecturas de telemetría (latitud, longitud, velocidad, tiempo).

---

## 🌐 Despliegue en Servidor de Producción (Linux / VPS)

Si vas a levantar la aplicación en un servidor Linux (Ubuntu/Debian) con Nginx y dominio público:

### 1. Servicio Systemd (`/etc/systemd/system/trackeo_buses.service`)
```ini
[Unit]
Description=Servicio de Trackeo de Buses e Itinerarios
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/sist_trackeo
ExecStart=/var/www/sist_trackeo/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

### 2. Configuración Nginx con HTTPS (SSL)
> **Nota Importante para Navegadores Móviles**: La API de Geolocalización de Chrome/Safari en celulares requiere HTTPS para funcionar si no es `localhost` ni una IP privada en algunas versiones modernas de Android/iOS. Se recomienda habilitar un certificado SSL gratuito con Let's Encrypt (`certbot`).

```nginx
server {
    server_name trackeo.tudominio.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    listen 443 ssl;
    # Rutas certificados SSL de Let's Encrypt...
}
```

---

## 🧪 Simulación y Pruebas Rápidas

Para probar el sistema sin necesidad de mover un vehículo físico:
1. Ingresa a `http://localhost:8000/admin`.
2. Presiona el botón superior **"Simular Recorrido Demo"**.
3. Se generará instantáneamente un trayecto con waypoints, métricas y cálculo de tiempos.
4. Podrás hacer clic en **"Ver"** para inspeccionar el mapa o en **".SHP"** para descargar el Shapefile comprimido en `.zip`.
>>>>>>> 7785eb6 (feat: Sistema de trackeo de itinerarios de buses con generador de Shapefiles, QRs y autenticacion)
