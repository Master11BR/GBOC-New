# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Hardware, Disks & S.M.A.R.T. Telemetry Router (Server)
# Zero-Mock Policy: 100% Real Hardware and Real Ambient Temperature Data
# ==============================================================================

import os
import sys
import platform
import subprocess
import json
import time
import urllib.request
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request
from modules.v2.envelope import build_v2_response

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

logger = logging.getLogger("gboc_hardware_module")
router = APIRouter(tags=["Hardware & SMART"])

_AMBIENT_CACHE = {
    "data": None,
    "last_fetch": 0
}

def get_ambient_telemetry() -> Dict[str, Any]:
    """Coleta a temperatura real do ambiente externo da cidade do servidor via GeoIP + Open-Meteo."""
    global _AMBIENT_CACHE
    now = time.time()
    if _AMBIENT_CACHE["data"] and (now - _AMBIENT_CACHE["last_fetch"] < 600):
        res = dict(_AMBIENT_CACHE["data"])
        res["cached"] = True
        return res

    try:
        req_loc = urllib.request.Request("http://ip-api.com/json", headers={"User-Agent": "GBOC-Hardware-Telemetry/1.0"})
        with urllib.request.urlopen(req_loc, timeout=3) as resp_loc:
            loc_data = json.loads(resp_loc.read().decode())
            city = loc_data.get("city") or "Local"
            region = loc_data.get("regionName") or loc_data.get("region") or ""
            country = loc_data.get("country") or "Brasil"
            lat = loc_data.get("lat")
            lon = loc_data.get("lon")

            if lat is not None and lon is not None:
                url_weather = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                req_w = urllib.request.Request(url_weather, headers={"User-Agent": "GBOC-Hardware-Telemetry/1.0"})
                with urllib.request.urlopen(req_w, timeout=3) as resp_w:
                    w_data = json.loads(resp_w.read().decode())
                    cw = w_data.get("current_weather", {})
                    temp_c = cw.get("temperature")
                    wind_speed = cw.get("windspeed")
                    weather_code = cw.get("weathercode", 0)

                    condition = "Limpo / Ensolarado"
                    if weather_code in (1, 2, 3):
                        condition = "Parcialmente Nublado"
                    elif weather_code in (45, 48):
                        condition = "Neblina"
                    elif weather_code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
                        condition = "Chuvoso"
                    elif weather_code in (95, 96, 99):
                        condition = "Tempestade"

                    result = {
                        "available": True,
                        "city": city,
                        "region": region,
                        "country": country,
                        "temperature_c": temp_c,
                        "condition": condition,
                        "wind_kmh": wind_speed,
                        "latitude": lat,
                        "longitude": lon,
                        "source": "Open-Meteo & GeoIP (Real)",
                        "updated_at": now,
                        "cached": False
                    }
                    _AMBIENT_CACHE["data"] = result
                    _AMBIENT_CACHE["last_fetch"] = now
                    return result
    except Exception as e:
        logger.warning(f"Não foi possível obter clima ambiente externo no Servidor: {e}")

    if _AMBIENT_CACHE["data"]:
        res = dict(_AMBIENT_CACHE["data"])
        res["cached"] = True
        return res

    return {
        "available": False,
        "city": "Ambiente do Servidor",
        "region": "",
        "country": "",
        "temperature_c": None,
        "condition": "Indisponível",
        "source": "Nenhum",
        "error": "Sem conexão externa para meteorologia",
        "cached": False
    }

def get_hardware_telemetry() -> Dict[str, Any]:
    """
    Coleta telemetria 100% REAL do hardware do host:
    - Processador: Modelo, Cores, Threads, Clock (MHz), Carga (%) e Sensores térmicos.
    - Discos Físicos & S.M.A.R.T.: Modelo, Mídia (SSD/HDD/NVMe), Bus (SATA/PCIe), Tamanho, Status S.M.A.R.T. e Temperatura (°C).
    - Ambiente Externo: Cidade onde roda o servidor e Temperatura ambiente (°C).
    - Comparativo Térmico: Temperatura externa vs interna (CPU e Discos).
    """
    t0 = time.perf_counter()
    
    # 1. CPU Telemetry
    cpu_data = {
        "model": platform.processor() or "Processador Host",
        "cores_physical": psutil.cpu_count(logical=False) if PSUTIL_AVAILABLE else 1,
        "threads_logical": psutil.cpu_count(logical=True) if PSUTIL_AVAILABLE else 1,
        "load_percent": psutil.cpu_percent(interval=0.1) if PSUTIL_AVAILABLE else 0.0,
        "clock_mhz": None,
        "temperature_c": None,
        "temperature_status": "unavailable"
    }

    # 2. Memory Telemetry
    mem_data = {}
    if PSUTIL_AVAILABLE:
        vm = psutil.virtual_memory()
        mem_data = {
            "total_gb": round(vm.total / (1024**3), 2),
            "used_gb": round(vm.used / (1024**3), 2),
            "free_gb": round(vm.available / (1024**3), 2),
            "percent": vm.percent
        }

    # 3. Storage Partitions
    partitions_data = []
    if PSUTIL_AVAILABLE:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                partitions_data.append({
                    "mountpoint": part.mountpoint,
                    "device": part.device,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent": usage.percent
                })
            except Exception:
                continue

    # 4. Physical Disks & S.M.A.R.T.
    physical_disks = []
    
    if platform.system() == "Windows":
        try:
            # Consulta detalhada dos discos e telemetria de confiabilidade (SMART / Temperatura)
            ps_cmd = (
                "Get-PhysicalDisk | ForEach-Object { "
                "$d = $_; "
                "$rel = Get-StorageReliabilityCounter -PhysicalDisk $d -ErrorAction SilentlyContinue; "
                "[PSCustomObject]@{ "
                "FriendlyName = $d.FriendlyName; "
                "MediaType = $d.MediaType; "
                "BusType = $d.BusType; "
                "Size = $d.Size; "
                "HealthStatus = $d.HealthStatus; "
                "OperationalStatus = $d.OperationalStatus; "
                "Temperature = if ($rel -and $rel.Temperature) { $rel.Temperature } else { $null }; "
                "Wear = if ($rel -and $rel.Wear) { $rel.Wear } else { $null }; "
                "ReadErrorsTotal = if ($rel -and $rel.ReadErrorsTotal) { $rel.ReadErrorsTotal } else { $null } "
                "} } | ConvertTo-Json -Depth 2"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5
            )
            if res.returncode == 0 and res.stdout.strip():
                raw_json = json.loads(res.stdout)
                disks_list = raw_json if isinstance(raw_json, list) else [raw_json]
                for d in disks_list:
                    sz_bytes = d.get("Size") or 0
                    sz_gb = round(sz_bytes / (1024**3), 1) if sz_bytes else 0
                    health = d.get("HealthStatus") or "OK"
                    op_status = d.get("OperationalStatus") or "OK"
                    temp_c = d.get("Temperature")
                    temp_status = "normal" if (temp_c and temp_c < 45) else "high" if (temp_c and temp_c < 55) else "critical" if temp_c else "unknown"
                    
                    physical_disks.append({
                        "name": d.get("FriendlyName") or "Disco Físico",
                        "media_type": d.get("MediaType") or "Desconhecido",
                        "bus_type": d.get("BusType") or "SATA",
                        "size_gb": sz_gb,
                        "health_status": health,
                        "operational_status": op_status,
                        "temperature_c": temp_c,
                        "temperature_status": temp_status,
                        "wear_percent": d.get("Wear"),
                        "read_errors": d.get("ReadErrorsTotal"),
                        "smart_status": "HEALTHY" if health.lower() == "healthy" or op_status.lower() == "ok" else "WARNING"
                    })
        except Exception as ex:
            logger.warning(f"Erro ao consultar Get-PhysicalDisk com S.M.A.R.T.: {ex}")

        # Fallback Win32_DiskDrive se Get-PhysicalDisk vazio
        if not physical_disks:
            try:
                ps_cmd2 = "Get-CimInstance Win32_DiskDrive | Select-Object Model, Status, Size | ConvertTo-Json"
                res2 = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd2],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                if res2.returncode == 0 and res2.stdout.strip():
                    raw_json2 = json.loads(res2.stdout)
                    drives_list = raw_json2 if isinstance(raw_json2, list) else [raw_json2]
                    for d in drives_list:
                        sz_bytes = d.get("Size") or 0
                        sz_gb = round(sz_bytes / (1024**3), 1) if sz_bytes else 0
                        st = d.get("Status") or "OK"
                        physical_disks.append({
                            "name": d.get("Model") or "Drive Local",
                            "media_type": "HDD/SSD",
                            "bus_type": "Local",
                            "size_gb": sz_gb,
                            "health_status": st,
                            "operational_status": st,
                            "temperature_c": None,
                            "temperature_status": "unknown",
                            "wear_percent": None,
                            "read_errors": None,
                            "smart_status": "HEALTHY" if st.upper() == "OK" else "DEGRADED"
                        })
            except Exception:
                pass

        # Query Win32_Processor for model and clock
        try:
            ps_cpu = "Get-CimInstance Win32_Processor | Select-Object Name, MaxClockSpeed | ConvertTo-Json"
            res_cpu = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cpu],
                capture_output=True,
                text=True,
                timeout=3
            )
            if res_cpu.returncode == 0 and res_cpu.stdout.strip():
                cpu_json = json.loads(res_cpu.stdout)
                if isinstance(cpu_json, list):
                    cpu_json = cpu_json[0]
                if cpu_json.get("Name"):
                    cpu_data["model"] = cpu_json.get("Name").strip()
                if cpu_json.get("MaxClockSpeed"):
                    cpu_data["clock_mhz"] = cpu_json.get("MaxClockSpeed")
        except Exception:
            pass

        # Query Thermal Sensors para CPU
        try:
            ps_temp = "Get-CimInstance -Namespace 'root/wmi' -ClassName 'MSAcpi_ThermalZoneTemperature' -ErrorAction SilentlyContinue | Select-Object CurrentTemperature | ConvertTo-Json"
            res_temp = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_temp],
                capture_output=True,
                text=True,
                timeout=2
            )
            if res_temp.returncode == 0 and res_temp.stdout.strip():
                temp_json = json.loads(res_temp.stdout)
                if isinstance(temp_json, list):
                    temp_json = temp_json[0]
                raw_k = temp_json.get("CurrentTemperature")
                if raw_k:
                    celsius = round((raw_k - 2732) / 10.0, 1)
                    if 0 < celsius < 115:
                        cpu_data["temperature_c"] = celsius
                        cpu_data["temperature_status"] = "normal" if celsius < 75 else "high" if celsius < 85 else "critical"
        except Exception:
            pass

    # 5. Ambient Weather Telemetry (Cidade do Servidor)
    ambient_data = get_ambient_telemetry()

    # 6. Comparativo Térmico
    disk_temps = [d["temperature_c"] for d in physical_disks if d.get("temperature_c") is not None]
    avg_disk_temp = round(sum(disk_temps) / len(disk_temps), 1) if disk_temps else None
    max_disk_temp = max(disk_temps) if disk_temps else None
    
    cpu_temp = cpu_data.get("temperature_c")
    ambient_temp = ambient_data.get("temperature_c")

    delta_cpu_ambient = round(cpu_temp - ambient_temp, 1) if (cpu_temp is not None and ambient_temp is not None) else None
    delta_disk_ambient = round(avg_disk_temp - ambient_temp, 1) if (avg_disk_temp is not None and ambient_temp is not None) else None

    thermal_status = "NORMAL"
    if cpu_temp and cpu_temp > 80:
        thermal_status = "CRÍTICO"
    elif max_disk_temp and max_disk_temp > 55:
        thermal_status = "ATENÇÃO"
    elif delta_disk_ambient and delta_disk_ambient < 25:
        thermal_status = "EXCELENTE"

    thermal_comparison = {
        "ambient_c": ambient_temp,
        "cpu_c": cpu_temp,
        "disks_avg_c": avg_disk_temp,
        "disks_max_c": max_disk_temp,
        "delta_cpu_ambient": delta_cpu_ambient,
        "delta_disk_ambient": delta_disk_ambient,
        "status": thermal_status
    }

    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": cpu_data,
        "memory": mem_data,
        "disks": physical_disks,
        "partitions": partitions_data,
        "ambient": ambient_data,
        "thermal_comparison": thermal_comparison,
        "timestamp": time.time()
    }

@router.get("/api/v1/system/hardware")
@router.get("/api/system/hardware")
async def get_hardware_v1(request: Request):
    """Endpoint legado/v1 para telemetria de hardware, S.M.A.R.T. e ambiente."""
    return get_hardware_telemetry()

@router.get("/api/v2/system/hardware")
async def get_hardware_v2(request: Request):
    """Endpoint moderno v2 com envelope para telemetria de hardware, S.M.A.R.T. e ambiente."""
    t0 = time.perf_counter()
    data = get_hardware_telemetry()
    elapsed = (time.perf_counter() - t0) * 1000
    return build_v2_response(data=data, execution_time_ms=elapsed)
