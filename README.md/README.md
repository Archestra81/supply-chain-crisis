# Real-Time Supply Chain & Emergency Intelligence Dashboard

A hackathon MVP for visualizing critical supply-chain resources and live emergency alerts during a crisis or disaster scenario.

The dashboard combines an interactive Leaflet map, OpenStreetMap supply-node data, and USGS earthquake alerts to help operators quickly locate food, water, medical, and fuel resources near an affected area.

## Features

- Full-screen interactive map built with Leaflet.js
- Supply-node markers for:
  - Food and supermarkets
  - Water points and water towers
  - Pharmacies, hospitals, clinics, and doctors
  - Fuel stations
- Live incident feed powered by the USGS Earthquake GeoJSON feed
- Automatic simulated crisis-alert fallback if the external alert service is unavailable
- Category filters for food, water, medical, and fuel layers
- Alert priority levels: critical, high, medium, and low
- Clickable incident cards that focus the map on the alert location
- FastAPI backend with CORS enabled for local development
- Response caching to reduce repeated external API requests

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, httpx |
| Frontend | HTML, CSS, JavaScript |
| Map | Leaflet.js, OpenStreetMap |
| Supply data | OpenStreetMap Overpass API |
| Live alerts | USGS Earthquake Hazards Program |
| Styling | Custom CSS |

## Project Structure

```text
crisis-supply-dashboard/
├── backend/
│   └── main.py
├── frontend/
│   └── index.html
├── .gitignore
└── README.md
```

## Requirements

- Python 3.9 or newer
- pip
- An internet connection for OpenStreetMap and USGS data

## Setup and Run

### 1. Start the backend

From the project root:

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows Command Prompt
.venv\Scripts\activate.bat
```

Install dependencies:

```bash
pip install fastapi uvicorn httpx
```

Start the API:

```bash
uvicorn main:app --reload --port 8000
```

The backend will be available at:

```text
http://localhost:8000
```

### 2. Start the frontend

Open a second terminal and run:

```bash
cd frontend
python -m http.server 5500
```

Open the dashboard:

```text
http://localhost:5500
```

## API Endpoints

### Health check

```text
GET /api/health
```

Example response:

```json
{
  "status": "ok"
}
```

### Supply nodes

Search supply nodes around a latitude/longitude point:

```text
GET /api/supply-nodes?lat=12.9716&lon=77.5946&radius=2000
```

Or search using a bounding box:

```text
GET /api/supply-nodes?south=12.90&west=77.50&north=13.05&east=77.70
```

Response format:

```json
{
  "type": "FeatureCollection",
  "count": 12,
  "features": []
}
```

### Live alerts

```text
GET /api/live-alerts
```

Example response:

```json
{
  "source": "USGS Earthquake GeoJSON Feed",
  "live": true,
  "count": 25,
  "alerts": []
}
```

If USGS is unavailable, the API returns simulated crisis alerts and sets:

```json
{
  "live": false,
  "fallback_used": true
}
```

## Data Sources

- [OpenStreetMap](https://www.openstreetmap.org/) — supermarkets, pharmacies, hospitals, fuel stations, drinking-water points, and water towers
- [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) — OpenStreetMap query interface
- [USGS Earthquake Hazards Program](https://earthquake.usgs.gov/) — live earthquake GeoJSON feed
- [Leaflet](https://leafletjs.com/) — interactive mapping library

## How It Works

1. The frontend requests supply nodes within a 2 km radius of the selected operating area.
2. The FastAPI backend builds an Overpass QL query and requests matching OpenStreetMap features.
3. The backend converts the results into GeoJSON and returns them to the browser.
4. Leaflet renders categorized markers on the map.
5. The frontend separately requests live alerts from the backend.
6. The backend fetches the USGS earthquake feed and normalizes it for the dashboard.
7. If the external alert service fails, the backend returns simulated alerts so the dashboard remains usable during a demo.

## Notes

- This project is intended for a hackathon prototype and crisis-scenario demonstration.
- OpenStreetMap and Overpass are community services, so avoid sending excessive requests.
- The simulated alert and supply-node fallbacks are clearly labeled and should not be treated as real emergency data.
- For production use, add authentication, rate limiting, persistent caching, and an approved emergency-data feed.

## License

This project is released for educational and hackathon use.