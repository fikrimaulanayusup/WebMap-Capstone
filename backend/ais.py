"""Integrasi AIS (Automatic Identification System) untuk pelacakan kapal via AISStream.io.

Mendukung:
  1. WebSocket real-time dari aisstream.io: posisi kapal dan data statis (nama, jenis, dll)
  2. Cache & riwayat jejak (track history) posisi kapal di memori per MMSI
  3. REST API untuk status konfigurasi API key, daftar kapal aktif, dan GeoJSON track history
  4. WebSocket relay untuk streaming langsung ke browser Leaflet

API key:
  - Dibaca dari variabel lingkungan `AISSTREAM_API_KEY`, atau
  - Diatur melalui endpoint `POST /api/ais/config` saat aplikasi berjalan.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger("ais")

router = APIRouter(prefix="/api/ais", tags=["AIS - AISStream & GFW"])

# ---------------------------------------------------------------- Konfigurasi API Key
# 1. AISStream.io (Streaming Real-Time)
AISSTREAM_API_KEY = os.environ.get("AISSTREAM_API_KEY", "5e0b7df4d63633c87ef5c1164055e01647404e3e")

# 2. Global Fishing Watch (Data Historis Masa Lampau)
# Dapatkan token gratis untuk riset di: https://globalfishingwatch.org/our-apis
GFW_API_TOKEN = os.environ.get("GFW_API_TOKEN", "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImtpZEtleSJ9.eyJkYXRhIjp7Im5hbWUiOiJPaWwgU3BpbGwgU291cmNlIERldGVjdGlvbiIsInVzZXJJZCI6NzUxMzksImFwcGxpY2F0aW9uTmFtZSI6Ik9pbCBTcGlsbCBTb3VyY2UgRGV0ZWN0aW9uIiwiaWQiOjE2NTQ3LCJ0eXBlIjoidXNlci1hcHBsaWNhdGlvbiJ9LCJpYXQiOjE3OTMxNjYyMzIsImV4cCI6MjEwODUyNjIzMiwiYXVkIjoiZ2Z3IiwiaXNzIjoiZ2Z3In0.Wk-7NjA57nqlioJNYpg4ma9F9K-5S_7kMwXRDbFV_0V7NvH8O4LUD7omkwxrIKBE5-QoT8y5TgIzuhKom6g_cxJYEW1Ma50VbXb0wFcepbOafIzSu91I2u9yg1M3D-iJbZf40Epqmb5NlJLvCoivPWBEfr-X4TCMqUI9LoNvoVpODqogj2jHzOO22vqh7qZdGmLI4GbmiyuZYdu9ddIq9W21k27X3J05ZOs9JkGgxyn9vSHsHefl2545uouRsTubncIsad_ZIq_STWmxsYX7jgf0_D5_VPaU91qva-Fmd3R02qx1zfjCF854tcYPrWGeFiD7XPn0GVCHgzwpm4Udk96lQTtCwOg7pQrXfysdkES9sMesTemLDJTm8QkSpdepM2Qn9D0cvZF4cv_UoydFiE8UZ2XetTjHK8c620tcVqy6oLmVYZ8ewMvDtO4Lo7TsC7u2InmIWaatfYn-AbjElrzj_2hYiCRfZSP_8I-1G7_y7JhbxoCMSpL12QPtKgfA")
GFW_EVENTS_URL = "https://gateway.api.globalfishingwatch.org/v3/events"


def get_aisstream_key() -> str:
    return AISSTREAM_API_KEY.strip()


def get_gfw_token() -> str:
    return GFW_API_TOKEN.strip()


# ---------------------------------------------------------------- Penyimpanan Kapal & Riwayat Jejak
# Struktur data kapal di memori:
# {
#   mmsi: {
#      "mmsi": int,
#      "name": str,
#      "lat": float,
#      "lon": float,
#      "sog": float,
#      "cog": float,
#      "heading": float,
#      "type_code": int,
#      "type_text": str,
#      "callsign": str,
#      "imo": int,
#      "destination": str,
#      "draught": float,
#      "last_seen": float,
#      "track": deque([ [lon, lat, timestamp, sog, cog], ... ], maxlen=150)
#   }
# }
MAX_TRACK_POINTS = 150
VESSEL_EXPIRY_SECONDS = 6 * 3600  # hapus kapal yang tidak terpantau lebih dari 6 jam

_vessels: dict[int, dict] = {}
_vessels_lock = threading.Lock()

SHIP_TYPE_MAPPING = {
    range(20, 30): "Wing in Ground",
    range(30, 31): "Fishing",
    range(31, 33): "Towing / Tug",
    range(33, 34): "Dredger",
    range(34, 35): "Dive Vessel",
    range(35, 36): "Military Ops",
    range(36, 37): "Sailing Vessel",
    range(37, 38): "Pleasure Craft",
    range(40, 50): "High Speed Craft",
    range(50, 51): "Pilot Vessel",
    range(51, 52): "Search & Rescue",
    range(52, 53): "Tug",
    range(53, 54): "Port Tender",
    range(54, 55): "Anti-pollution",
    range(55, 56): "Law Enforcement",
    range(58, 60): "Medical Transport",
    range(60, 70): "Passenger",
    range(70, 80): "Cargo",
    range(80, 90): "Tanker (Minyak/Kimia)",
    range(90, 100): "Other",
}


def decode_ship_type(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    for r, name in SHIP_TYPE_MAPPING.items():
        if code in r:
            return name
    return "Unknown"


def update_vessel_position(
    mmsi: int,
    name: Optional[str],
    lat: float,
    lon: float,
    sog: Optional[float],
    cog: Optional[float],
    heading: Optional[float],
    timestamp: str,
) -> dict:
    now = time.time()
    with _vessels_lock:
        if mmsi not in _vessels:
            _vessels[mmsi] = {
                "mmsi": mmsi,
                "name": name or f"MMSI {mmsi}",
                "lat": lat,
                "lon": lon,
                "sog": sog,
                "cog": cog,
                "heading": heading,
                "type_code": None,
                "type_text": "Unknown",
                "callsign": None,
                "imo": None,
                "destination": None,
                "draught": None,
                "last_seen": now,
                "timestamp_utc": timestamp,
                "track": deque(maxlen=MAX_TRACK_POINTS),
            }
        v = _vessels[mmsi]
        v["lat"] = lat
        v["lon"] = lon
        if name and (v["name"].startswith("MMSI") or not v["name"]):
            v["name"] = name
        if sog is not None:
            v["sog"] = sog
        if cog is not None:
            v["cog"] = cog
        if heading is not None:
            v["heading"] = heading
        v["last_seen"] = now
        v["timestamp_utc"] = timestamp

        # Catat track history jika posisi berpindah secara signifikan (> ~5 meter)
        track = v["track"]
        should_append = True
        if track:
            last_lon, last_lat = track[-1][0], track[-1][1]
            if abs(last_lon - lon) < 0.00005 and abs(last_lat - lat) < 0.00005:
                should_append = False
        if should_append:
            track.append([round(lon, 6), round(lat, 6), timestamp, sog, cog])

        return {
            "mmsi": v["mmsi"],
            "name": v["name"],
            "lat": v["lat"],
            "lon": v["lon"],
            "sog": v["sog"],
            "cog": v["cog"],
            "heading": v["heading"],
            "type_code": v["type_code"],
            "type_text": v["type_text"],
            "last_seen": v["last_seen"],
            "timestamp_utc": v["timestamp_utc"],
            "track_count": len(v["track"]),
        }


def update_vessel_static(
    mmsi: int,
    name: Optional[str],
    imo: Optional[int],
    callsign: Optional[str],
    type_code: Optional[int],
    destination: Optional[str],
    draught: Optional[float],
) -> Optional[dict]:
    with _vessels_lock:
        if mmsi in _vessels:
            v = _vessels[mmsi]
            if name:
                v["name"] = name
            if imo:
                v["imo"] = imo
            if callsign:
                v["callsign"] = callsign
            if type_code is not None:
                v["type_code"] = type_code
                v["type_text"] = decode_ship_type(type_code)
            if destination:
                v["destination"] = destination
            if draught is not None:
                v["draught"] = draught
            return v
    return None


def cleanup_old_vessels():
    """Hapus data kapal yang sudah tidak aktif lama."""
    now = time.time()
    cutoff = now - VESSEL_EXPIRY_SECONDS
    with _vessels_lock:
        expired = [mmsi for mmsi, v in _vessels.items() if v["last_seen"] < cutoff]
        for mmsi in expired:
            del _vessels[mmsi]


# ---------------------------------------------------------------- Endpoints REST
class HistoricalAisRequest(BaseModel):
    start_date: str = Field(description="Tanggal awal YYYY-MM-DD")
    end_date: str = Field(description="Tanggal akhir YYYY-MM-DD")
    bbox: tuple[float, float, float, float] = Field(description="Kotak koordinat: west, south, east, north")


@router.get("/config")
def get_config():
    """Periksa status konfigurasi API key AISStream & GFW dari backend."""
    ais_key = get_aisstream_key()
    gfw_token = get_gfw_token()
    return {
        "aisstream": {
            "provider": "aisstream.io",
            "configured": bool(ais_key),
        },
        "gfw": {
            "provider": "Global Fishing Watch",
            "configured": bool(gfw_token),
        },
        "source": "backend_file",
    }


@router.post("/historical")
def query_historical_ais(req: HistoricalAisRequest):
    """Cari kapal historis di dalam area kotak dan rentang tanggal menggunakan Global Fishing Watch API."""
    west, south, east, north = req.bbox
    if not (west < east and south < north):
        raise HTTPException(400, "bbox tidak valid.")

    gfw_token = get_gfw_token()
    if not gfw_token:
        return {
            "status": "unconfigured",
            "source": "Global Fishing Watch (GFW)",
            "message": "Token GFW_API_TOKEN belum diisi di backend/ais.py (baris 39). Daftar gratis di globalfishingwatch.org/our-apis untuk mengaktifkan query historis.",
            "vessels": [],
            "count": 0,
            "configured": False,
        }

    start_iso = f"{req.start_date}T00:00:00Z" if len(req.start_date) == 10 else req.start_date
    end_iso = f"{req.end_date}T23:59:59Z" if len(req.end_date) == 10 else req.end_date

    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]
        ],
    }

    target_datasets = [
        "public-global-fishing-events:latest",
        "public-global-loitering-events:latest",
        "public-global-encounters-events:latest",
        "public-global-port-visits-events:latest",
    ]

    all_entries: list[dict] = []
    gfw_errors: list[str] = []

    def fetch_dataset(ds: str) -> list[dict]:
        ds_body = {
            "datasets": [ds],
            "startDate": start_iso,
            "endDate": end_iso,
            "geometry": polygon,
        }
        with httpx.Client(timeout=25) as client:
            resp = client.post(
                GFW_EVENTS_URL,
                params={"limit": 50, "offset": 0},
                headers={
                    "Authorization": f"Bearer {gfw_token}",
                    "Content-Type": "application/json",
                },
                json=ds_body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("entries", [])

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_ds = {executor.submit(fetch_dataset, ds): ds for ds in target_datasets}
            for future in future_to_ds:
                ds = future_to_ds[future]
                try:
                    entries = future.result()
                    all_entries.extend(entries)
                except httpx.HTTPStatusError as exc:
                    logger.warning("GFW dataset %s HTTP %s: %s", ds, exc.response.status_code, exc.response.text)
                    try:
                        err_json = exc.response.json()
                        if "messages" in err_json and isinstance(err_json["messages"], list):
                            details = [f"{m.get('title', '')}: {m.get('detail', '')}".strip(': ') for m in err_json["messages"]]
                            gfw_errors.append("; ".join(details))
                        elif "message" in err_json:
                            gfw_errors.append(str(err_json["message"]))
                        else:
                            gfw_errors.append(exc.response.text[:200])
                    except Exception:
                        gfw_errors.append(exc.response.text[:200])
                except Exception as exc:
                    logger.warning("GFW dataset %s error: %s", ds, exc)
                    gfw_errors.append(str(exc))
    except Exception as exc:
        logger.warning("GFW ThreadPool error: %s", exc)

    if not all_entries and gfw_errors:
        return {
            "status": "error",
            "source": "Global Fishing Watch (GFW)",
            "message": f"GFW API Error: {'; '.join(gfw_errors[:2])}",
            "vessels": [],
            "count": 0,
            "configured": True,
        }

    results = []
    seen_ids = set()

    for entry in all_entries:
        pos = entry.get("position", {})
        lat = pos.get("lat")
        lon = pos.get("lon")
        if lat is None or lon is None:
            continue

        # Safeguard: pastikan di dalam batas area kotak pencarian
        margin = 0.05
        if not (west - margin <= lon <= east + margin and south - margin <= lat <= north + margin):
            continue

        vessel_info = entry.get("vessel", {})
        ssvid = vessel_info.get("ssvid") or entry.get("id")
        try:
            mmsi = int(ssvid)
        except (ValueError, TypeError):
            mmsi = abs(hash(str(ssvid))) % 1000000000

        name = vessel_info.get("name") or vessel_info.get("shipname") or f"Vessel {mmsi}"
        flag = vessel_info.get("flag", "")
        gear = vessel_info.get("gearType", "")
        v_type = vessel_info.get("type", "")
        event_type = entry.get("type", "").replace("_", " ").title()

        type_desc = f"{event_type}"
        if v_type and v_type.lower() != "fishing":
            type_desc += f" ({v_type.title()})"
        elif gear:
            type_desc += f" ({gear})"
        if flag:
            type_desc += f" [{flag}]"

        bbox_event = entry.get("boundingBox") or entry.get("bounding_box")
        track_coords = []
        if bbox_event and len(bbox_event) == 4:
            track_coords = [
                [bbox_event[0], bbox_event[1]],
                [lon, lat],
                [bbox_event[2], bbox_event[3]],
            ]
        else:
            track_coords = [[lon, lat]]

        dedup_key = (mmsi, round(lat, 4), round(lon, 4), entry.get("start", "")[:13])
        if dedup_key in seen_ids:
            continue
        seen_ids.add(dedup_key)

        v_obj = {
            "mmsi": mmsi,
            "name": name,
            "lat": lat,
            "lon": lon,
            "sog": None,
            "cog": None,
            "heading": None,
            "type_code": None,
            "type_text": type_desc,
            "flag": flag,
            "event_type": event_type,
            "timestamp_utc": entry.get("start", ""),
            "last_seen": time.time(),
            "source": "gfw",
            "track": [[p[0], p[1], entry.get("start", ""), None, None] for p in track_coords],
        }

        # Simpan ke cache vessel agar dapat di-klik dan dilihat popup-nya
        update_vessel_position(
            mmsi=mmsi,
            name=name,
            lat=lat,
            lon=lon,
            sog=None,
            cog=None,
            heading=None,
            timestamp=entry.get("start", ""),
        )
        update_vessel_static(
            mmsi=mmsi,
            name=name,
            imo=None,
            callsign=None,
            type_code=None,
            destination=f"{event_type} (GFW)",
            draught=None,
        )

        results.append(v_obj)

    return {
        "status": "success",
        "source": "Global Fishing Watch (GFW)",
        "vessels": results,
        "count": len(results),
        "total_events": len(all_entries),
        "start_date": req.start_date,
        "end_date": req.end_date,
        "configured": True,
    }


@router.get("/vessels")
def list_vessels(
    west: Optional[float] = Query(None, ge=-180, le=180),
    south: Optional[float] = Query(None, ge=-90, le=90),
    east: Optional[float] = Query(None, ge=-180, le=180),
    north: Optional[float] = Query(None, ge=-90, le=90),
    include_track: bool = Query(False, description="Sertakan titik koordinat track per kapal"),
):
    """Ambil daftar kapal yang sedang terpantau di memori.

    Jika bbox diberikan, filter hanya kapal yang berada di dalam rentang koordinat.
    """
    cleanup_old_vessels()
    results = []
    with _vessels_lock:
        for v in _vessels.values():
            lat, lon = v["lat"], v["lon"]
            if west is not None and south is not None and east is not None and north is not None:
                if not (south <= lat <= north and west <= lon <= east):
                    continue
            item = {
                "mmsi": v["mmsi"],
                "name": v["name"],
                "lat": v["lat"],
                "lon": v["lon"],
                "sog": v["sog"],
                "cog": v["cog"],
                "heading": v["heading"],
                "type_code": v["type_code"],
                "type_text": v["type_text"],
                "callsign": v["callsign"],
                "imo": v["imo"],
                "destination": v["destination"],
                "draught": v["draught"],
                "last_seen": round(v["last_seen"], 1),
                "timestamp_utc": v.get("timestamp_utc"),
                "track_count": len(v["track"]),
            }
            if include_track:
                item["track"] = list(v["track"])
            results.append(item)

    return {"vessels": results, "count": len(results)}


@router.get("/track/{mmsi}")
def get_vessel_track(mmsi: int):
    """Ambil riwayat jejak (track history) suatu kapal dalam format GeoJSON LineString."""
    with _vessels_lock:
        v = _vessels.get(mmsi)
        if not v:
            raise HTTPException(404, f"Kapal dengan MMSI {mmsi} tidak ditemukan atau belum pernah mengirim posisi.")

        coords = [[p[0], p[1]] for p in v["track"]]
        track_geojson = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": {
                "mmsi": mmsi,
                "name": v["name"],
                "type_text": v["type_text"],
                "points": len(coords),
                "last_sog": v.get("sog"),
                "last_seen": v.get("last_seen"),
            },
        }
        return {
            "mmsi": mmsi,
            "name": v["name"],
            "type_text": v["type_text"],
            "points_count": len(coords),
            "geojson": track_geojson,
        }


# ---------------------------------------------------------------- WebSocket Relay AISStream
AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"


@router.websocket("/stream")
async def websocket_ais_stream(ws: WebSocket):
    """WebSocket relay antara frontend dan AISStream.io.

    Klien (frontend) mengirim pesan JSON berisi kotak pemantauan:
      { "bbox": [west, south, east, north] }
    Server menghubungkan ke AISStream.io dan meneruskan pembaruan posisi kapal real-time.
    """
    await ws.accept()
    key = get_aisstream_key()
    if not key:
        await ws.send_json({
            "type": "error",
            "message": "API Key AISStream belum dikonfigurasi. Masukkan API Key pada panel AIS terlebih dahulu.",
        })
        await ws.close(1008, "API Key tidak ada")
        return

    try:
        import websockets  # noqa: E402
    except ImportError:
        await ws.send_json({
            "type": "error",
            "message": "Package 'websockets' belum terinstal di server backend.",
        })
        await ws.close(1011, "websockets not installed")
        return

    upstream = None
    reader_task: Optional[asyncio.Task] = None

    async def connect_upstream(bbox):
        west, south, east, north = bbox
        # AISStream bounding box format: [[lat_north, lon_west], [lat_south, lon_east]]
        subscribe_msg = {
            "APIKey": key,
            "BoundingBoxes": [[[north, west], [south, east]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }
        try:
            conn = await websockets.connect(AISSTREAM_WS_URL, ping_interval=20, ping_timeout=20)
            await conn.send(json.dumps(subscribe_msg))
            return conn
        except Exception as exc:
            logger.warning("Gagal menyambung ke AISStream.io: %s", exc)
            return None

    async def pump_upstream_messages(conn):
        try:
            async for raw in conn:
                try:
                    packet = json.loads(raw)
                    msg_type = packet.get("MessageType")
                    meta = packet.get("MetaData", {})

                    if msg_type == "PositionReport":
                        pos = packet.get("Message", {}).get("PositionReport", {})
                        mmsi = meta.get("MMSI") or pos.get("UserID")
                        if not mmsi:
                            continue
                        lat = pos.get("Latitude") if pos.get("Latitude") is not None else meta.get("latitude")
                        lon = pos.get("Longitude") if pos.get("Longitude") is not None else meta.get("longitude")
                        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            continue

                        heading = pos.get("TrueHeading")
                        if heading == 511:
                            heading = None

                        vessel = update_vessel_position(
                            mmsi=mmsi,
                            name=(meta.get("ShipName") or "").strip() or None,
                            lat=lat,
                            lon=lon,
                            sog=pos.get("Sog"),
                            cog=pos.get("Cog"),
                            heading=heading,
                            timestamp=meta.get("time_utc", ""),
                        )
                        await ws.send_json({
                            "type": "vessel_position",
                            "data": vessel,
                        })

                    elif msg_type == "ShipStaticData":
                        static = packet.get("Message", {}).get("ShipStaticData", {})
                        mmsi = meta.get("MMSI") or static.get("UserID")
                        if not mmsi:
                            continue
                        updated = update_vessel_static(
                            mmsi=mmsi,
                            name=(meta.get("ShipName") or static.get("Name") or "").strip() or None,
                            imo=static.get("ImoNumber"),
                            callsign=(static.get("CallSign") or "").strip() or None,
                            type_code=static.get("Type"),
                            destination=(static.get("Destination") or "").strip() or None,
                            draught=static.get("MaximumStaticDraught"),
                        )
                        if updated:
                            await ws.send_json({
                                "type": "vessel_static",
                                "data": {
                                    "mmsi": mmsi,
                                    "name": updated["name"],
                                    "type_code": updated["type_code"],
                                    "type_text": updated["type_text"],
                                    "imo": updated["imo"],
                                    "destination": updated["destination"],
                                    "draught": updated["draught"],
                                },
                            })
                except json.JSONDecodeError:
                    pass
                except Exception as ex:
                    logger.debug("Error processing AIS packet: %s", ex)
        except Exception:
            pass

    try:
        async for client_msg_raw in ws.iter_text():
            try:
                client_msg = json.loads(client_msg_raw)
            except json.JSONDecodeError:
                continue

            if "bbox" in client_msg:
                bbox = client_msg["bbox"]
                if (
                    isinstance(bbox, (list, tuple))
                    and len(bbox) == 4
                    and all(isinstance(v, (int, float)) for v in bbox)
                ):
                    # Tutup koneksi upstream lama jika ada perubahan bbox
                    if reader_task:
                        reader_task.cancel()
                    if upstream:
                        await upstream.close()

                    upstream = await connect_upstream(bbox)
                    if upstream:
                        reader_task = asyncio.create_task(pump_upstream_messages(upstream))
                        await ws.send_json({
                            "type": "status",
                            "status": "connected",
                            "message": "Terhubung ke AISStream.io",
                            "bbox": bbox,
                        })
                    else:
                        await ws.send_json({
                            "type": "error",
                            "message": "Gagal menghubungkan ke server AISStream.io. Periksa koneksi internet atau validitas API Key.",
                        })

    except WebSocketDisconnect:
        pass
    finally:
        if reader_task:
            reader_task.cancel()
        if upstream:
            try:
                await upstream.close()
            except Exception:
                pass
