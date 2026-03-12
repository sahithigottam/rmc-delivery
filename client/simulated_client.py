"""RMC Delivery Route Optimizer — Simulation Client (Gradio 6)
Same UI as app.py PLUS:
  • ▶ Simulate button — animates a truck marker along the route
  • Dynamic re-routing — periodically checks traffic; if delay exceeds
    a threshold the route is recalculated and the map / metrics update live
"""
import gradio as gr
import httpx
import folium
import polyline as polyline_codec
import json
import asyncio
import math
import time
import threading
from datetime import datetime
from folium import plugins
from typing import Any, Optional, List, Tuple, cast

# ── API ─────────────────────────────────────────────────────────────────────
API_BASE_URL = "http://localhost:8000/api/v1"

# ── Simulation state (module-level so the background thread can see it) ─────
_sim_running = False
_sim_paused = False
_sim_cancel = threading.Event()
_last_route_data: Optional[dict] = None  # stash the most recent API result

# ============================================================================
# Gradio 6 Theme — MD3 (same as app.py)
# ============================================================================
MD3_THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.purple,
    secondary_hue=gr.themes.colors.purple,
    neutral_hue=gr.themes.colors.gray,
    text_size=gr.themes.sizes.text_md,
    spacing_size=gr.themes.sizes.spacing_md,
    radius_size=gr.themes.sizes.radius_sm,
    font=[
        gr.themes.GoogleFont("Google Sans"),
        gr.themes.GoogleFont("Roboto"),
        "sans-serif",
    ],
).set(
    body_background_fill="white",
    body_text_color="#1c1b1f",
    body_text_color_subdued="#49454f",
    background_fill_primary="white",
    background_fill_secondary="white",
    block_background_fill="transparent",
    block_border_width="0px",
    block_shadow="none",
    block_label_text_color="#49454f",
    block_label_text_size="*text_sm",
    block_label_text_weight="500",
    block_title_text_color="#49454f",
    block_title_text_size="*text_sm",
    block_title_text_weight="500",
    input_background_fill="white",
    input_background_fill_dark="#1c1b1f",
    input_background_fill_focus="white",
    input_background_fill_hover="white",
    input_border_color="#79747e",
    input_border_color_focus="#6750a4",
    input_border_color_hover="#1c1b1f",
    input_border_width="1px",
    input_radius="8px",
    input_padding="12px 16px",
    input_text_size="*text_md",
    input_shadow="none",
    input_shadow_focus="none",
    border_color_primary="#cac4d0",
    border_color_accent="#6750a4",
    button_primary_background_fill="#6750a4",
    button_primary_background_fill_hover="#7965af",
    button_primary_border_color="#6750a4",
    button_primary_border_color_hover="#7965af",
    button_primary_text_color="white",
    button_primary_text_color_hover="white",
    button_primary_shadow="0 1px 2px rgba(0,0,0,0.3), 0 1px 3px 1px rgba(0,0,0,0.15)",
    button_primary_shadow_hover="0 1px 2px rgba(0,0,0,0.3), 0 2px 6px 2px rgba(0,0,0,0.15)",
    button_primary_shadow_active="none",
    button_secondary_background_fill="transparent",
    button_secondary_border_color="#79747e",
    button_secondary_text_color="#6750a4",
    checkbox_background_color="white",
    checkbox_background_color_selected="#6750a4",
    checkbox_border_color="#79747e",
    checkbox_border_color_focus="#6750a4",
    checkbox_border_color_hover="#6750a4",
    checkbox_border_color_selected="#6750a4",
    checkbox_border_radius="4px",
    checkbox_label_text_color="#1c1b1f",
    checkbox_label_text_size="*text_sm",
    checkbox_label_text_weight="500",
    checkbox_label_background_fill="transparent",
    checkbox_label_background_fill_hover="rgba(103,80,164,0.08)",
    checkbox_label_background_fill_selected="rgba(103,80,164,0.12)",
    checkbox_label_border_color="#79747e",
    checkbox_label_border_width="1px",
    checkbox_label_padding="6px 14px",
    checkbox_label_gap="8px",
    slider_color="#6750a4",
    accordion_text_color="#1c1b1f",
    color_accent="#6750a4",
)


# ============================================================================
# CSS — same as app.py + simulation extras
# ============================================================================
CUSTOM_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --header-h: 56px;
    --sidebar-width: 400px;
    --md-surface: #fffbfe;
    --md-surface-variant: #f3edf7;
    --md-surface-container: #f7f2fa;
    --md-surface-container-low: #f7f2fa;
    --md-surface-container-high: #ece6f0;
    --md-on-surface: #1c1b1f;
    --md-on-surface-variant: #49454f;
    --md-outline: #79747e;
    --md-outline-variant: #cac4d0;
    --md-primary: #6750a4;
    --md-on-primary: #ffffff;
    --md-primary-container: #eaddff;
    --md-on-primary-container: #21005d;
    --md-secondary-container: #e8def8;
    --md-tertiary: #7d5260;
    --md-error: #b3261e;
    --md-success: #1e8e3e;
    --md-radius-sm: 8px;
    --md-radius-md: 12px;
    --md-radius-lg: 16px;
    --md-radius-full: 100px;
}

/* ── Shell ──────────────────────────────────────────── */
.gradio-container {
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    height: 100vh !important;
    overflow: hidden !important;
}
footer { display: none !important; }

#app-shell {
    display: flex !important;
    flex-direction: column !important;
    height: 100vh !important;
    gap: 0 !important;
    padding: 0 !important;
    border: none !important;
    box-shadow: none !important;
    background: transparent !important;
    overflow: hidden !important;
}
#app-shell > div {
    border: none !important; box-shadow: none !important; background: transparent !important;
}

/* ── TOP APP BAR ───────────────────────────────────── */
#top-bar {
    padding: 0 !important;
    gap: 0 !important;
    min-height: var(--header-h) !important;
    max-height: var(--header-h) !important;
    background: transparent !important;
}
.md-top-app-bar {
    display: flex;
    align-items: center;
    gap: 16px;
    height: var(--header-h);
    padding: 0 24px;
    background: var(--md-primary);
    color: var(--md-on-primary);
    box-shadow: 0 2px 4px -1px rgba(0,0,0,0.2), 0 4px 5px rgba(0,0,0,0.14), 0 1px 10px rgba(0,0,0,0.12);
    position: relative;
    z-index: 100;
}
.md-top-app-bar .bar-icon {
    width: 40px; height: 40px;
    border-radius: var(--md-radius-full);
    background: rgba(255,255,255,0.15);
    display: flex; align-items: center; justify-content: center;
    font-size: 20px;
    flex-shrink: 0;
}
.md-top-app-bar .bar-title {
    font-size: 22px; font-weight: 400; letter-spacing: 0; flex: 1;
}
.md-top-app-bar .bar-subtitle {
    font-size: 12px; opacity: 0.85; font-weight: 400; letter-spacing: 0.15px;
}

/* ── BODY ROW ─────────────────────────────────────── */
#app-body {
    display: flex !important;
    flex-direction: row !important;
    flex: 1 !important;
    height: calc(100vh - var(--header-h)) !important;
    gap: 0 !important;
    padding: 0 !important;
    border: none !important;
    box-shadow: none !important;
    background: transparent !important;
    overflow: hidden !important;
}
#app-body > div {
    border: none !important; box-shadow: none !important; background: transparent !important;
}

/* ── SIDEBAR ────────────────────────────────────────── */
#sidebar {
    width: var(--sidebar-width) !important;
    min-width: var(--sidebar-width) !important;
    max-width: var(--sidebar-width) !important;
    height: calc(100vh - var(--header-h)) !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    background: white !important;
    border-right: 1px solid var(--md-outline-variant) !important;
    padding: 0 !important;
    gap: 0 !important;
    flex-shrink: 0 !important;
}
#sidebar::-webkit-scrollbar { width: 4px; }
#sidebar::-webkit-scrollbar-thumb { background: var(--md-outline-variant); border-radius: 2px; }

/* ── MAP ────────────────────────────────────────────── */
#map-area {
    flex: 1 !important;
    height: calc(100vh - var(--header-h)) !important;
    min-width: 0 !important;
    padding: 0 !important;
    gap: 0 !important;
    overflow: hidden !important;
    background: #e8eaed !important;
}
#map-container, #map-container iframe, #map-container > div {
    width: 100% !important;
    height: calc(100vh - var(--header-h)) !important;
    border: none !important;
    border-radius: 0 !important;
}

/* ── FORM CONTROLS ──────────────────────────────────── */
.md-textbox,
.md-textbox > div {
    background: white !important; border: none !important; box-shadow: none !important;
}
.md-textbox input,
.md-textbox textarea {
    border: 1px solid var(--md-outline) !important;
    border-radius: var(--md-radius-sm) !important;
    background: white !important;
    color: var(--md-on-surface) !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 8px 14px !important;
    font-size: 14px !important;
    font-family: inherit !important;
    box-shadow: none !important;
    transition: border-color 0.2s !important;
    caret-color: var(--md-primary) !important;
}
.md-textbox input:hover,
.md-textbox textarea:hover { border-color: var(--md-on-surface) !important; }
.md-textbox input:focus,
.md-textbox textarea:focus {
    border-color: var(--md-primary) !important;
    border-width: 2px !important;
    padding: 7px 13px !important;
    background: white !important;
    box-shadow: none !important;
    outline: none !important;
}
.md-textbox label span,
.md-textbox > label {
    color: var(--md-on-surface-variant) !important;
    font-size: 12px !important; font-weight: 500 !important; letter-spacing: 0.4px !important;
}

.md-dropdown,
.md-dropdown > div,
.md-dropdown div[data-testid] {
    background: white !important; border: none !important; box-shadow: none !important;
}
.md-dropdown input {
    border: 1px solid var(--md-outline) !important;
    border-radius: var(--md-radius-sm) !important;
    background: white !important;
    color: var(--md-on-surface) !important;
    height: 42px !important;
    min-height: 42px !important;
    max-height: 42px !important;
    padding: 8px 14px !important;
    font-size: 14px !important;
    font-family: inherit !important;
    box-shadow: none !important;
    transition: border-color 0.2s !important;
}
.md-dropdown input:hover { border-color: var(--md-on-surface) !important; }
.md-dropdown input:focus {
    border-color: var(--md-primary) !important;
    border-width: 2px !important;
    padding: 7px 13px !important;
    outline: none !important;
}
.md-dropdown label span,
.md-dropdown > label {
    color: var(--md-on-surface-variant) !important;
    font-size: 12px !important; font-weight: 500 !important; letter-spacing: 0.4px !important;
}
.md-dropdown .wrap-inner,
.md-dropdown .secondary-wrap {
    border: none !important; padding: 0 !important; min-height: unset !important;
    background: transparent !important;
}
.md-dropdown ul { background: white !important; border-radius: var(--md-radius-sm) !important; }
.md-dropdown ul li { font-size: 14px !important; padding: 10px 14px !important; }
.md-dropdown ul li:hover { background: rgba(103,80,164,0.08) !important; }

/* ── BUTTONS ────────────────────────────────────────── */
#search-btn {
    margin: 4px 0 0 !important;
    border: none !important;
    border-radius: var(--md-radius-full) !important;
    min-height: 48px !important;
    background: var(--md-primary) !important;
    color: var(--md-on-primary) !important;
    font-weight: 500 !important; font-size: 14px !important;
    font-family: inherit !important; letter-spacing: 0.1px;
    cursor: pointer;
    transition: box-shadow 0.2s, background 0.2s !important;
}
#search-btn:hover { background: #7965af !important; }
#search-btn:active { box-shadow: none !important; }

/* Simulation toggle button — contextual colors via JS class */
#sim-toggle {
    margin: 0 !important;
    border: none !important;
    border-radius: var(--md-radius-full) !important;
    min-height: 40px !important;
    background: #1e8e3e !important;
    color: white !important;
    font-weight: 500 !important; font-size: 13px !important;
    font-family: inherit !important; letter-spacing: 0.1px;
    cursor: pointer;
    transition: background 0.2s !important;
    flex: 1 !important;
}
#sim-toggle:hover { background: #1a7c36 !important; }
/* Stop button — red accent */
#stop-btn {
    margin: 0 !important;
    border: none !important;
    border-radius: var(--md-radius-full) !important;
    min-height: 40px !important;
    min-width: 40px !important;
    max-width: 40px !important;
    background: var(--md-error) !important;
    color: white !important;
    font-weight: 500 !important; font-size: 16px !important;
    font-family: inherit !important;
    cursor: pointer;
    padding: 0 !important;
    display: flex !important; align-items: center !important; justify-content: center !important;
}
#stop-btn:hover { background: #922018 !important; }

/* ── CHIPS ──────────────────────────────────────────── */
.md-chip {
    background: white !important;
    border: 1px solid var(--md-outline) !important;
    border-radius: 20px !important;
    padding: 6px 14px !important;
    margin: 0 !important;
    min-height: auto !important;
    transition: all 0.2s !important;
    cursor: pointer;
    box-shadow: none !important;
}
.md-chip > div { background: transparent !important; border: none !important; box-shadow: none !important; }
.md-chip:hover { background: rgba(103,80,164,0.08) !important; }
.md-chip label {
    font-size: 13px !important; font-weight: 500 !important;
    color: var(--md-on-surface) !important; gap: 6px !important;
    cursor: pointer !important; letter-spacing: 0.1px !important;
    white-space: nowrap !important;
}
.md-chip input[type='checkbox'] {
    accent-color: var(--md-primary) !important; width: 16px !important; height: 16px !important;
}

/* ── SECTIONS ───────────────────────────────────────── */
#address-bar {
    padding: 20px 20px 16px !important;
    gap: 12px !important;
    background: white !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
}
#status-toast {
    margin: 0; border-radius: 0;
    padding: 12px 20px; font-size: 14px;
    letter-spacing: 0.25px;
    color: #fff; background: #323232;
}
#status-toast.error { background: var(--md-error); }
#status-toast.success { background: var(--md-success); }
#status-toast.hidden { display: none; }

#metrics-section { padding: 0 !important; gap: 0 !important; background: transparent !important; }
#results-card {
    display: flex; gap: 0; align-items: stretch;
    padding: 0; margin: 0;
    background: var(--md-surface-container-low);
    border: none !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}
.metric-box {
    flex: 1; text-align: center;
    padding: 16px 8px;
    border-right: 1px solid var(--md-outline-variant);
}
.metric-box:last-child { border-right: none; }
.metric-value {
    font-size: 22px; font-weight: 400;
    color: var(--md-on-surface); line-height: 1.2;
}
.metric-value span {
    font-size: 11px; color: var(--md-on-surface-variant);
    font-weight: 400; margin-left: 2px;
}
.metric-label {
    font-size: 11px; color: var(--md-on-surface-variant);
    text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px;
    font-weight: 500;
}
.route-badge {
    background: var(--md-primary-container); color: var(--md-on-primary-container);
    border-radius: var(--md-radius-full); padding: 6px 16px;
    font-size: 12px; font-weight: 500;
    align-self: center; margin: 0 12px; white-space: nowrap;
    letter-spacing: 0.1px;
}

.section-label {
    padding: 16px 20px 8px;
    font-size: 11px; font-weight: 500;
    color: var(--md-on-surface-variant);
    text-transform: uppercase; letter-spacing: 0.5px;
    background: white;
}

#quick-settings {
    padding: 0 20px 16px !important;
    gap: 12px !important;
    background: white !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
}
#quick-settings > div { gap: 12px !important; }

#route-prefs {
    padding: 8px 20px 16px !important;
    gap: 14px !important;
    background: white !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
}
#route-prefs > div {
    gap: 8px !important; flex-wrap: wrap !important;
    background: transparent !important; border: none !important; box-shadow: none !important;
}
#route-prefs .md-dropdown { margin-top: 4px !important; }

/* ── SIMULATION PANEL ───────────────────────────────── */
#sim-section {
    padding: 12px 20px 16px !important;
    gap: 10px !important;
    background: white !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
}
#sim-section > div { gap: 8px !important; }

.sim-status-bar {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px;
    background: var(--md-surface-container-low);
    border-radius: var(--md-radius-sm);
    font-size: 13px; color: var(--md-on-surface);
}
.sim-status-bar .sim-dot {
    width: 10px; height: 10px; border-radius: 50%;
    flex-shrink: 0;
}
.sim-dot.idle { background: var(--md-outline); }
.sim-dot.running { background: var(--md-success); animation: pulse 1.5s infinite; }
.sim-dot.rerouting { background: #fbbc04; animation: pulse 0.6s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

.sim-progress {
    height: 4px; background: var(--md-outline-variant);
    border-radius: 2px; overflow: hidden; margin-top: 2px;
}
.sim-progress-fill {
    height: 100%; background: var(--md-primary);
    border-radius: 2px; transition: width 0.4s ease;
}

/* ── SCHEDULE / ACCORDION ───────────────────────────── */
#trip-details { padding: 0 !important; gap: 0 !important; }
#trip-details .accordion {
    border: none !important; border-radius: 0 !important; margin: 0 !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
    background: transparent !important;
}
#trip-details button,
#trip-details summary,
#trip-details .label-wrap,
#trip-details [role="button"] {
    padding: 16px 20px !important;
    background: white !important;
    font-size: 14px !important; font-weight: 500 !important;
    color: var(--md-on-surface) !important;
    letter-spacing: 0.1px !important; border: none !important;
}
#trip-details .content,
#trip-details .wrap,
#trip-details [role="region"] {
    padding: 4px 20px 16px !important; background: white !important;
}
#trip-details-inner { padding: 4px 20px 16px !important; gap: 14px !important; }
#trip-details-inner > div { gap: 12px !important; }

.md-datetime,
.md-datetime > div { background: white !important; border: none !important; box-shadow: none !important; }
.md-datetime input {
    border: 1px solid var(--md-outline) !important;
    border-radius: var(--md-radius-sm) !important;
    background: white !important;
    height: 42px !important; min-height: 42px !important;
    padding: 8px 14px !important; font-size: 14px !important;
}
.flatpickr-calendar { z-index: 200000 !important; }

/* ── DIRECTIONS ─────────────────────────────────────── */
#directions-section { padding: 0 !important; gap: 0 !important; }
#directions-panel {
    border: none !important; border-radius: 0 !important;
    box-shadow: none !important; overflow: hidden; background: white;
}
.directions-header {
    padding: 16px 20px; font-size: 14px; font-weight: 500;
    color: var(--md-on-surface); border-bottom: 1px solid var(--md-outline-variant);
    background: white;
    display: flex; align-items: center; gap: 10px; letter-spacing: 0.1px;
}
.directions-list { max-height: none; overflow-y: visible; }
.direction-step {
    display: flex; gap: 14px;
    padding: 12px 20px;
    border-bottom: 1px solid var(--md-outline-variant);
    transition: background 0.15s;
}
.direction-step:hover { background: rgba(103,80,164,0.05); }
.direction-step:last-child { border-bottom: none; }
.step-number {
    width: 24px; height: 24px; border-radius: var(--md-radius-full);
    background: var(--md-primary); color: var(--md-on-primary);
    font-size: 11px; font-weight: 500;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; margin-top: 1px;
}
.step-content { flex: 1; }
.step-instruction { font-size: 14px; line-height: 1.5; color: var(--md-on-surface); letter-spacing: 0.25px; }
.step-distance { font-size: 12px; color: var(--md-on-surface-variant); margin-top: 2px; }

/* ── Mobile ─────────────────────────────────────────── */
@media (max-width: 768px) {
    #app-body { flex-direction: column !important; height: auto !important; overflow: auto !important; }
    #sidebar {
        width: 100% !important; min-width: 100% !important; max-width: 100% !important;
        height: auto !important; max-height: 55vh !important;
        border-right: none !important; border-bottom: 1px solid var(--md-outline-variant) !important;
    }
    #map-area { height: 50vh !important; }
    #map-container, #map-container iframe, #map-container > div { height: 50vh !important; }
}
"""


# ============================================================================
# Helpers
# ============================================================================

def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance in metres between two coords."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _interpolate(p1: Tuple[float, float], p2: Tuple[float, float], t: float) -> Tuple[float, float]:
    """Linear interpolation between two lat/lng points, t ∈ [0,1]."""
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def _subsample_route(points: List[Tuple[float, float]], n: int = 200) -> List[Tuple[float, float]]:
    """
    Convert a polyline (variable spacing) into ~n evenly-spaced points.
    This gives smoother animation at constant speed.
    """
    if len(points) < 2:
        return points
    # Compute cumulative arc-length
    dists = [0.0]
    for i in range(1, len(points)):
        dists.append(dists[-1] + _haversine(points[i - 1][0], points[i - 1][1],
                                             points[i][0], points[i][1]))
    total = dists[-1]
    if total == 0:
        return points

    result: List[Tuple[float, float]] = []
    seg = 0
    for k in range(n + 1):
        target = total * k / n
        while seg < len(dists) - 2 and dists[seg + 1] < target:
            seg += 1
        seg_len = dists[seg + 1] - dists[seg]
        t = (target - dists[seg]) / seg_len if seg_len > 0 else 0.0
        result.append(_interpolate(points[seg], points[seg + 1], min(t, 1.0)))
    return result


# ============================================================================
# API Functions
# ============================================================================

async def estimate_route(
    start_address: str,
    end_address: str,
    vehicle_type: str,
    vehicle_id: str,
    load_weight: float,
    load_volume: float,
    departure_datetime,
    delivery_time: str,
    priority: str,
    request_alternatives: bool,
    avoid_tolls: bool,
    avoid_highways: bool,
    avoid_ferries: bool,
    selected_route_idx: int,
):
    """Call API to estimate route"""
    global _last_route_data
    no_route_dropdown = gr.update(choices=[("Fastest", "0")], value="0")

    if not start_address or not end_address:
        return (
            '<div id="status-toast" class="error">Enter both pickup and destination</div>',
            create_empty_map(),
            create_metrics_html(None),
            "",
            create_sim_status("idle", "Search a route first"),
            no_route_dropdown,
        )

    try:
        departure_time_str = None
        if departure_datetime:
            if hasattr(departure_datetime, "isoformat"):
                departure_time_str = departure_datetime.isoformat()
            else:
                departure_time_str = str(departure_datetime)

        max_delivery_minutes = None
        if delivery_time and delivery_time != "No Limit":
            max_delivery_minutes = int(delivery_time.split()[0])

        avoid = []
        if avoid_tolls:
            avoid.append("tolls")
        if avoid_highways:
            avoid.append("highways")
        if avoid_ferries:
            avoid.append("ferries")

        payload = {
            "start": {"address": start_address},
            "end": {"address": end_address},
            "vehicle_type": vehicle_type,
            "vehicle_id": vehicle_id or None,
            "load_weight": load_weight or 0,
            "load_volume": load_volume or 0,
            "departure_datetime": departure_time_str,
            "max_delivery_minutes": max_delivery_minutes,
            "priority": priority,
            "request_alternatives": request_alternatives,
            "avoid": avoid if avoid else None,
            "route_index": int(selected_route_idx) if selected_route_idx else 0,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{API_BASE_URL}/routes/estimate", json=payload)

            if response.status_code == 200:
                data = response.json()
                _last_route_data = data
                route_dropdown = _build_route_choices(data)
                return (
                    '<div id="status-toast" class="hidden"></div>',
                    create_route_map(data),
                    create_metrics_html(data),
                    create_directions_html(data.get("route_steps", [])),
                    create_sim_status("idle", "Ready — press ▶ Simulate"),
                    route_dropdown,
                )
            else:
                error = response.json().get("detail", "Unknown error")
                return (
                    f'<div id="status-toast" class="error">{error}</div>',
                    create_empty_map(),
                    create_metrics_html(None),
                    "",
                    create_sim_status("idle", "Route failed"),
                    no_route_dropdown,
                )

    except Exception as e:
        return (
            f'<div id="status-toast" class="error">Connection error: {e}</div>',
            create_empty_map(),
            create_metrics_html(None),
            "",
            create_sim_status("idle", "Connection error"),
            no_route_dropdown,
        )


def _build_route_choices(data: dict):
    """Build dynamic dropdown choices from alternatives_summary."""
    alts = data.get("alternatives_summary") or []
    selected = data.get("selected_route_index", 0)
    if not alts:
        return gr.update(choices=[("Fastest", "0")], value="0")
    choices = []
    for alt in alts:
        idx = alt.get("index", 0)
        summary = alt.get("summary", f"Route {idx + 1}")
        km = alt.get("distance_km", 0)
        mins = alt.get("duration_mins", 0)
        hrs = int(mins // 60)
        rm = int(mins % 60)
        time_str = f"{hrs}h {rm}m" if hrs else f"{rm} min"
        label = f"{summary} — {km:.0f} km, {time_str}"
        if idx == 0:
            label = f"⚡ {label}"
        choices.append((label, str(idx)))
    return gr.update(choices=choices, value=str(selected))


# ============================================================================
# Map builders
# ============================================================================

def create_empty_map() -> str:
    m = folium.Map(location=[-41.2865, 174.7762], zoom_start=6, tiles="cartodbpositron")
    plugins.Fullscreen(position="topright").add_to(m)
    return m._repr_html_()


def create_route_map(data: dict, truck_pos: Optional[Tuple[float, float]] = None,
                     traversed: Optional[List[Tuple[float, float]]] = None,
                     remaining: Optional[List[Tuple[float, float]]] = None) -> str:
    """Create route map, optionally showing a moving truck marker."""
    start_lat = data.get("start_lat")
    start_lng = data.get("start_lng")
    end_lat = data.get("end_lat")
    end_lng = data.get("end_lng")

    if not all([start_lat, start_lng, end_lat, end_lng]):
        return create_empty_map()

    center_lat = (float(start_lat) + float(end_lat)) / 2
    center_lng = (float(start_lng) + float(end_lng)) / 2

    m = folium.Map(location=[center_lat, center_lng], zoom_start=12, tiles="cartodbpositron")
    plugins.Fullscreen(position="topright").add_to(m)

    # Start marker
    folium.CircleMarker(
        [start_lat, start_lng], radius=10, color="white",
        fill=True, fillColor="#1a73e8", fillOpacity=1, weight=3,
        popup=data.get("resolved_start_address", "Start"),
    ).add_to(m)

    # End marker
    folium.Marker(
        [end_lat, end_lng],
        popup=data.get("resolved_end_address", "Destination"),
        icon=folium.Icon(color="red", icon="flag", prefix="fa"),
    ).add_to(m)

    # Route polyline
    all_points = []
    if data.get("polyline"):
        try:
            all_points = polyline_codec.decode(data["polyline"])
        except Exception:
            pass

    if traversed is not None and remaining is not None:
        # Simulation mode — show traversed (gray) and remaining (blue)
        if traversed:
            folium.PolyLine(traversed, weight=6, color="#9aa0a6", opacity=0.6, dash_array="6").add_to(m)
        if remaining:
            folium.PolyLine(remaining, weight=6, color="#1a73e8", opacity=1).add_to(m)
    elif all_points:
        folium.PolyLine(all_points, weight=10, color="#1a73e8", opacity=0.3).add_to(m)
        folium.PolyLine(all_points, weight=5, color="#1a73e8", opacity=1).add_to(m)

    # Truck marker
    if truck_pos:
        folium.Marker(
            truck_pos,
            icon=folium.DivIcon(
                icon_size=(36, 36),
                icon_anchor=(18, 18),
                html='<div style="font-size:28px;text-shadow:0 2px 6px rgba(0,0,0,0.4);">🚚</div>',
            ),
        ).add_to(m)

    fit_pts = all_points or [[start_lat, start_lng], [end_lat, end_lng]]
    m.fit_bounds(fit_pts, padding=[60, 60])
    return m._repr_html_()


def create_metrics_html(data: Optional[dict] = None, extra_label: str = "") -> str:
    if not data:
        return """
        <div id="results-card" style="opacity:0.5;">
            <div class="metric-box"><div class="metric-value" style="color:#9aa0a6;">—</div><div class="metric-label">Distance</div></div>
            <div class="metric-box"><div class="metric-value" style="color:#9aa0a6;">—</div><div class="metric-label">Duration</div></div>
            <div class="metric-box"><div class="metric-value" style="color:#9aa0a6;">—</div><div class="metric-label">Traffic</div></div>
        </div>"""

    distance = data.get("distance_meters", 0) / 1000
    duration = data.get("duration_seconds", 0) / 60
    traffic = (data.get("traffic_delay_seconds") or 0) / 60
    alt_count = data.get("total_alternatives", 1)
    traffic_color = "#ea4335" if traffic > 10 else "#fbbc04" if traffic > 5 else "#34a853"

    badge = f'<div class="route-badge">{alt_count} routes</div>' if alt_count > 1 else ""
    extra = f'<div class="route-badge" style="background:#e8f5e9;color:#1e8e3e;">{extra_label}</div>' if extra_label else ""

    return f"""
    <div id="results-card">
        <div class="metric-box"><div class="metric-value">{distance:.1f}<span> km</span></div><div class="metric-label">Distance</div></div>
        <div style="width:1px;height:40px;background:#e8eaed;"></div>
        <div class="metric-box"><div class="metric-value">{duration:.0f}<span> min</span></div><div class="metric-label">Duration</div></div>
        <div style="width:1px;height:40px;background:#e8eaed;"></div>
        <div class="metric-box"><div class="metric-value" style="color:{traffic_color};">{'+' if traffic > 0 else ''}{traffic:.0f}<span> min</span></div><div class="metric-label">Traffic</div></div>
        {badge}{extra}
    </div>"""


def create_directions_html(steps: list) -> str:
    if not steps:
        return ""
    html = '<div id="directions-panel">'
    html += '<div class="directions-header"><span style="font-size:16px;">🧭</span> Turn-by-turn directions</div>'
    html += '<div class="directions-list">'
    for i, step in enumerate(steps, 1):
        instruction = step.get("instruction", "").replace("<b>", "<strong>").replace("</b>", "</strong>")
        distance = step.get("distance_meters", 0)
        dist_str = f"{distance / 1000:.1f} km" if distance >= 1000 else f"{distance:.0f} m"
        html += f'''
        <div class="direction-step">
            <div class="step-number">{i}</div>
            <div class="step-content">
                <div class="step-instruction">{instruction}</div>
                <div class="step-distance">{dist_str}</div>
            </div>
        </div>'''
    html += "</div></div>"
    return html


def create_sim_status(state: str = "idle", text: str = "", progress: float = 0.0) -> str:
    """Small status bar in the simulation section."""
    dot_cls = state  # idle | running | rerouting
    pct = max(0, min(100, progress * 100))
    return f"""
    <div class="sim-status-bar">
        <div class="sim-dot {dot_cls}"></div>
        <span style="flex:1;">{text}</span>
        <span style="font-size:12px;color:var(--md-on-surface-variant);">{pct:.0f}%</span>
    </div>
    <div class="sim-progress"><div class="sim-progress-fill" style="width:{pct}%;"></div></div>
    """


# ============================================================================
# Simulation — all animation runs client-side in Leaflet JS (no map flicker)
# ============================================================================

def create_simulation_map(data: dict, speed: int = 5) -> str:
    """
    Build a self-contained Leaflet HTML page that animates a truck along the
    route entirely in JavaScript.  The map is rendered ONCE — no iframe
    rebuilds, no zoom resets, no flicker.
    """
    raw_points = polyline_codec.decode(data["polyline"])
    smooth = _subsample_route(raw_points, 250)
    pts_json = json.dumps([[p[0], p[1]] for p in smooth])

    start_lat = data.get("start_lat", smooth[0][0])
    start_lng = data.get("start_lng", smooth[0][1])
    end_lat = data.get("end_lat", smooth[-1][0])
    end_lng = data.get("end_lng", smooth[-1][1])
    total_km = data.get("distance_meters", 0) / 1000
    duration_min = data.get("duration_seconds", 0) / 60
    traffic_min = (data.get("traffic_delay_seconds") or 0) / 60
    start_addr = json.dumps(data.get("resolved_start_address", "Start"))
    end_addr = json.dumps(data.get("resolved_end_address", "Destination"))

    # Reroute API endpoint (for JS-based dynamic rerouting)
    api_url = json.dumps(f"{API_BASE_URL}/routes/estimate")
    vehicle_type = json.dumps(data.get("vehicle_type", "rmc_truck"))
    priority_val = json.dumps(data.get("priority", "normal"))
    avoid_opts = json.dumps(data.get("avoid_options") or [])

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;}} html,body,#map{{width:100%;height:100%;overflow:hidden;}}
.overlay{{
  position:absolute;bottom:20px;left:20px;right:20px;z-index:1000;
  background:rgba(255,255,255,0.96);border-radius:16px;
  padding:14px 20px;
  box-shadow:0 2px 12px rgba(0,0,0,0.18);
  font-family:'Google Sans','Roboto',sans-serif;
  backdrop-filter:blur(10px);
}}
.ov-row{{display:flex;align-items:center;gap:10px;}}
.ov-dot{{width:10px;height:10px;border-radius:50%;background:#1e8e3e;
  animation:pulse 1.4s infinite;flex-shrink:0;}}
@keyframes pulse{{0%,100%{{opacity:1;}}50%{{opacity:.35;}}}}
.ov-text{{flex:1;font-size:13px;color:#1c1b1f;}}
.ov-pct{{font-size:12px;color:#49454f;min-width:36px;text-align:right;}}
.ov-bar{{height:4px;background:#e0e0e0;border-radius:2px;margin-top:8px;overflow:hidden;}}
.ov-fill{{height:100%;background:#6750a4;border-radius:2px;transition:width .35s ease;width:0%;}}
.ov-metrics{{display:flex;gap:16px;margin-top:8px;font-size:12px;color:#49454f;}}
.ov-metrics span{{color:#1c1b1f;font-weight:500;}}
.ov-reroute{{margin-top:6px;font-size:12px;color:#fbbc04;display:none;}}
.ov-done .ov-dot{{background:#6750a4;animation:none;}}
</style></head><body>
<div id="map"></div>
<div class="overlay" id="ov">
  <div class="ov-row">
    <div class="ov-dot" id="dot"></div>
    <div class="ov-text" id="txt">🚚 Starting…</div>
    <div class="ov-pct" id="pct">0%</div>
  </div>
  <div class="ov-bar"><div class="ov-fill" id="bar"></div></div>
  <div class="ov-metrics">
    <div>Dist: <span id="m-dist">{total_km:.1f} km</span></div>
    <div>ETA: <span id="m-eta">{duration_min:.0f} min</span></div>
    <div>Traffic: <span id="m-traf">{'+' if traffic_min > 0 else ''}{traffic_min:.0f} min</span></div>
  </div>
  <div class="ov-reroute" id="reroute-msg"></div>
</div>
<script>
(function(){{
  /* ── DATA ────────────────────────────────────────── */
  const pts      = {pts_json};
  const speed    = {speed};
  const totalKm  = {total_km};
  const endAddr  = {end_addr};
  const apiUrl   = {api_url};
  const vType    = {vehicle_type};
  const prio     = {priority_val};
  const avoidArr = {avoid_opts};

  /* ── MAP ─────────────────────────────────────────── */
  const map = L.map('map',{{zoomControl:true,attributionControl:false}});
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{
    maxZoom:19}}).addTo(map);
  map.fitBounds(pts,{{padding:[60,80]}});

  /* markers */
  L.circleMarker([{start_lat},{start_lng}],{{
    radius:10,color:'white',fillColor:'#1a73e8',fillOpacity:1,weight:3
  }}).bindPopup({start_addr}).addTo(map);
  const endIcon = L.divIcon({{
    html:'<div style="font-size:24px;">📍</div>',
    iconSize:[24,24],iconAnchor:[12,24],className:''
  }});
  L.marker([{end_lat},{end_lng}],{{icon:endIcon}}).bindPopup(endAddr).addTo(map);

  /* polylines */
  L.polyline(pts,{{weight:8,color:'#1a73e8',opacity:.12}}).addTo(map);
  const traversed = L.polyline([],{{weight:5,color:'#9aa0a6',opacity:.6,dashArray:'6'}}).addTo(map);
  const remaining = L.polyline(pts,{{weight:5,color:'#1a73e8',opacity:1}}).addTo(map);

  /* truck */
  const truckIcon = L.divIcon({{
    html:'<div style="font-size:30px;filter:drop-shadow(0 2px 4px rgba(0,0,0,.35));">🚚</div>',
    iconSize:[36,36],iconAnchor:[18,18],className:''
  }});
  const truck = L.marker(pts[0],{{icon:truckIcon,zIndexOffset:1000}}).addTo(map);

  /* ── DOM refs ────────────────────────────────────── */
  const $txt  = document.getElementById('txt');
  const $pct  = document.getElementById('pct');
  const $bar  = document.getElementById('bar');
  const $dot  = document.getElementById('dot');
  const $ov   = document.getElementById('ov');
  const $dist = document.getElementById('m-dist');
  const $rr   = document.getElementById('reroute-msg');

  /* ── ANIMATION ───────────────────────────────────── */
  let idx = 0;
  const step = Math.max(1, speed);
  const intervalMs = 120;
  let rerouteCount = 0;
  const checkEvery = Math.max(15, Math.floor(pts.length / 5));
  let paused = false;

  /* Listen for pause/resume messages from parent */
  window.addEventListener('message', function(e) {{
    if (e.data === 'pause')  {{ paused = true;  $dot.style.animation='none'; $dot.style.background='#fbbc04'; $txt.textContent='⏸ Paused'; }}
    if (e.data === 'resume') {{ paused = false; $dot.style.animation='pulse 1.4s infinite'; $dot.style.background='#1e8e3e'; }}
    if (e.data === 'stop')   {{ paused = false; clearInterval(timer); }}
  }});

  function finish(){{
    truck.setLatLng(pts[pts.length-1]);
    traversed.setLatLngs(pts);
    remaining.setLatLngs([]);
    $txt.textContent = '🏁 Delivered to ' + endAddr.replace(/"/g,'');
    $pct.textContent = '100%';
    $bar.style.width  = '100%';
    $dot.style.background = '#6750a4';
    $dot.style.animation  = 'none';
    $ov.classList.add('ov-done');
  }}

  /* dynamic reroute check (non-blocking) */
  let rerouting = false;
  async function checkTraffic(curPt){{
    if(rerouting) return;
    rerouting = true;
    $rr.style.display = 'block';
    $rr.textContent = '🔄 Checking traffic…';
    $rr.style.color = '#fbbc04';
    try{{
      const resp = await fetch(apiUrl, {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{
          start:{{address: curPt[0]+','+curPt[1]}},
          end:{{address: endAddr.replace(/"/g,'')}},
          vehicle_type: vType,
          priority: prio,
          request_alternatives: false,
          avoid: avoidArr.length ? avoidArr : null,
          route_index: 0,
        }})
      }});
      if(resp.ok){{
        const d = await resp.json();
        const newTraffic = (d.traffic_delay_seconds||0)/60;
        const newDist    = (d.distance_meters||0)/1000;
        if(Math.abs(newTraffic - {traffic_min}) > 2){{
          rerouteCount++;
          $rr.textContent = '⚠️ Route updated — traffic changed (×'+rerouteCount+')';
          $rr.style.color = '#ea4335';
          $dist.textContent = newDist.toFixed(1)+' km';
        }} else {{
          $rr.textContent = '✅ Traffic OK';
          $rr.style.color = '#1e8e3e';
        }}
      }}
    }} catch(e) {{
      $rr.textContent = '⚠️ Traffic check failed';
    }}
    rerouting = false;
    setTimeout(()=>{{ $rr.style.display='none'; }}, 3000);
  }}

  const timer = setInterval(()=>{{
    if(paused) return;
    idx = Math.min(idx + step, pts.length - 1);
    const p = pts[idx];

    truck.setLatLng(p);
    traversed.setLatLngs(pts.slice(0, idx+1));
    remaining.setLatLngs(pts.slice(idx));

    const progress = idx / (pts.length - 1);
    const remKm = (totalKm * (1 - progress)).toFixed(1);

    $txt.textContent = '🚚 En route — ' + remKm + ' km remaining';
    $pct.textContent = Math.round(progress*100) + '%';
    $bar.style.width  = Math.round(progress*100) + '%';
    $dist.textContent = remKm + ' km left';

    /* periodic reroute check */
    if(idx > 0 && idx % checkEvery === 0 && idx < pts.length - step){{
      checkTraffic(p);
    }}

    if(idx >= pts.length - 1){{
      clearInterval(timer);
      finish();
    }}
  }}, intervalMs);
}})();
</script></body></html>"""


async def toggle_simulation(
    start_address, end_address, vehicle_type, vehicle_id,
    load_weight, load_volume, departure_datetime, delivery_time,
    priority, request_alternatives, avoid_tolls, avoid_highways,
    avoid_ferries, selected_route_idx, sim_speed,
):
    """
    Single toggle button: ▶ Simulate → ⏸ Pause → ▶ Resume → …
    Map is rendered ONCE; pause/resume is done via postMessage to the
    Leaflet iframe.  No flicker.
    """
    global _last_route_data, _sim_running, _sim_paused

    # ── PAUSE (currently running) ────────────────────────────────────
    if _sim_running and not _sim_paused:
        _sim_paused = True
        # Tell JS to pause
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            create_sim_status("rerouting", "⏸ Paused"),
            gr.update(value="▶ Resume"),
            gr.update(visible=True),
        )

    # ── RESUME (currently paused) ────────────────────────────────────
    if _sim_running and _sim_paused:
        _sim_paused = False
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            create_sim_status("running", "🚚 Resumed"),
            gr.update(value="⏸ Pause"),
            gr.update(visible=True),
        )

    # ── START (not running) ──────────────────────────────────────────
    data = _last_route_data
    if data is None or not data.get("polyline"):
        return (
            '<div id="status-toast" class="error">Search a route first, then simulate</div>',
            gr.update(),
            gr.update(),
            gr.update(),
            create_sim_status("idle", "No route — search first"),
            gr.update(value="▶ Simulate"),
            gr.update(visible=False),
        )

    _sim_running = True
    _sim_paused = False
    _sim_cancel.clear()

    speed_val = max(1, int(sim_speed) if sim_speed else 5)
    sim_map = create_simulation_map(data, speed_val)

    return (
        '<div id="status-toast" class="hidden"></div>',
        sim_map,
        create_metrics_html(data, extra_label="Simulating"),
        create_directions_html(data.get("route_steps", [])),
        create_sim_status("running", "🚚 Simulation started — watch the map"),
        gr.update(value="⏸ Pause"),
        gr.update(visible=True),
    )


def stop_simulation():
    """Full stop — reset to static route map."""
    global _sim_running, _sim_paused
    _sim_cancel.set()
    _sim_running = False
    _sim_paused = False
    data = _last_route_data
    static_map = create_route_map(data) if data and data.get("polyline") else gr.update()
    return (
        create_sim_status("idle", "⏹ Stopped"),
        static_map,
        gr.update(value="▶ Simulate"),
        gr.update(visible=False),
    )


# ============================================================================
# HEAD HTML — fonts + autocomplete
# ============================================================================
HEAD_HTML = """
<link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;600&family=Roboto:wght@400;500&display=swap" rel="stylesheet">
<style>
    .address-suggestions {
        position: absolute; top: 100%; left: 0; right: 0;
        background: white; border-radius: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2), 0 8px 24px rgba(0,0,0,0.15);
        z-index: 100001; max-height: 300px; overflow-y: auto; display: none;
    }
    .address-suggestions.visible { display: block; }
    .address-suggestion {
        padding: 12px 16px; font-size: 14px; cursor: pointer;
        border-bottom: 1px solid #f1f3f4;
        display: flex; align-items: flex-start; gap: 12px;
    }
    .address-suggestion:hover { background: #f8f9fa; }
    .address-suggestion:last-child { border-bottom: none; }
    .suggestion-icon {
        width: 20px; height: 20px; background: #e8eaed; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 10px; flex-shrink: 0; margin-top: 2px;
    }
    .suggestion-text { flex: 1; line-height: 1.4; }
    .suggestion-main { color: #202124; font-weight: 500; }
    .suggestion-secondary { color: #5f6368; font-size: 12px; margin-top: 2px; }
    .search-input-wrapper { position: relative; }
</style>
<script>
    let debounceTimer = null;
    let dropdownEl = null;
    let activeInput = null;

    function queryAllDeep(selector) {
        const out = [];
        const walker = [document];
        while (walker.length) {
            const node = walker.pop();
            if (node.nodeType === 1 || node.nodeType === 9 || node.nodeType === 11) {
                if (node.querySelectorAll) node.querySelectorAll(selector).forEach(el => out.push(el));
                if (node.shadowRoot) walker.push(node.shadowRoot);
                node.childNodes.forEach(child => walker.push(child));
            }
        }
        return out;
    }

    function findAddressInputs() {
        const startWrapper = document.getElementById('start-address');
        const endWrapper = document.getElementById('end-address');
        const startElDirect = startWrapper ? startWrapper.querySelector('input, textarea') : null;
        const endElDirect = endWrapper ? endWrapper.querySelector('input, textarea') : null;
        if (startElDirect && endElDirect) return { startEl: startElDirect, endEl: endElDirect };
        let startEl = null, endEl = null;
        queryAllDeep('input, textarea').forEach(input => {
            const ph = (input.getAttribute('placeholder') || '').toLowerCase();
            if (!startEl && ph.includes('pickup')) startEl = input;
            if (!endEl && ph.includes('delivery')) endEl = input;
        });
        return { startEl, endEl };
    }

    function ensureDropdown() {
        if (dropdownEl) return dropdownEl;
        dropdownEl = document.createElement('div');
        Object.assign(dropdownEl.style, {
            position:'absolute',top:'0',left:'0',width:'0',
            background:'white',borderRadius:'8px',
            boxShadow:'0 2px 6px rgba(0,0,0,0.2), 0 8px 24px rgba(0,0,0,0.15)',
            zIndex:'100001',maxHeight:'300px',overflowY:'auto',display:'none',padding:'0',
        });
        dropdownEl.className = 'address-suggestions';
        document.body.appendChild(dropdownEl);
        dropdownEl.addEventListener('mousedown', e => e.preventDefault());
        dropdownEl.addEventListener('click', e => {
            const s = e.target.closest('.address-suggestion');
            if (s && activeInput) {
                activeInput.value = s.dataset.address;
                activeInput.dispatchEvent(new Event('input',{bubbles:true}));
                activeInput.dispatchEvent(new Event('change',{bubbles:true}));
                hideDropdown();
            }
        });
        window.addEventListener('scroll', hideDropdown, true);
        window.addEventListener('resize', hideDropdown, true);
        return dropdownEl;
    }

    function positionDropdownForInput(input) {
        const el = ensureDropdown();
        const rect = input.getBoundingClientRect();
        el.style.position = 'absolute';
        el.style.top = `${rect.bottom+window.scrollY}px`;
        el.style.left = `${rect.left+window.scrollX}px`;
        el.style.width = `${rect.width}px`;
    }
    function hideDropdown() { if (!dropdownEl) return; dropdownEl.style.display='none'; dropdownEl.classList.remove('visible'); activeInput=null; }
    function showDropdown() { const el=ensureDropdown(); el.style.display='block'; el.classList.add('visible'); }

    async function searchAddress(query, suggestionsEl, inputEl) {
        if (!query || query.length < 3) { suggestionsEl.style.display='none'; return; }
        try {
            const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&countrycodes=nz&limit=5&addressdetails=1`;
            const response = await fetch(url);
            const results = await response.json();
            if (!results.length) { suggestionsEl.style.display='none'; return; }
            suggestionsEl.innerHTML = results.map(p => {
                const main = p.display_name.split(',')[0];
                const sec = p.display_name.split(',').slice(1,3).join(',').trim();
                return `<div class="address-suggestion" data-address="${p.display_name.replace(/"/g,'&quot;')}">
                    <div class="suggestion-icon">📍</div>
                    <div class="suggestion-text"><div class="suggestion-main">${main}</div><div class="suggestion-secondary">${sec}</div></div>
                </div>`;
            }).join('');
            activeInput = inputEl;
            positionDropdownForInput(inputEl);
            showDropdown();
        } catch(e) { hideDropdown(); }
    }

    function attachAutocomplete(input) {
        if (!input || input.dataset.autocompleteAttached) return;
        ensureDropdown();
        input.addEventListener('input', e => { clearTimeout(debounceTimer); debounceTimer = setTimeout(() => { positionDropdownForInput(input); searchAddress(e.target.value, dropdownEl, input); }, 300); });
        input.addEventListener('blur', () => setTimeout(hideDropdown, 150));
        input.addEventListener('focus', () => { if (input.value.length >= 3) { positionDropdownForInput(input); searchAddress(input.value, dropdownEl, input); } });
        input.dataset.autocompleteAttached = 'true';
    }

    function initAutocomplete() {
        const {startEl, endEl} = findAddressInputs();
        if (!startEl || !endEl) { setTimeout(initAutocomplete, 1000); return; }
        attachAutocomplete(startEl);
        attachAutocomplete(endEl);
    }

    const observer = new MutationObserver(() => {
        const {startEl, endEl} = findAddressInputs();
        if (startEl) attachAutocomplete(startEl);
        if (endEl) attachAutocomplete(endEl);
    });
    observer.observe(document.documentElement, {childList:true, subtree:true});

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(initAutocomplete, 1500));
    } else {
        setTimeout(initAutocomplete, 1500);
    }
</script>
"""


# ============================================================================
# Build UI
# ============================================================================
with gr.Blocks(title="RMC Route Optimizer — Simulation") as app:
    with gr.Column(elem_id="app-shell"):

        # ── TOP APP BAR ────────────────────────────────────
        with gr.Column(elem_id="top-bar"):
            gr.HTML("""
            <div class="md-top-app-bar">
                <div class="bar-icon">🚚</div>
                <div>
                    <div class="bar-title">RMC Route Optimizer</div>
                    <div class="bar-subtitle">New Zealand · Simulation Mode</div>
                </div>
            </div>
            """)

        # ── BODY ───────────────────────────────────────────
        with gr.Row(elem_id="app-body"):

            # ── SIDEBAR ──────────────────────────────────
            with gr.Column(elem_id="sidebar", scale=0):

                # Address bar
                with gr.Column(elem_id="address-bar"):
                    start_address = gr.Textbox(
                        label="From", placeholder="Enter pickup address",
                        elem_id="start-address", elem_classes=["md-textbox"], lines=1,
                    )
                    end_address = gr.Textbox(
                        label="To", placeholder="Enter delivery address",
                        elem_id="end-address", elem_classes=["md-textbox"], lines=1,
                    )
                    calculate_btn = gr.Button("Search Route", elem_id="search-btn")

                # Status
                status_output = gr.HTML(value='<div id="status-toast" class="hidden"></div>')

                # Metrics
                with gr.Column(elem_id="metrics-section"):
                    metrics_output = gr.HTML(value=create_metrics_html(None))

                # ── SIMULATION PANEL ─────────────────────
                gr.HTML('<div class="section-label">Simulation</div>')
                with gr.Column(elem_id="sim-section"):
                    sim_status_output = gr.HTML(value=create_sim_status("idle", "Search a route first"))
                    with gr.Row():
                        sim_speed = gr.Dropdown(
                            label="Speed",
                            choices=[("1× (slow)", "1"), ("3×", "3"), ("5× (normal)", "5"),
                                     ("10× (fast)", "10"), ("20× (turbo)", "20")],
                            value="5", elem_classes=["md-dropdown"], scale=2,
                        )
                        sim_toggle_btn = gr.Button("▶ Simulate", elem_id="sim-toggle", scale=1)
                        stop_btn = gr.Button("⏹", elem_id="stop-btn", scale=0, visible=False)

                # Vehicle & Priority
                gr.HTML('<div class="section-label">Vehicle & Priority</div>')
                with gr.Column(elem_id="quick-settings"):
                    with gr.Row():
                        vehicle_type = gr.Dropdown(
                            label="Vehicle Type",
                            choices=[("RMC Truck", "rmc_truck"), ("Concrete Mixer", "concrete_mixer"),
                                     ("Pump Truck", "pump_truck"), ("Delivery Truck", "delivery_truck")],
                            value="rmc_truck", scale=3, elem_classes=["md-dropdown"],
                        )
                        priority = gr.Dropdown(
                            label="Priority",
                            choices=["low", "normal", "high", "urgent"],
                            value="normal", scale=2, elem_classes=["md-dropdown"],
                        )
                vehicle_id = gr.State(value="")
                load_weight = gr.State(value=0)
                load_volume = gr.State(value=0)

                # Route preferences
                gr.HTML('<div class="section-label">Route Preferences</div>')
                with gr.Column(elem_id="route-prefs"):
                    with gr.Row():
                        request_alternatives = gr.Checkbox(label="Alt routes", value=True, elem_classes=["md-chip"])
                        avoid_tolls = gr.Checkbox(label="No tolls", value=False, elem_classes=["md-chip"])
                    with gr.Row():
                        avoid_highways = gr.Checkbox(label="No highways", value=False, elem_classes=["md-chip"])
                        avoid_ferries = gr.Checkbox(label="No ferries", value=False, elem_classes=["md-chip"])
                    selected_route_idx = gr.Dropdown(
                        label="Route Variant",
                        choices=[("Search a route first", "0")],
                        value="0",
                        interactive=True,
                        elem_classes=["md-dropdown"],
                    )

                # Schedule
                with gr.Column(elem_id="trip-details"):
                    with gr.Accordion("⏰  Schedule", open=False):
                        with gr.Column(elem_id="trip-details-inner"):
                            departure_datetime = gr.DateTime(
                                label="Departure Time", include_time=True,
                                type="datetime", elem_classes=["md-datetime"],
                            )
                            delivery_time = gr.Dropdown(
                                label="Max Delivery Window",
                                choices=["No Limit", "45 minutes", "60 minutes", "90 minutes"],
                                value="No Limit", elem_classes=["md-dropdown"],
                            )

                # Directions
                with gr.Column(elem_id="directions-section"):
                    directions_output = gr.HTML(value="")

            # ── MAP ──────────────────────────────────────
            with gr.Column(elem_id="map-area", scale=1):
                map_output = gr.HTML(value=create_empty_map(), elem_id="map-container")

    # ── Event bindings ───────────────────────────────────────────────────────
    route_inputs = [
        start_address, end_address, vehicle_type, vehicle_id,
        load_weight, load_volume, departure_datetime, delivery_time,
        priority, request_alternatives, avoid_tolls, avoid_highways,
        avoid_ferries, selected_route_idx,
    ]
    route_outputs = [status_output, map_output, metrics_output, directions_output, sim_status_output, selected_route_idx]

    calculate_btn.click(fn=estimate_route, inputs=route_inputs, outputs=route_outputs)
    selected_route_idx.change(fn=estimate_route, inputs=route_inputs, outputs=route_outputs)

    sim_inputs = route_inputs + [sim_speed]

    # Pause/resume JS sent to iframe via postMessage
    _PAUSE_RESUME_JS = """
    () => {
        const iframe = document.querySelector('#map-container iframe');
        if (!iframe || !iframe.contentWindow) return;
        const btn = document.querySelector('#sim-toggle');
        const label = btn ? btn.textContent.trim() : '';
        if (label.includes('Pause')) {
            iframe.contentWindow.postMessage('pause','*');
        } else if (label.includes('Resume')) {
            iframe.contentWindow.postMessage('resume','*');
        }
    }
    """
    _STOP_JS = """
    () => {
        const iframe = document.querySelector('#map-container iframe');
        if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage('stop','*');
    }
    """

    sim_toggle_btn.click(
        fn=toggle_simulation,
        inputs=sim_inputs,
        outputs=[status_output, map_output, metrics_output, directions_output, sim_status_output, sim_toggle_btn, stop_btn],
    ).then(fn=None, js=_PAUSE_RESUME_JS)

    stop_btn.click(
        fn=stop_simulation,
        inputs=[],
        outputs=[sim_status_output, map_output, sim_toggle_btn, stop_btn],
    ).then(fn=None, js=_STOP_JS)


if __name__ == "__main__":
    app.launch(
        server_port=7860,
        show_error=True,
        theme=MD3_THEME,
        css=CUSTOM_CSS,
        head=HEAD_HTML,
    )
