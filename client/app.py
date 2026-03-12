"""RMC Delivery Route Optimizer - Material Design 3 UI (Gradio 6)
Design Principles:
- Full-width MD3 top app bar spanning the viewport
- Material Design 3 color system, typography & elevation
- Gradio 6 theme API + elem_classes for reliable styling
- Fixed sidebar with flat, scannable controls
- Full-screen map as primary focus
"""
import gradio as gr
import httpx
import folium
import polyline
import json
from datetime import datetime
from folium import plugins
from typing import Any, Optional, cast

# API Configuration
API_BASE_URL = "http://localhost:8000/api/v1"


# ============================================================================
# Gradio 6 Theme — MD3 colors via the theme API (no fragile CSS selectors)
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
    # Surface / body — pure white for clean look
    body_background_fill="white",
    body_text_color="#1c1b1f",
    body_text_color_subdued="#49454f",
    background_fill_primary="white",
    background_fill_secondary="white",
    # Blocks (remove default cards/borders)
    block_background_fill="transparent",
    block_border_width="0px",
    block_shadow="none",
    block_label_text_color="#49454f",
    block_label_text_size="*text_sm",
    block_label_text_weight="500",
    block_title_text_color="#49454f",
    block_title_text_size="*text_sm",
    block_title_text_weight="500",
    # Inputs — MD3 outlined style (white, not gray)
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
    # Borders
    border_color_primary="#cac4d0",
    border_color_accent="#6750a4",
    # Primary button
    button_primary_background_fill="#6750a4",
    button_primary_background_fill_hover="#7965af",
    button_primary_border_color="#6750a4",
    button_primary_border_color_hover="#7965af",
    button_primary_text_color="white",
    button_primary_text_color_hover="white",
    button_primary_shadow="0 1px 2px rgba(0,0,0,0.3), 0 1px 3px 1px rgba(0,0,0,0.15)",
    button_primary_shadow_hover="0 1px 2px rgba(0,0,0,0.3), 0 2px 6px 2px rgba(0,0,0,0.15)",
    button_primary_shadow_active="none",
    # Secondary button
    button_secondary_background_fill="transparent",
    button_secondary_border_color="#79747e",
    button_secondary_text_color="#6750a4",
    # Checkbox / radio
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
    # Slider
    slider_color="#6750a4",
    # Accordion
    accordion_text_color="#1c1b1f",
    # Color accent
    color_accent="#6750a4",
)


# ============================================================================
# CSS — layout + overrides (NO .gradio-textbox / .gradio-dropdown selectors!)
# Uses elem_id containers + elem_classes added to individual components.
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

/* ── OUTER WRAPPER (column: header + body) ────────── */
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

/* ── TOP APP BAR (Material Design 3) ───────────────── */
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
    font-size: 22px;
    font-weight: 400;
    letter-spacing: 0;
    flex: 1;
}
.md-top-app-bar .bar-subtitle {
    font-size: 12px;
    opacity: 0.85;
    font-weight: 400;
    letter-spacing: 0.15px;
}

/* ── BODY ROW (sidebar + map) ─────────────────────── */
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

/* ── LEFT SIDEBAR ───────────────────────────────────── */
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

/* ── RIGHT MAP ──────────────────────────────────────── */
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

/* ============================================================
   FORM CONTROLS — targeted via elem_classes (Gradio 6 safe)
   ============================================================ */

/* ── MD3 Outlined Text Fields ───────────────────────── */
.md-textbox,
.md-textbox > div {
    background: white !important;
    border: none !important;
    box-shadow: none !important;
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
    transition: border-color 0.2s cubic-bezier(0.2,0,0,1) !important;
    caret-color: var(--md-primary) !important;
}
.md-textbox input:hover,
.md-textbox textarea:hover {
    border-color: var(--md-on-surface) !important;
}
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
    font-size: 12px !important;
    font-weight: 500 !important;
    letter-spacing: 0.4px !important;
}

/* ── MD3 Outlined Dropdowns ─────────────────────────── */
/* Reset ALL backgrounds inside dropdown wrapper to white */
.md-dropdown,
.md-dropdown > div,
.md-dropdown div[data-testid] {
    background: white !important;
    border: none !important;
    box-shadow: none !important;
}
/* The actual input field inside dropdown */
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
/* Label */
.md-dropdown label span,
.md-dropdown > label {
    color: var(--md-on-surface-variant) !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    letter-spacing: 0.4px !important;
}
/* Kill extra nested wrapper borders/padding that Gradio 6 adds */
.md-dropdown .wrap-inner,
.md-dropdown .secondary-wrap {
    border: none !important;
    padding: 0 !important;
    min-height: unset !important;
    background: transparent !important;
}
/* Dropdown options list */
.md-dropdown ul { background: white !important; border-radius: var(--md-radius-sm) !important; }
.md-dropdown ul li { font-size: 14px !important; padding: 10px 14px !important; }
.md-dropdown ul li:hover { background: rgba(103,80,164,0.08) !important; }

/* ── MD3 Filled Button (primary) ────────────────────── */
#search-btn {
    margin: 4px 0 0 !important;
    border: none !important;
    border-radius: var(--md-radius-full) !important;
    min-height: 48px !important;
    background: var(--md-primary) !important;
    color: var(--md-on-primary) !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    font-family: inherit !important;
    letter-spacing: 0.1px;
    cursor: pointer;
    transition: box-shadow 0.2s cubic-bezier(0.2,0,0,1), background 0.2s !important;
}
#search-btn:hover {
    background: #7965af !important;
}
#search-btn:active {
    box-shadow: none !important;
}

/* ── MD3 Filter Chips (checkboxes) ──────────────────── */
.md-chip {
    background: white !important;
    border: 1px solid var(--md-outline) !important;
    border-radius: 20px !important;
    padding: 6px 14px !important;
    margin: 0 !important;
    min-height: auto !important;
    transition: all 0.2s cubic-bezier(0.2,0,0,1) !important;
    cursor: pointer;
    box-shadow: none !important;
}
.md-chip > div {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
.md-chip:hover {
    background: rgba(103,80,164,0.08) !important;
}
.md-chip label {
    font-size: 13px !important;
    font-weight: 500 !important;
    color: var(--md-on-surface) !important;
    gap: 6px !important;
    cursor: pointer !important;
    letter-spacing: 0.1px !important;
    white-space: nowrap !important;
}
.md-chip input[type='checkbox'] {
    accent-color: var(--md-primary) !important;
    width: 16px !important;
    height: 16px !important;
}

/* ── Route variant dropdown ─────────────────────────── */
#route-prefs .md-dropdown {
    margin-top: 4px !important;
}

/* ── MD3 Accordion (target by elem_id) ─────────────── */
#trip-details .accordion {
    border: none !important;
    border-radius: 0 !important;
    margin: 0 !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
    background: transparent !important;
}
/* Accordion toggle button / summary */
#trip-details button,
#trip-details summary,
#trip-details .label-wrap,
#trip-details [role="button"] {
    padding: 16px 20px !important;
    background: white !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    color: var(--md-on-surface) !important;
    letter-spacing: 0.1px !important;
    border: none !important;
}
/* Accordion content */
#trip-details .content,
#trip-details .wrap,
#trip-details [role="region"] {
    padding: 4px 20px 16px !important;
    background: white !important;
}

/* ============================================================
   SIDEBAR SECTIONS
   ============================================================ */

/* ── ADDRESS BAR ────────────────────────────────────── */
#address-bar {
    padding: 20px 20px 16px !important;
    gap: 12px !important;
    background: white !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
}

/* ── STATUS TOAST ───────────────────────────────────── */
#status-toast {
    margin: 0; border-radius: 0;
    padding: 12px 20px; font-size: 14px;
    letter-spacing: 0.25px;
    color: #fff; background: #323232;
}
#status-toast.error { background: var(--md-error); }
#status-toast.success { background: var(--md-success); }
#status-toast.hidden { display: none; }

/* ── METRICS STRIP ──────────────────────────────────── */
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

/* ── SECTION LABELS (MD3 title-small) ───────────────── */
.section-label {
    padding: 16px 20px 8px;
    font-size: 11px;
    font-weight: 500;
    color: var(--md-on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background: white;
}

/* ── QUICK SETTINGS ─────────────────────────────────── */
#quick-settings {
    padding: 0 20px 16px !important;
    gap: 12px !important;
    background: white !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
}
#quick-settings > div { gap: 12px !important; }

/* ── ROUTE PREFS ────────────────────────────────────── */
#route-prefs {
    padding: 8px 20px 16px !important;
    gap: 14px !important;
    background: white !important;
    border-bottom: 1px solid var(--md-outline-variant) !important;
}
#route-prefs > div {
    gap: 8px !important;
    flex-wrap: wrap !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* ── TRIP DETAILS ───────────────────────────────────── */
#trip-details { padding: 0 !important; gap: 0 !important; }
#trip-details-inner { padding: 4px 20px 16px !important; gap: 14px !important; }
#trip-details-inner > div { gap: 12px !important; }

/* ── DIRECTIONS ─────────────────────────────────────── */
#directions-section { padding: 0 !important; gap: 0 !important; }

#directions-panel {
    border: none !important; border-radius: 0 !important;
    box-shadow: none !important; overflow: hidden;
    background: white;
}
.directions-header {
    padding: 16px 20px; font-size: 14px; font-weight: 500;
    color: var(--md-on-surface); border-bottom: 1px solid var(--md-outline-variant);
    background: white;
    display: flex; align-items: center; gap: 10px;
    letter-spacing: 0.1px;
}
.directions-list { max-height: none; overflow-y: visible; }
.direction-step {
    display: flex; gap: 14px;
    padding: 12px 20px;
    border-bottom: 1px solid var(--md-outline-variant);
    transition: background 0.15s cubic-bezier(0.2,0,0,1);
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

/* ── Datepicker / DateTime ──────────────────────────── */
.md-datetime,
.md-datetime > div {
    background: white !important;
    border: none !important;
    box-shadow: none !important;
}
.md-datetime input {
    border: 1px solid var(--md-outline) !important;
    border-radius: var(--md-radius-sm) !important;
    background: white !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 8px 14px !important;
    font-size: 14px !important;
}
.flatpickr-calendar { z-index: 200000 !important; }

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
    no_route_dropdown = gr.update(choices=[("Fastest", "0")], value="0")

    if not start_address or not end_address:
        return (
            '<div id="status-toast" class="error">Enter both pickup and destination</div>',
            create_empty_map(),
            create_metrics_html(None),
            "",
            no_route_dropdown,
        )
    
    try:
        departure_time_str = None
        if departure_datetime:
            if hasattr(departure_datetime, 'isoformat'):
                departure_time_str = departure_datetime.isoformat()
            else:
                departure_time_str = str(departure_datetime)
        
        max_delivery_minutes = None
        if delivery_time and delivery_time != "No Limit":
            max_delivery_minutes = int(delivery_time.split()[0])
        
        avoid = []
        if avoid_tolls: avoid.append("tolls")
        if avoid_highways: avoid.append("highways")
        if avoid_ferries: avoid.append("ferries")
        
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
            response = await client.post(
                f"{API_BASE_URL}/routes/estimate",
                json=payload
            )
            
            if response.status_code == 200:
                data = response.json()
                route_dropdown = _build_route_choices(data)
                return (
                    '<div id="status-toast" class="hidden"></div>',
                    create_route_map(data),
                    create_metrics_html(data),
                    create_directions_html(data.get("route_steps", [])),
                    route_dropdown,
                )
            else:
                error = response.json().get("detail", "Unknown error")
                return (
                    f'<div id="status-toast" class="error">{error}</div>',
                    create_empty_map(),
                    create_metrics_html(None),
                    "",
                    no_route_dropdown,
                )
                
    except Exception as e:
        return (
            '<div id="status-toast" class="error">Connection error</div>',
            create_empty_map(),
            create_metrics_html(None),
            "",
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


def create_empty_map() -> str:
    """Create empty map centered on New Zealand"""
    m = folium.Map(
        location=[-41.2865, 174.7762],
        zoom_start=6,
        tiles='cartodbpositron'
    )
    plugins.Fullscreen(position='topright').add_to(m)
    return m._repr_html_()


def create_metrics_html(data: Optional[dict[str, Any]] = None) -> str:
    """Create floating results card HTML"""
    if not data:
        return """
        <div id="results-card" style="opacity: 0.5;">
            <div class="metric-box">
                <div class="metric-value" style="color: #9aa0a6;">—</div>
                <div class="metric-label">Distance</div>
            </div>
            <div class="metric-box">
                <div class="metric-value" style="color: #9aa0a6;">—</div>
                <div class="metric-label">Duration</div>
            </div>
            <div class="metric-box">
                <div class="metric-value" style="color: #9aa0a6;">—</div>
                <div class="metric-label">Traffic</div>
            </div>
        </div>
        """
    
    distance = data.get("distance_meters", 0) / 1000
    duration = data.get("duration_seconds", 0) / 60
    traffic = (data.get("traffic_delay_seconds") or 0) / 60
    alt_count = data.get("total_alternatives", 1)
    
    traffic_color = "#ea4335" if traffic > 10 else "#fbbc04" if traffic > 5 else "#34a853"
    
    return f"""
    <div id="results-card">
        <div class="metric-box">
            <div class="metric-value">{distance:.1f}<span> km</span></div>
            <div class="metric-label">Distance</div>
        </div>
        <div style="width: 1px; height: 40px; background: #e8eaed;"></div>
        <div class="metric-box">
            <div class="metric-value">{duration:.0f}<span> min</span></div>
            <div class="metric-label">Duration</div>
        </div>
        <div style="width: 1px; height: 40px; background: #e8eaed;"></div>
        <div class="metric-box">
            <div class="metric-value" style="color: {traffic_color};">{'+' if traffic > 0 else ''}{traffic:.0f}<span> min</span></div>
            <div class="metric-label">Traffic</div>
        </div>
        {f'<div class="route-badge">{alt_count} routes</div>' if alt_count > 1 else ''}
    </div>
    """


def create_route_map(data: dict) -> str:
    """Create route map with Google Maps styling"""
    start_lat = data.get("start_lat")
    start_lng = data.get("start_lng")
    end_lat = data.get("end_lat")
    end_lng = data.get("end_lng")
    
    if not all([start_lat, start_lng, end_lat, end_lng]):
        return create_empty_map()

    start_lat_f = cast(float, start_lat)
    start_lng_f = cast(float, start_lng)
    end_lat_f = cast(float, end_lat)
    end_lng_f = cast(float, end_lng)
    
    center_lat = (start_lat_f + end_lat_f) / 2
    center_lng = (start_lng_f + end_lng_f) / 2
    
    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=12,
        tiles='cartodbpositron'
    )
    
    plugins.Fullscreen(position='topright').add_to(m)
    
    # Start marker (blue circle)
    folium.CircleMarker(
        [start_lat, start_lng],
        radius=10,
        color='white',
        fill=True,
        fillColor='#1a73e8',
        fillOpacity=1,
        weight=3,
        popup=data.get('resolved_start_address', 'Start'),
    ).add_to(m)
    
    # End marker (red)
    folium.Marker(
        [end_lat, end_lng],
        popup=data.get('resolved_end_address', 'Destination'),
        icon=folium.Icon(color="red", icon="flag", prefix="fa"),
    ).add_to(m)
    
    # Route polyline
    if data.get("polyline"):
        try:
            points = polyline.decode(data["polyline"])
            
            # Route shadow
            folium.PolyLine(
                points,
                weight=10,
                color="#1a73e8",
                opacity=0.3
            ).add_to(m)
            
            # Main route
            folium.PolyLine(
                points,
                weight=5,
                color="#1a73e8",
                opacity=1
            ).add_to(m)
            
            m.fit_bounds(points, padding=[60, 60])
        except:
            pass
    
    return m._repr_html_()


def create_directions_html(steps: list) -> str:
    """Create directions panel HTML"""
    if not steps:
        return ""
    
    html = '<div id="directions-panel">'
    html += '<div class="directions-header"><span style="font-size:16px;">🧭</span> Turn-by-turn directions</div>'
    html += '<div class="directions-list">'
    
    for i, step in enumerate(steps, 1):
        instruction = step.get("instruction", "").replace("<b>", "<strong>").replace("</b>", "</strong>")
        distance = step.get("distance_meters", 0)
        dist_str = f"{distance/1000:.1f} km" if distance >= 1000 else f"{distance:.0f} m"
        
        html += f'''
        <div class="direction-step">
            <div class="step-number">{i}</div>
            <div class="step-content">
                <div class="step-instruction">{instruction}</div>
                <div class="step-distance">{dist_str}</div>
            </div>
        </div>
        '''
    
    html += '</div></div>'
    return html


# ============================================================================
# HEAD HTML — fonts + autocomplete (injected via launch() in Gradio 6)
# ============================================================================
HEAD_HTML = """
<link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;600&family=Roboto:wght@400;500&display=swap" rel="stylesheet">
<style>
    /* Autocomplete dropdown */
    .address-suggestions {
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        background: white;
        border-radius: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2), 0 8px 24px rgba(0,0,0,0.15);
        z-index: 100001;
        max-height: 300px;
        overflow-y: auto;
        display: none;
    }
    .address-suggestions.visible { display: block; }
    .address-suggestion {
        padding: 12px 16px;
        font-size: 14px;
        cursor: pointer;
        border-bottom: 1px solid #f1f3f4;
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }
    .address-suggestion:hover { background: #f8f9fa; }
    .address-suggestion:last-child { border-bottom: none; }
    .suggestion-icon {
        width: 20px;
        height: 20px;
        background: #e8eaed;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 10px;
        flex-shrink: 0;
        margin-top: 2px;
    }
    .suggestion-text {
        flex: 1;
        line-height: 1.4;
    }
    .suggestion-main { color: #202124; font-weight: 500; }
    .suggestion-secondary { color: #5f6368; font-size: 12px; margin-top: 2px; }
    .search-input-wrapper { position: relative; }
</style>
<script>
    // Nominatim (OpenStreetMap) Address Autocomplete
    let debounceTimer = null;
    let dropdownEl = null;
    let activeInput = null;
    console.log('🚀 Nominatim autocomplete script loaded');

    function queryAllDeep(selector) {
        const out = [];
        const walker = [document];
        while (walker.length) {
            const node = walker.pop();
            if (node.nodeType === 1 || node.nodeType === 9 || node.nodeType === 11) {
                if (node.querySelectorAll) {
                    node.querySelectorAll(selector).forEach(el => out.push(el));
                }
                if (node.shadowRoot) walker.push(node.shadowRoot);
                node.childNodes.forEach(child => walker.push(child));
            }
        }
        return out;
    }

    function findAddressInputs() {
        // Try by explicit elem_id first (works if not in shadow)
        const startWrapper = document.getElementById('start-address');
        const endWrapper = document.getElementById('end-address');
        const startElDirect = startWrapper ? startWrapper.querySelector('input, textarea') : null;
        const endElDirect = endWrapper ? endWrapper.querySelector('input, textarea') : null;
        if (startElDirect && endElDirect) return { startEl: startElDirect, endEl: endElDirect };

        // Shadow DOM deep search fallback
        let startEl = null;
        let endEl = null;
        queryAllDeep('input, textarea').forEach(input => {
            const placeholder = (input.getAttribute('placeholder') || '').toLowerCase();
            if (!startEl && placeholder.includes('starting point')) startEl = input;
            if (!endEl && placeholder.includes('destination')) endEl = input;
        });
        return { startEl, endEl };
    }

    function ensureDropdown() {
        if (dropdownEl) return dropdownEl;
        dropdownEl = document.createElement('div');
        Object.assign(dropdownEl.style, {
            position: 'absolute',
            top: '0',
            left: '0',
            width: '0',
            background: 'white',
            borderRadius: '8px',
            boxShadow: '0 2px 6px rgba(0,0,0,0.2), 0 8px 24px rgba(0,0,0,0.15)',
            zIndex: '100001',
            maxHeight: '300px',
            overflowY: 'auto',
            display: 'none',
            padding: '0',
        });
        dropdownEl.className = 'address-suggestions';
        document.body.appendChild(dropdownEl);

        // Allow clicking without losing data due to blur
        dropdownEl.addEventListener('mousedown', (e) => {
            e.preventDefault();
        });

        // Handle suggestion click globally
        dropdownEl.addEventListener('click', (e) => {
            const suggestion = e.target.closest('.address-suggestion');
            if (suggestion && activeInput) {
                const address = suggestion.dataset.address;
                activeInput.value = address;
                activeInput.dispatchEvent(new Event('input', { bubbles: true }));
                activeInput.dispatchEvent(new Event('change', { bubbles: true }));
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
        el.style.top = `${rect.bottom + window.scrollY}px`;
        el.style.left = `${rect.left + window.scrollX}px`;
        el.style.width = `${rect.width}px`;
    }

    function hideDropdown() {
        if (!dropdownEl) return;
        dropdownEl.style.display = 'none';
        dropdownEl.classList.remove('visible');
        activeInput = null;
    }

    function showDropdown() {
        const el = ensureDropdown();
        el.style.display = 'block';
        el.classList.add('visible');
    }

    async function searchAddress(query, suggestionsEl, inputEl) {
        if (!query || query.length < 3) {
            console.log('ℹ️ Query too short or empty, hiding suggestions');
            suggestionsEl.classList.remove('visible');
            if (suggestionsEl.style) suggestionsEl.style.display = 'none';
            activeInput = null;
            return;
        }
        if (!suggestionsEl) {
            console.warn('⚠️ No suggestions element to render into');
            return;
        }

        try {
            // Search NZ addresses using Nominatim
            const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&countrycodes=nz&limit=5&addressdetails=1`;

            console.log('🔍 Searching Nominatim:', query);
            console.log('📡 API URL:', url);

            const response = await fetch(url);

            console.log('📥 Response status:', response.status);

            const results = await response.json();

            console.log('📍 Results found:', results.length, results);

            if (results.length === 0) {
                console.log('⚠️ No results found for:', query);
                suggestionsEl.classList.remove('visible');
                return;
            }

            suggestionsEl.innerHTML = results.map(place => {
                const mainText = place.display_name.split(',')[0];
                const secondaryText = place.display_name.split(',').slice(1, 3).join(',').trim();
                return `
                    <div class="address-suggestion" data-address="${place.display_name.replace(/"/g, '&quot;')}">
                        <div class="suggestion-icon">📍</div>
                        <div class="suggestion-text">
                            <div class="suggestion-main">${mainText}</div>
                            <div class="suggestion-secondary">${secondaryText}</div>
                        </div>
                    </div>
                `;
            }).join('');

            suggestionsEl.classList.add('visible');
            if (suggestionsEl.style) suggestionsEl.style.display = 'block';
            if (inputEl) {
                activeInput = inputEl;
                positionDropdownForInput(inputEl);
                showDropdown();
            }
        } catch (e) {
            console.error('Nominatim search error:', e);
            suggestionsEl.classList.remove('visible');
            if (suggestionsEl.style) suggestionsEl.style.display = 'none';
            hideDropdown();
        }
    }

    function attachAutocomplete(input) {
        if (!input || input.dataset.autocompleteAttached) return;
        ensureDropdown();

        console.log('🔗 Attaching listeners to', input.placeholder || input.name || 'input');

        input.addEventListener('input', (e) => {
            console.log('⌨️ Typing detected:', e.target.value);
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                positionDropdownForInput(input);
                searchAddress(e.target.value, dropdownEl, input);
            }, 300);
        });

        input.addEventListener('blur', () => {
            setTimeout(() => hideDropdown(), 150);
        });

        input.addEventListener('focus', () => {
            if (input.value.length >= 3) {
                positionDropdownForInput(input);
                searchAddress(input.value, dropdownEl, input);
            } else {
                hideDropdown();
            }
        });

        input.dataset.autocompleteAttached = 'true';
        console.log('✅ Autocomplete wired for input with placeholder:', input.placeholder);
    }

    function initAutocomplete() {
        const { startEl, endEl } = findAddressInputs();
        console.log('🔍 Input search result:', { startEl, endEl });
        if (!startEl || !endEl) {
            console.log('⏳ Address inputs not ready, retrying...');
            setTimeout(initAutocomplete, 1000);
            return;
        }

        attachAutocomplete(startEl);
        attachAutocomplete(endEl);
        console.log('🏁 OpenStreetMap Nominatim autocomplete initialized');
    }

    // As a fallback, watch DOM mutations in case Gradio re-renders
    const observer = new MutationObserver(() => {
        const { startEl, endEl } = findAddressInputs();
        if (startEl) attachAutocomplete(startEl);
        if (endEl) attachAutocomplete(endEl);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(initAutocomplete, 1500));
    } else {
        setTimeout(initAutocomplete, 1500);
    }
</script>
"""


# ============================================================================
# Build UI  (Gradio 6: theme/css/head go in launch(), not Blocks())
# ============================================================================
with gr.Blocks(title="RMC Route Optimizer") as app:
    with gr.Column(elem_id="app-shell"):

        # ── FULL-WIDTH TOP APP BAR ─────────────────────────
        with gr.Column(elem_id="top-bar"):
            gr.HTML("""
            <div class="md-top-app-bar">
                <div class="bar-icon">🚚</div>
                <div>
                    <div class="bar-title">RMC Route Optimizer</div>
                    <div class="bar-subtitle">New Zealand · Ready-Mix Concrete</div>
                </div>
            </div>
            """)

        # ── BODY: sidebar + map ────────────────────────────
        with gr.Row(elem_id="app-body"):

            # ── LEFT SIDEBAR ──────────────────────────────
            with gr.Column(elem_id="sidebar", scale=0):

                # Address bar
                with gr.Column(elem_id="address-bar"):
                    start_address = gr.Textbox(
                        label="From",
                        placeholder="Enter pickup address",
                        elem_id="start-address",
                        elem_classes=["md-textbox"],
                        lines=1,
                    )
                    end_address = gr.Textbox(
                        label="To",
                        placeholder="Enter delivery address",
                        elem_id="end-address",
                        elem_classes=["md-textbox"],
                        lines=1,
                    )
                    calculate_btn = gr.Button("Search Route", elem_id="search-btn")

                # Status toast
                status_output = gr.HTML(value='<div id="status-toast" class="hidden"></div>')

                # Metrics strip
                with gr.Column(elem_id="metrics-section"):
                    metrics_output = gr.HTML(value=create_metrics_html(None))

                # Vehicle & Priority
                gr.HTML('<div class="section-label">Vehicle & Priority</div>')
                with gr.Column(elem_id="quick-settings"):
                    with gr.Row():
                        vehicle_type = gr.Dropdown(
                            label="Vehicle Type",
                            choices=[
                                ("RMC Truck", "rmc_truck"),
                                ("Concrete Mixer", "concrete_mixer"),
                                ("Pump Truck", "pump_truck"),
                                ("Delivery Truck", "delivery_truck"),
                            ],
                            value="rmc_truck", scale=3,
                            elem_classes=["md-dropdown"],
                        )
                        priority = gr.Dropdown(
                            label="Priority",
                            choices=["low", "normal", "high", "urgent"],
                            value="normal", scale=2,
                            elem_classes=["md-dropdown"],
                        )
                # Hidden defaults
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
                                label="Departure Time",
                                include_time=True,
                                type="datetime",
                                elem_classes=["md-datetime"],
                            )
                            delivery_time = gr.Dropdown(
                                label="Max Delivery Window",
                                choices=["No Limit", "45 minutes", "60 minutes", "90 minutes"],
                                value="No Limit",
                                elem_classes=["md-dropdown"],
                            )

                # Directions
                with gr.Column(elem_id="directions-section"):
                    directions_output = gr.HTML(value="")

            # ── RIGHT MAP ─────────────────────────────────
            with gr.Column(elem_id="map-area", scale=1):
                map_output = gr.HTML(
                    value=create_empty_map(),
                    elem_id="map-container",
                )

    # Event bindings
    inputs = [
        start_address, end_address, vehicle_type, vehicle_id,
        load_weight, load_volume, departure_datetime, delivery_time,
        priority, request_alternatives, avoid_tolls, avoid_highways,
        avoid_ferries, selected_route_idx,
    ]
    outputs = [status_output, map_output, metrics_output, directions_output, selected_route_idx]

    calculate_btn.click(fn=estimate_route, inputs=inputs, outputs=outputs)
    selected_route_idx.change(fn=estimate_route, inputs=inputs, outputs=outputs)


if __name__ == "__main__":
    app.launch(
        server_port=7860,
        show_error=True,
        theme=MD3_THEME,
        css=CUSTOM_CSS,
        head=HEAD_HTML,
    )
