from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class GPSPointItem(BaseModel):
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    speed_kmh: Optional[float] = 0.0
    accuracy: Optional[float] = None
    heading: Optional[float] = None
    timestamp: str = Field(description="ISO 8601 string or client timestamp")

class ServiceStartRequest(BaseModel):
    bus_number: str
    driver_name: Optional[str] = "Chofer General"
    line_name: Optional[str] = "Línea Principal"
    origin_name: Optional[str] = "Terminal de Salida"
    checkpoint_code: Optional[str] = None
    user_id: Optional[str] = None
    initial_location: Optional[GPSPointItem] = None

class GPSBatchUpload(BaseModel):
    service_id: str
    points: List[GPSPointItem]

class ServiceFinishRequest(BaseModel):
    service_id: str
    destination_name: Optional[str] = "Terminal de Llegada"
    checkpoint_code: Optional[str] = None
    final_location: Optional[GPSPointItem] = None
    timestamp: Optional[str] = None

class CheckpointCreate(BaseModel):
    name: str
    type: str # 'salida' or 'llegada'
    code: str
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
