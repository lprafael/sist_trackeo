import math
import io
import os
import zipfile
import tempfile
import shapefile
from datetime import datetime
from typing import List, Dict, Any, Tuple

# WKT de Proyección WGS 84 (EPSG:4326) para el archivo .prj del Shapefile
WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]]'
)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia en kilómetros entre dos coordenadas GPS usando la fórmula de Haversine."""
    R = 6371.0 # Radio de la Tierra en km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0)**2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0)**2

    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def calculate_service_metrics(points: List[Dict[str, Any]], start_time_str: str, end_time_str: str = None) -> Dict[str, Any]:
    """Calcula distancia total, velocidades, tiempos y estadísticas a partir de la lista de puntos GPS."""
    total_dist_km = 0.0
    speeds = []
    max_speed = 0.0
    
    if len(points) >= 2:
        for i in range(1, len(points)):
            p_prev = points[i-1]
            p_curr = points[i]
            d = haversine_distance(p_prev["latitude"], p_prev["longitude"], p_curr["latitude"], p_curr["longitude"])
            
            # Filtro básico de salto GPS anómalo (ej: > 150 km/h o teletransportación)
            if d < 10.0: # menos de 10 km entre muestras consecutivas
                total_dist_km += d
                
            spd = p_curr.get("speed_kmh") or 0.0
            if spd > 0.5: # solo velocidades en movimiento
                speeds.append(spd)
                if spd > max_speed:
                    max_speed = spd

    # Normalizar strings de tiempo para cálculo robusto de duración
    def parse_dt(dt_str: str) -> datetime:
        if not dt_str:
            return datetime.utcnow()
        clean_str = dt_str.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is not None:
                # Convertir a naive UTC
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            return datetime.utcnow()

    t_start = parse_dt(start_time_str)
    t_end = parse_dt(end_time_str) if end_time_str else datetime.utcnow()

    duration_sec = max(0, int((t_end - t_start).total_seconds()))
    
    # Si no hay velocidades reportadas por el GPS pero hay distancia y tiempo, calculamos velocidad media
    avg_speed = (sum(speeds) / len(speeds)) if speeds else 0.0
    if avg_speed == 0.0 and duration_sec > 60 and total_dist_km > 0.1:
        avg_speed = (total_dist_km / (duration_sec / 3600.0))

    return {
        "total_distance_km": round(total_dist_km, 3),
        "total_duration_sec": duration_sec,
        "avg_speed_kmh": round(avg_speed, 1),
        "max_speed_kmh": round(max_speed, 1),
        "points_count": len(points)
    }

def format_duration(seconds: int) -> str:
    """Convierte segundos a formato legible HH:MM:SS"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}h {minutes:02d}m {secs:02d}s"
    return f"{minutes:02d}m {secs:02d}s"

def generate_shapefile_zip(service: Dict[str, Any], points: List[Dict[str, Any]]) -> bytes:
    """
    Genera un archivo ZIP con el ESRI Shapefile completo (.shp, .shx, .dbf, .prj)
    del recorrido / trazado del itinerario del bus.
    """
    clean_bus = "".join(c for c in service.get("bus_number", "bus") if c.isalnum() or c in ("-", "_"))
    base_name = f"itinerario_bus_{clean_bus}_{service.get('id', 'servicio')[:8]}"

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_base = os.path.join(tmpdir, base_name)
        
        # 1. Crear Shapefile de Línea (Trazado del Itinerario)
        w = shapefile.Writer(shp_base, shapeType=shapefile.POLYLINE)
        w.field("ID_SERV", "C", size=40)
        w.field("BUS_NUM", "C", size=20)
        w.field("CHOFER", "C", size=40)
        w.field("LINEA", "C", size=40)
        w.field("ORIGEN", "C", size=50)
        w.field("DESTINO", "C", size=50)
        w.field("F_SALIDA", "C", size=30)
        w.field("F_LLEGADA", "C", size=30)
        w.field("DURAC_SEG", "N", decimal=0)
        w.field("DIST_KM", "N", decimal=3)
        w.field("VEL_PROM", "N", decimal=1)
        w.field("VEL_MAX", "N", decimal=1)
        w.field("CANT_PTS", "N", decimal=0)

        # Construir coordenadas [lon, lat] para el trazado
        coordinates = []
        for p in points:
            coordinates.append([float(p["longitude"]), float(p["latitude"])])

        if len(coordinates) >= 2:
            w.line([coordinates])
        elif len(coordinates) == 1:
            # Si solo hay 1 punto, duplicamos para formar una línea mínima válida
            w.line([[coordinates[0], coordinates[0]]])
        else:
            w.line([[[0.0, 0.0], [0.0, 0.0]]])

        w.record(
            str(service.get("id", "")),
            str(service.get("bus_number", "")),
            str(service.get("driver_name", "") or "No especificado"),
            str(service.get("line_name", "") or "General"),
            str(service.get("origin_name", "") or "Origen"),
            str(service.get("destination_name", "") or "Destino"),
            str(service.get("start_time", "")),
            str(service.get("end_time", "") or "En curso"),
            int(service.get("total_duration_sec", 0) or 0),
            float(service.get("total_distance_km", 0.0) or 0.0),
            float(service.get("avg_speed_kmh", 0.0) or 0.0),
            float(service.get("max_speed_kmh", 0.0) or 0.0),
            int(len(points))
        )
        w.close()

        # 2. Crear archivo de proyección .prj (WGS84 EPSG:4326)
        prj_path = f"{shp_base}.prj"
        with open(prj_path, "w", encoding="utf-8") as f:
            f.write(WGS84_PRJ)

        # 3. Crear Shapefile adicional de Puntos (Waypoints con velocidad y timestamp)
        pts_base = os.path.join(tmpdir, f"{base_name}_puntos")
        wp = shapefile.Writer(pts_base, shapeType=shapefile.POINT)
        wp.field("ORDEN", "N", decimal=0)
        wp.field("TIMESTAMP", "C", size=30)
        wp.field("VEL_KMH", "N", decimal=1)
        wp.field("ALTITUD", "N", decimal=1)
        wp.field("PRECISION", "N", decimal=1)
        
        for idx, p in enumerate(points):
            wp.point(float(p["longitude"]), float(p["latitude"]))
            wp.record(
                idx + 1,
                str(p.get("recorded_at", "")),
                float(p.get("speed_kmh") or 0.0),
                float(p.get("altitude") or 0.0),
                float(p.get("accuracy") or 0.0)
            )
        wp.close()

        with open(f"{pts_base}.prj", "w", encoding="utf-8") as f:
            f.write(WGS84_PRJ)

        # 4. Crear archivo README con metadatos legibles
        readme_path = os.path.join(tmpdir, "LEAME_METADATOS.txt")
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(
                f"SISTEMA DE TRACKEO DE ITINERARIOS DE BUSES\n"
                f"==========================================\n"
                f"ID de Servicio : {service.get('id')}\n"
                f"Número de Bus  : {service.get('bus_number')}\n"
                f"Chofer         : {service.get('driver_name')}\n"
                f"Línea / Ramal  : {service.get('line_name')}\n"
                f"Origen         : {service.get('origin_name')}\n"
                f"Destino        : {service.get('destination_name')}\n"
                f"Horario Salida : {service.get('start_time')}\n"
                f"Horario Llegada: {service.get('end_time')}\n"
                f"Duración Total : {format_duration(service.get('total_duration_sec', 0))}\n"
                f"Distancia Total: {service.get('total_distance_km', 0)} km\n"
                f"Velocidad Media: {service.get('avg_speed_kmh', 0)} km/h\n"
                f"Total de Puntos: {len(points)} waypoints GPS\n"
                f"Sistema Coord. : EPSG:4326 (WGS 84 Lat/Lon)\n"
                f"Compatible con : QGIS, ArcGIS, Google Earth, AutoCAD Map, GeoServer\n"
            )

        # 5. Comprimir todos los archivos en un ZIP en memoria
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root, _, files in os.walk(tmpdir):
                for file in files:
                    file_path = os.path.join(root, file)
                    zip_file.write(file_path, arcname=file)

        zip_bytes = zip_buffer.getvalue()

        # 6. Guardar copia persistente en la carpeta exports/shapes del servidor
        try:
            shapes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports", "shapes")
            os.makedirs(shapes_dir, exist_ok=True)
            
            # Guardar el .zip completo
            zip_out_path = os.path.join(shapes_dir, f"{base_name}.zip")
            with open(zip_out_path, "wb") as f_out:
                f_out.write(zip_bytes)

            # Guardar los archivos .shp, .shx, .dbf, .prj listos para abrir directamente en QGIS/ArcGIS
            raw_folder = os.path.join(shapes_dir, base_name)
            os.makedirs(raw_folder, exist_ok=True)
            import shutil
            for f in os.listdir(tmpdir):
                shutil.copy2(os.path.join(tmpdir, f), os.path.join(raw_folder, f))
        except Exception as err:
            print(f"Aviso al guardar copia física del Shapefile en disco: {err}")

        return zip_bytes

def generate_geojson(service: Dict[str, Any], points: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Genera una estructura GeoJSON FeatureCollection con el trazado y puntos clave."""
    coordinates = [[float(p["longitude"]), float(p["latitude"])] for p in points]
    
    features = []
    
    # Feature 1: Línea completa de la ruta
    features.append({
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates
        },
        "properties": {
            "service_id": service.get("id"),
            "bus_number": service.get("bus_number"),
            "driver_name": service.get("driver_name"),
            "line_name": service.get("line_name"),
            "origin": service.get("origin_name"),
            "destination": service.get("destination_name"),
            "start_time": service.get("start_time"),
            "end_time": service.get("end_time"),
            "total_distance_km": service.get("total_distance_km"),
            "total_duration_sec": service.get("total_duration_sec"),
            "duration_formatted": format_duration(service.get("total_duration_sec", 0)),
            "avg_speed_kmh": service.get("avg_speed_kmh"),
            "points_count": len(points),
            "status": service.get("status")
        }
    })

    # Feature 2: Punto de Salida
    if points:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(points[0]["longitude"]), float(points[0]["latitude"])]
            },
            "properties": {
                "type": "salida",
                "label": f"Salida: {service.get('origin_name')}",
                "timestamp": points[0].get("recorded_at") or service.get("start_time")
            }
        })

    # Feature 3: Punto de Llegada
    if len(points) > 1 and service.get("status") == "completed":
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(points[-1]["longitude"]), float(points[-1]["latitude"])]
            },
            "properties": {
                "type": "llegada",
                "label": f"Llegada: {service.get('destination_name')}",
                "timestamp": points[-1].get("recorded_at") or service.get("end_time")
            }
        })

    return {
        "type": "FeatureCollection",
        "properties": {
            "generated_by": "Sistema de Trackeo e Itinerarios de Buses",
            "service_id": service.get("id")
        },
        "features": features
    }

def generate_kml(service: Dict[str, Any], points: List[Dict[str, Any]]) -> str:
    """Genera archivo KML para Google Earth."""
    coord_str = " ".join([f"{p['longitude']},{p['latitude']},0" for p in points])
    bus = service.get("bus_number", "Bus")
    start = service.get("start_time", "")
    end = service.get("end_time", "") or "En curso"
    dist = service.get("total_distance_km", 0)

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Itinerario Bus {bus}</name>
    <description>Servicio {service.get('id')} - Salida: {start} - Llegada: {end} - Distancia: {dist} km</description>
    <Style id="routeStyle">
      <LineStyle>
        <color>ff0066ff</color>
        <width>5</width>
      </LineStyle>
    </Style>
    <Placemark>
      <name>Trazado de Ruta - Bus {bus}</name>
      <styleUrl>#routeStyle</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>
          {coord_str}
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
    return kml

def generate_gpx(service: Dict[str, Any], points: List[Dict[str, Any]]) -> str:
    """Genera archivo GPX estándar para navegadores y GPS."""
    bus = service.get("bus_number", "Bus")
    trkpts = []
    for p in points:
        rec_time = p.get("recorded_at") or ""
        spd = p.get("speed_kmh") or 0.0
        spd_ms = spd / 3.6 # GPX usa m/s
        ele = p.get("altitude") or 0.0
        trkpts.append(
            f'      <trkpt lat="{p["latitude"]}" lon="{p["longitude"]}">'
            f'<ele>{ele:.1f}</ele>'
            f'<time>{rec_time}</time>'
            f'<speed>{spd_ms:.2f}</speed>'
            f'</trkpt>'
        )
    
    pts_xml = "\n".join(trkpts)
    gpx = f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="SistemaTrackeoBuses" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>Recorrido Bus {bus}</name>
    <time>{service.get('start_time')}</time>
  </metadata>
  <trk>
    <name>Itinerario {service.get('id')}</name>
    <trkseg>
{pts_xml}
    </trkseg>
  </trk>
</gpx>"""
    return gpx

def generate_csv(service: Dict[str, Any], points: List[Dict[str, Any]]) -> str:
    """Genera archivo CSV tabular con todas las lecturas de telemetría."""
    lines = ["orden,service_id,bus_number,latitud,longitud,altitud_m,velocidad_kmh,precision_m,rumbo_deg,timestamp"]
    for i, p in enumerate(points):
        lines.append(
            f"{i+1},{service.get('id')},{service.get('bus_number')},{p['latitude']},{p['longitude']},"
            f"{p.get('altitude') or 0},{p.get('speed_kmh') or 0},{p.get('accuracy') or 0},"
            f"{p.get('heading') or 0},{p.get('recorded_at') or ''}"
        )
    return "\n".join(lines)
