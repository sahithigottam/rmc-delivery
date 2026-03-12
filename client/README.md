# RMC Delivery Route Optimizer - Gradio Client

A web-based UI for the RMC Delivery Route Optimizer API.

## Features

- 📍 OpenStreetMap-powered address autocomplete for start and destination
- 🚛 Vehicle input with RMC truck defaults
- ⚙️ Avoid route options: tolls, highways, ferries
- ⏰ Start time selection limited to max 12 hours from now
- 🛣️ Alternate route request + route index selector
- 🗺️ Interactive route map with markers and polyline
- 📊 Route summary with distance and duration
- 🧭 Turn-by-turn directions

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Make sure the FastAPI backend is running:
```bash
cd ..
uvicorn app.main:app --reload
```

3. Start the Gradio app:
```bash
python app.py
```

4. Open your browser to http://localhost:7860

## Usage

1. Enter the start address (e.g., "Queen Street, Auckland")
2. Enter the end address (e.g., "Hamilton City")
3. Optionally configure vehicle details, avoid options, and departure window
4. Click "Calculate Route"
5. View route ETA, alternate routes, map, and turn-by-turn directions
