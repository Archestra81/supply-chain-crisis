from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Crisis Supply Intelligence API", version="1.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"

HTTP_TIMEOUT = httpx.Timeout(connect=10, read=45, write=15, pool=10)
CACHE_SECONDS = 60

supply_cache: dict[str, Any] = {"time": 0, "key": "", "data": None}
alert_cache: dict[str, Any] = {"time": 0, "data": None}


def classify(tags: dict[str, Any]) -> tuple[str, str]:
    amenity = str(tags.get("amenity", "")).lower()
    shop = str(tags.get("shop", "")).lower()
    man_made = str(tags.get("man_made", "")).lower()

    if amenity == "supermarket" or shop == "supermarket":
        return "food", "Food / Supermarket"
    if amenity in {"pharmacy", "hospital", "clinic", "doctors"}:
        return "medical", "Medical"
    if amenity == "fuel":
        return "fuel", "Fuel"
    if amenity == "drinking_water" or man_made == "water_tower":
        return "water", "Water"

    return "other", "Other"


def get_coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    if element.get("type") == "node":
        lat = element.get("lat")
        lon = element.get("lon")
        if lat is not None and lon is not None:
            return float(lat), float(lon)

    center = element.get("center", {})
    lat = center.get("lat")
    lon = center.get("lon")

    if lat is not None and lon is not None:
        return float(lat), float(lon)

    return None


def to_feature(element: dict[str, Any]) -> dict[str, Any] | None:
    point = get_coordinates(element)
    if not point:
        return None

    lat, lon = point
    tags = element.get("tags", {})
    category, label = classify(tags)
    name = tags.get("name") or tags.get("brand") or tags.get("operator") or label

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "id": f"osm-{element.get('type')}-{element.get('id')}",
            "name": name,
            "category": category,
            "label": label,
            "lat": lat,
            "lon": lon,
        },
    }


def build_overpass_query(
    south: float,
    west: float,
    north: float,
    east: float,
) -> str:
    bbox = f"({south},{west},{north},{east})"

    return (
        "[out:json][25];"
        "("
        f'node["amenity"="supermarket"]{bbox};'
        f'way["amenity"="supermarket"]{bbox};'
        f'node["shop"="supermarket"]{bbox};'
        f'way["shop"="supermarket"]{bbox};'
        f'node["amenity"="pharmacy"]{bbox};'
        f'way["amenity"="pharmacy"]{bbox};'
        f'node["amenity"="hospital"]{bbox};'
        f'way["amenity"="hospital"]{bbox};'
        f'node["amenity"="fuel"]{bbox};'
        f'way["amenity"="fuel"]{bbox};'
        f'node["amenity"="drinking_water"]{bbox};'
        f'way["amenity"="drinking_water"]{bbox};'
        f'node["man_made"="water_tower"]{bbox};'
        f'way["man_made"="water_tower"]{bbox};'
        ");"
        "out center tags;"
    )


def radius_bbox(
    lat: float,
    lon: float,
    radius: int,
) -> tuple[float, float, float, float]:
    lat_delta = radius / 111320
    lon_delta = radius / (111320 * max(0.1, abs(math.cos(math.radians(lat)))))

    return (
        max(-90, lat - lat_delta),
        max(-180, lon - lon_delta),
        min(90, lat + lat_delta),
        min(180, lon + lon_delta),
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/supply-nodes")
async def supply_nodes(
    lat: float = Query(12.9716, ge=-90, le=90),
    lon: float = Query(77.5946, ge=-180, le=180),
    radius: int = Query(5000, ge=100, le=50000),
    south: float | None = Query(None, ge=-90, le=90),
    west: float | None = Query(None, ge=-180, le=180),
    north: float | None = Query(None, ge=-90, le=90),
    east: float | None = Query(None, ge=-180, le=180),
) -> dict[str, Any]:
    if all(value is not None for value in (south, west, north, east)):
        bbox = (south, west, north, east)
    elif any(value is not None for value in (south, west, north, east)):
        raise HTTPException(
            status_code=400,
            detail="Provide south, west, north and east together.",
        )
    else:
        bbox = radius_bbox(lat, lon, radius)

    s, w, n, e = bbox
    cache_key = f"{s:.5f}:{w:.5f}:{n:.5f}:{e:.5f}"
    now = time.time()

    if (
        supply_cache["data"]
        and now - supply_cache["time"] < CACHE_SECONDS
        and supply_cache["key"] == cache_key
    ):
        return supply_cache["data"]

    query = build_overpass_query(s, w, n, e)
    last_error = "No Overpass endpoint was reachable."

    for overpass_url in OVERPASS_URLS:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.post(
                    overpass_url,
                    data={"data": query},
                    headers={
                        "User-Agent": "CrisisSupplyDashboard/1.4",
                        "Accept": "application/json",
                    },
                )

                if response.status_code != 200:
                    last_error = (
                        f"{overpass_url} returned HTTP {response.status_code}: "
                        f"{response.text[:300]}"
                    )
                    continue

                payload = response.json()
                break

        except httpx.TimeoutException:
            last_error = f"{overpass_url} timed out."
            continue
        except httpx.RequestError as error:
            last_error = f"{overpass_url} connection failed: {error}"
            continue
        except ValueError:
            last_error = f"{overpass_url} returned invalid JSON."
            continue
    else:
        raise HTTPException(
            status_code=502,
            detail=f"All Overpass endpoints failed. Last error: {last_error}",
        )

    features = [
        converted
        for element in payload.get("elements", [])
        if (converted := to_feature(element)) is not None
    ]

    result = {
        "type": "FeatureCollection",
        "generated_at": int(now * 1000),
        "query": {"south": s, "west": w, "north": n, "east": e},
        "count": len(features),
        "features": features,
    }

    supply_cache.update({"time": now, "key": cache_key, "data": result})
    return result


def priority_for_magnitude(magnitude: float) -> str:
    if magnitude >= 6:
        return "critical"
    if magnitude >= 4.5:
        return "high"
    if magnitude >= 2.5:
        return "medium"
    return "low"


def normalize_usgs_alert(feature: dict[str, Any]) -> dict[str, Any] | None:
    coords = feature.get("geometry", {}).get("coordinates", [])
    if len(coords) < 2:
        return None

    properties = feature.get("properties", {})

    try:
        magnitude = float(properties.get("mag") or 0)
    except (TypeError, ValueError):
        magnitude = 0

    return {
        "id": feature.get("id"),
        "title": properties.get("title") or properties.get("place") or "Earthquake",
        "place": properties.get("place") or "Unknown location",
        "magnitude": magnitude,
        "priority": priority_for_magnitude(magnitude),
        "time": properties.get("time"),
        "url": properties.get("url"),
        "lat": float(coords[1]),
        "lon": float(coords[0]),
        "depth_km": coords[2] if len(coords) > 2 else None,
        "source": "USGS Earthquake Hazards Program",
        "live": True,
    }


def simulated_alerts() -> list[dict[str, Any]]:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    alerts = [
        {
            "id": "sim-grid-1",
            "title": "Power grid disruption",
            "place": "Central Bengaluru corridor",
            "magnitude": 0,
            "priority": "high",
            "lat": 12.9716,
            "lon": 77.5946,
            "depth_km": None,
            "url": None,
        },
        {
            "id": "sim-road-1",
            "title": "Major arterial road blockage",
            "place": "Outer Ring Road sector",
            "magnitude": 0,
            "priority": "critical",
            "lat": 12.9352,
            "lon": 77.6245,
            "depth_km": None,
            "url": None,
        },
        {
            "id": "sim-water-1",
            "title": "Water distribution pressure drop",
            "place": "North Bengaluru zone",
            "magnitude": 0,
            "priority": "medium",
            "lat": 13.0358,
            "lon": 77.5970,
            "depth_km": None,
            "url": None,
        },
        {
            "id": "sim-medical-1",
            "title": "Emergency medical demand surge",
            "place": "South Bengaluru zone",
            "magnitude": 0,
            "priority": "high",
            "lat": 12.9121,
            "lon": 77.6446,
            "depth_km": None,
            "url": None,
        },
    ]

    for index, alert in enumerate(alerts):
        alert["time"] = now_ms - index * 7 * 60 * 1000
        alert["source"] = "Simulated Crisis Feed"
        alert["live"] = False

    return alerts


@app.get("/api/live-alerts")
async def live_alerts() -> dict[str, Any]:
    now = time.time()

    if alert_cache["data"] and now - alert_cache["time"] < CACHE_SECONDS:
        return alert_cache["data"]

    usgs_error = None
    alerts = []
    source = "Simulated Crisis Feed"
    live = False

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(
                USGS_URL,
                headers={"User-Agent": "CrisisSupplyDashboard/1.4"},
            )
            response.raise_for_status()
            payload = response.json()

        alerts = [
            normalized
            for feature in payload.get("features", [])
            if (normalized := normalize_usgs_alert(feature)) is not None
        ]

        if alerts:
            source = "USGS Earthquake GeoJSON Feed"
            live = True

    except httpx.TimeoutException:
        usgs_error = "USGS request timed out."
    except httpx.HTTPStatusError as error:
        usgs_error = f"USGS returned HTTP {error.response.status_code}."
    except httpx.RequestError:
        usgs_error = "Could not connect to USGS."
    except ValueError:
        usgs_error = "USGS returned invalid JSON."

    if not alerts:
        alerts = simulated_alerts()

    rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}

    alerts.sort(
        key=lambda alert: (rank.get(alert["priority"], 0), alert["magnitude"]),
        reverse=True,
    )

    result = {
        "source": source,
        "live": live,
        "fallback_used": not live,
        "usgs_error": usgs_error,
        "generated_at": int(now * 1000),
        "count": len(alerts),
        "alerts": alerts,
    }

    alert_cache.update({"time": now, "data": result})
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)