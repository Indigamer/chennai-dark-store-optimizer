"""Streamlit application for Chennai dark-store location optimization."""

from collections import defaultdict
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import time

import folium
from folium.plugins import HeatMap, MarkerCluster
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from coverage_geometry import uncovered_region_geojson, uncovered_road_gap_geojson
from data_validation import (
    DEFAULT_CHENNAI_BOUNDS,
    InputValidationError,
    generate_demo_data,
    validate_customers_csv,
    validate_instance_capacity,
    validate_stores_csv,
)
from optimization_model import haversine_distance_km, solve_location_model
from routing_provider import OpenRouteServiceClient
from sensitivity_analysis import run_sensitivity_scenarios


APP_DIR = Path(__file__).resolve().parent
EXAMPLE_FILES = {
    "Optimizer run": (
        APP_DIR / "optimizer_example_customers.csv",
        APP_DIR / "optimizer_example_stores.csv",
    ),
    "Sensitivity analysis": (
        APP_DIR / "sensitivity_example_customers.csv",
        APP_DIR / "sensitivity_example_stores.csv",
    ),
}
P_PRESETS = {
    "Original benchmark (2, 5, 10, 20, 25)": (2, 5, 10, 20, 25),
    "Additional examples (3, 5, 7, 10)": (3, 5, 7, 10),
}


@st.cache_data(show_spinner=False)
def _cached_demo_data(customer_count, store_count, seed, bounds):
    return generate_demo_data(customer_count, store_count, seed=seed, bounds=bounds)


def _get_secret_key():
    try:
        return st.secrets.get("ORS_API_KEY", "") or os.getenv("ORS_API_KEY", "")
    except Exception:
        return os.getenv("ORS_API_KEY", "")


def _csv_bytes(rows, columns):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _road_matrix_cache_key(customers, stores, max_distance_km):
    coordinates = {
        "customers": [(row["latitude"], row["longitude"]) for row in customers],
        "stores": [(row["latitude"], row["longitude"]) for row in stores],
        "max_distance_km": float(max_distance_km),
    }
    payload = json.dumps(coordinates, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _show_examples(workflow):
    customer_path, store_path = EXAMPLE_FILES[workflow]
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "Download customer example",
            customer_path.read_bytes(),
            file_name=customer_path.name,
            mime="text/csv",
            width="stretch",
        )
    with col_b:
        st.download_button(
            "Download store example",
            store_path.read_bytes(),
            file_name=store_path.name,
            mime="text/csv",
            width="stretch",
        )


def _collect_inputs(workflow, source, bounds, customer_count, store_count, seed, uploaded_customers, uploaded_stores):
    if source == "Synthetic Chennai demo":
        return _cached_demo_data(customer_count, store_count, seed, bounds)
    if source == "Example CSVs":
        customer_path, store_path = EXAMPLE_FILES[workflow]
        return (
            validate_customers_csv(customer_path.read_bytes(), bounds=bounds),
            validate_stores_csv(store_path.read_bytes(), bounds=bounds),
        )
    if uploaded_customers is None or uploaded_stores is None:
        raise InputValidationError(["Upload both a customer CSV and a candidate-store CSV."])
    return (
        validate_customers_csv(uploaded_customers.getvalue(), bounds=bounds),
        validate_stores_csv(uploaded_stores.getvalue(), bounds=bounds),
    )


def _store_summary(result):
    if result is None:
        return {}, {}
    loads = defaultdict(float)
    for assignment in result.assignments:
        loads[assignment["store_id"]] += assignment["demand"]
    return loads, result.capacity_utilization


def _add_customer_layers(map_object, customers, show_heatmap, heatmap_metric, show_customers, show_cluster_outlines):
    if show_heatmap:
        heat_weight = "demand" if heatmap_metric == "Orders per day" else None
        weighted_data = [
            [row["latitude"], row["longitude"], row["demand"]]
            if heat_weight
            else [row["latitude"], row["longitude"]]
            for row in customers
        ]
        HeatMap(
            weighted_data,
            name=f"Customer density ({heatmap_metric.lower()})",
            radius=18,
            blur=14,
            min_opacity=0.2,
            show=True,
        ).add_to(map_object)

    if show_customers:
        marker_cluster = MarkerCluster(
            name="Customer locations",
            options={"chunkedLoading": True, "disableClusteringAtZoom": 15},
        )
        for customer in customers[:500]:
            tooltip = (
                f"Customer {customer['customer_id']} | "
                f"{customer['demand']:g} orders/day"
            )
            folium.CircleMarker(
                [customer["latitude"], customer["longitude"]],
                radius=3,
                color="#c8563e",
                fill=True,
                fill_color="#e16d52",
                fill_opacity=0.72,
                weight=1,
                tooltip=tooltip,
            ).add_to(marker_cluster)
        marker_cluster.add_to(map_object)

    if show_cluster_outlines and customers:
        grouped = defaultdict(list)
        cell_degrees = 0.025
        for customer in customers:
            cell = (
                int(customer["latitude"] / cell_degrees),
                int(customer["longitude"] / cell_degrees),
            )
            grouped[cell].append(customer)
        outline_layer = folium.FeatureGroup(name="Demand cluster outlines", show=True)
        for (_, _), rows in grouped.items():
            if len(rows) < 4:
                continue
            center_lat = sum(row["latitude"] for row in rows) / len(rows)
            center_lon = sum(row["longitude"] for row in rows) / len(rows)
            demand = sum(row["demand"] for row in rows)
            cluster_circ = folium.Circle(
                [center_lat, center_lon],
                radius=650,
                color="#477e9b",
                weight=1,
                fill=True,
                fill_color="#477e9b",
                fill_opacity=0.05,
            )
            cluster_circ.options["interactive"] = False
            cluster_circ.add_to(outline_layer)
        outline_layer.add_to(map_object)


def _build_map(
    customers,
    stores,
    result,
    *,
    bounds,
    max_distance_km,
    distance_mode,
    selected_store_id,
    show_heatmap,
    heatmap_metric,
    show_customers,
    show_cluster_outlines,
    show_assignments,
    isochrone_geojson=None,
    is_dark=False,
    collapse_layers=True,
    center_on_store=False,
):
    center = [
        sum(row["latitude"] for row in customers) / len(customers),
        sum(row["longitude"] for row in customers) / len(customers),
    ] if customers else [13.0450, 80.2200]

    sel_store_loc = next((s for s in stores if s["store_id"] == selected_store_id), None)
    if center_on_store and sel_store_loc:
        map_center = [sel_store_loc["latitude"], sel_store_loc["longitude"]]
        map_zoom = 12
    else:
        map_state = st.session_state.get("map_view", {})
        map_center = map_state.get("center", center)
        map_zoom = map_state.get("zoom", 11)

    map_object = folium.Map(
        location=map_center,
        zoom_start=map_zoom,
        tiles="OpenStreetMap",
        control_scale=True,
        prefer_canvas=True,
    )
    map_css = f"""
    <style>
    {'''
    .leaflet-tile-pane {
        filter: invert(100%) hue-rotate(180deg) brightness(85%) contrast(90%) saturate(80%);
    }
    .leaflet-container {
        background: #0b0f19 !important;
    }
    .leaflet-control-layers {
        background: #151c2c !important;
        color: #f1f5f9 !important;
        border: 1px solid #26334d !important;
        border-radius: 6px !important;
    }
    .leaflet-control-layers-toggle {
        filter: invert(100%);
    }
    .leaflet-control-zoom a {
        background-color: #151c2c !important;
        color: #f1f5f9 !important;
        border-color: #26334d !important;
    }
    .leaflet-popup-content-wrapper {
        background: #151c2cf8 !important;
        color: #f1f5f9 !important;
        border: 1px solid #26334d !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 16px rgba(0,0,0,0.5) !important;
    }
    .leaflet-popup-tip {
        background: #151c2cf8 !important;
    }
    .leaflet-tooltip-pane {
        z-index: 99999 !important;
    }
    .leaflet-tooltip {
        background: #151c2cf8 !important;
        color: #f1f5f9 !important;
        border: 1px solid #26334d !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 16px rgba(0,0,0,0.6) !important;
        padding: 8px 12px !important;
        font-size: 12px !important;
        pointer-events: none !important;
        opacity: 1 !important;
        z-index: 99999 !important;
    }
    ''' if is_dark else '''
    .leaflet-container {
        background: #f8fafc !important;
    }
    .leaflet-control-layers {
        background: #ffffff !important;
        color: #0f172a !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 6px !important;
    }
    .leaflet-control-zoom a {
        background-color: #ffffff !important;
        color: #0f172a !important;
        border-color: #cbd5e1 !important;
    }
    .leaflet-popup-content-wrapper {
        background: #fffffff8 !important;
        color: #0f172a !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 16px rgba(0,0,0,0.12) !important;
    }
    .leaflet-popup-tip {
        background: #fffffff8 !important;
    }
    .leaflet-tooltip-pane {
        z-index: 99999 !important;
    }
    .leaflet-tooltip {
        background: #fffffff8 !important;
        color: #0f172a !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 16px rgba(0,0,0,0.12) !important;
        padding: 8px 12px !important;
        font-size: 12px !important;
        pointer-events: none !important;
        opacity: 1 !important;
        z-index: 99999 !important;
    }
    '''}
    /* CRITICAL: Guarantee coverage circles and polygons never block store markers */
    #map_div, .folium-map {{
        width: 100% !important;
        height: 640px !important;
    }}
    .float-child, .float-container {{
        width: 100% !important;
    }}
    .leaflet-overlay-pane path:not(.store-marker-circle) {{
        pointer-events: none !important;
    }}
    .store-marker-circle {{
        pointer-events: auto !important;
        cursor: pointer !important;
        transition: transform 0.15s ease, filter 0.15s ease;
    }}
    .store-marker-circle:hover {{
        filter: drop-shadow(0 0 8px {'#10b981' if is_dark else '#0f7773'}) brightness(1.25) !important;
    }}
    </style>
    """
    map_object.get_root().header.add_child(folium.Element(map_css))

    assigned_load, utilization = _store_summary(result)
    open_ids = set(result.open_store_ids) if result and result.status in ("OPTIMAL", "FEASIBLE_LIMIT") else set()
    open_color = "#10b981" if is_dark else "#0f7773"
    candidate_color = "#64748b" if is_dark else "#6b7c83"
    border_color = "#0b0f19" if is_dark else "white"

    # 1. Background Layers: Coverage Gap Polygons (non-interactive)
    gap_stroke = "#f43f5e" if is_dark else "#c8563e"
    gap_fill = "#fb7185" if is_dark else "#e16d52"
    gap_stores = [store for store in stores if store["store_id"] in open_ids] if open_ids else stores
    if distance_mode == "Straight-line":
        try:
            gaps = uncovered_region_geojson(bounds, gap_stores, max_distance_km)
            if gaps["features"]:
                folium.GeoJson(
                    gaps,
                    name="Uncovered service gaps",
                    interactive=False,
                    style_function=lambda _: {
                        "color": gap_stroke,
                        "weight": 1,
                        "fillColor": gap_fill,
                        "fillOpacity": 0.22 if is_dark else 0.18,
                    },
                ).add_to(map_object)
        except (ValueError, TypeError):
            pass
    elif distance_mode == "Road distance" and isochrone_geojson:
        try:
            road_gaps = uncovered_road_gap_geojson(bounds, [isochrone_geojson])
            if road_gaps["features"]:
                folium.GeoJson(
                    road_gaps,
                    name="Uncovered road service gaps",
                    interactive=False,
                    style_function=lambda _: {
                        "color": gap_stroke,
                        "weight": 1,
                        "fillColor": gap_fill,
                        "fillOpacity": 0.22 if is_dark else 0.18,
                    },
                ).add_to(map_object)
        except (ValueError, TypeError):
            pass

    # 2. Background Layers: Selected Store Coverage Radius / Isochrone (non-interactive)
    coverage_accent = "#14b8a6" if is_dark else "#0f7773"
    selected_store = next((store for store in stores if store["store_id"] == selected_store_id), None)
    if selected_store is not None:
        coverage = folium.FeatureGroup(name="Selected store coverage", show=True)
        if distance_mode == "Straight-line":
            cov_circ = folium.Circle(
                [selected_store["latitude"], selected_store["longitude"]],
                radius=max_distance_km * 1000,
                color=coverage_accent,
                weight=2,
                fill=True,
                fill_color=coverage_accent,
                fill_opacity=0.12 if is_dark else 0.09,
            )
            cov_circ.options["interactive"] = False
            cov_circ.add_to(coverage)
        elif isochrone_geojson:
            folium.GeoJson(
                isochrone_geojson,
                name=f"Road reachable area: {selected_store_id}",
                interactive=False,
                style_function=lambda _: {
                    "color": coverage_accent,
                    "weight": 2,
                    "fillColor": coverage_accent,
                    "fillOpacity": 0.18 if is_dark else 0.14,
                },
            ).add_to(coverage)
        coverage.add_to(map_object)

    # 3. Background Layers: Customer Assignment PolyLines (non-interactive)
    if show_assignments and result and result.assignments:
        assignment_layer = folium.FeatureGroup(name="Assignments", show=True)
        shown = 0
        store_lookup = {store["store_id"]: store for store in stores}
        customer_lookup = {customer["customer_id"]: customer for customer in customers}
        assign_color = "#38bdf8" if is_dark else "#477e9b"
        for assignment in result.assignments:
            if assignment["store_id"] != selected_store_id:
                continue
            customer = customer_lookup.get(assignment["customer_id"])
            store = store_lookup.get(assignment["store_id"])
            if customer is None or store is None:
                continue
            pline = folium.PolyLine(
                [[store["latitude"], store["longitude"]], [customer["latitude"], customer["longitude"]]],
                color=assign_color,
                weight=1.5 if is_dark else 1,
                opacity=0.55 if is_dark else 0.35,
            )
            pline.options["interactive"] = False
            pline.add_to(assignment_layer)
            shown += 1
            if shown >= 150:
                break
        assignment_layer.add_to(map_object)

    # 4. Background Layers: Unserviceable customers
    if result and result.unserviceable_customer_ids:
        unserviceable_ids = set(result.unserviceable_customer_ids)
        layer = folium.FeatureGroup(name="Unserviceable customers", show=True)
        for customer in customers:
            if customer["customer_id"] in unserviceable_ids:
                folium.CircleMarker(
                    [customer["latitude"], customer["longitude"]],
                    radius=7,
                    color="#e11d48" if is_dark else "#a23f2b",
                    fill=True,
                    fill_color="#fb7185" if is_dark else "#e16d52",
                    fill_opacity=0.95,
                    tooltip=f"No eligible store: customer {customer['customer_id']}",
                ).add_to(layer)
        layer.add_to(map_object)

    # 5. Customer Layers (HeatMap, Cluster Outlines, Markers)
    _add_customer_layers(map_object, customers, show_heatmap, heatmap_metric, show_customers, show_cluster_outlines)

    # 6. Chennai Center Marker
    badge_bg = "#151c2cdc" if is_dark else "#ffffffdc"
    badge_color = "#f1f5f9" if is_dark else "#173238"
    badge_border = "#26334d" if is_dark else "#cbd8d2"
    folium.Marker(
        center,
        icon=folium.DivIcon(
            html=f'<div style="font:700 11px sans-serif;color:{badge_color};background:{badge_bg};padding:3px 6px;border:1px solid {badge_border};border-radius:4px">CHENNAI</div>',
            icon_size=(70, 18),
            icon_anchor=(35, 9),
        ),
    ).add_to(map_object)

    # 7. Foreground Layer (ON TOP OF EVERYTHING): Candidate & Open Store Markers
    candidates = folium.FeatureGroup(name="Dark store locations", show=True)
    for store in stores:
        store_id = store["store_id"]
        is_open = store_id in open_ids
        color = open_color if is_open else candidate_color
        is_selected = (store_id == selected_store_id)
        border = "#38bdf8" if is_selected else border_color
        rad = 14 if is_selected else (11 if is_open else 9)

        if is_open:
            store_info_html = (
                f"<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;font-size:12px;line-height:1.5;min-width:215px;'>"
                f"<div style='font-weight:700;font-size:13px;color:{'#10b981' if is_dark else '#0f7773'};border-bottom:1px solid {'#26334d' if is_dark else '#e2e8f0'};padding-bottom:3px;margin-bottom:5px;'>"
                f"🟢 Open Dark Store {store_id}"
                f"{' &nbsp;<span style=\"color:#14b8a6;font-size:11px;\">[SELECTED]</span>' if is_selected else ''}"
                f"</div>"
                f"<div><b>Fixed Lease:</b> ₹{store['fixed_cost']:,.0f} / day</div>"
                f"<div><b>Daily Capacity:</b> {store['capacity']:,.0f} orders/d</div>"
                f"<div><b>Assigned Load:</b> {assigned_load.get(store_id, 0):,.0f} orders/d</div>"
                f"<div><b>Utilization:</b> {100 * utilization.get(store_id, 0):.1f}%</div>"
                f"<div style='margin-top:6px;font-size:11px;color:#0ea5e9;font-style:italic;border-top:1px dashed {'#334155' if is_dark else '#cbd5e1'};padding-top:4px;'>"
                f"Click store to inspect coverage & assignments"
                f"</div>"
                f"</div>"
            )
        else:
            store_info_html = (
                f"<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;font-size:12px;line-height:1.5;min-width:215px;'>"
                f"<div style='font-weight:700;font-size:13px;color:{'#94a3b8' if is_dark else '#64748b'};border-bottom:1px solid {'#26334d' if is_dark else '#e2e8f0'};padding-bottom:3px;margin-bottom:5px;'>"
                f"⚪ Inactive Candidate {store_id}"
                f"{' &nbsp;<span style=\"color:#14b8a6;font-size:11px;\">[SELECTED]</span>' if is_selected else ''}"
                f"</div>"
                f"<div><b>Fixed Lease:</b> ₹{store['fixed_cost']:,.0f} / day</div>"
                f"<div><b>Max Capacity:</b> {store['capacity']:,.0f} orders/d</div>"
                f"<div style='color:{'#94a3b8' if is_dark else '#64748b'};font-style:italic;'>Status: Inactive candidate (0 orders assigned)</div>"
                f"<div style='margin-top:6px;font-size:11px;color:#0ea5e9;font-style:italic;border-top:1px dashed {'#334155' if is_dark else '#cbd5e1'};padding-top:4px;'>"
                f"Click candidate store to view location"
                f"</div>"
                f"</div>"
            )

        marker = folium.CircleMarker(
            [store["latitude"], store["longitude"]],
            radius=rad,
            color=border,
            weight=3 if is_selected else 2,
            fill=True,
            fill_color=color,
            fill_opacity=1.0,
            tooltip=folium.Tooltip(store_info_html, sticky=True, opacity=1.0),
            popup=folium.Popup(store_info_html, max_width=300),
            pane="markerPane",
        )
        marker.options["className"] = "store-marker-circle"
        marker.add_to(candidates)
    candidates.add_to(map_object)
    folium.LayerControl(collapsed=collapse_layers, autoZIndex=False).add_to(map_object)

    # 8. Client-side Cursor Lock-On & Proximity Reticle HUD
    map_var_name = map_object.get_name()
    store_pts = [
        {
            "id": s["store_id"],
            "lat": s["latitude"],
            "lng": s["longitude"],
            "isOpen": s["store_id"] in open_ids,
            "cost": s["fixed_cost"],
            "cap": s["capacity"],
            "load": assigned_load.get(s["store_id"], 0),
            "util": round(100 * utilization.get(s["store_id"], 0), 1),
        }
        for s in stores
    ]
    snap_script = f"""
    <style>
    .cursor-lockon-reticle {{
        position: absolute;
        pointer-events: none;
        z-index: 9999;
        display: none;
        transform: translate(-50%, -50%);
        transition: width 0.1s ease, height 0.1s ease;
    }}
    .cursor-lockon-ring {{
        width: 100%;
        height: 100%;
        border-radius: 50%;
        box-sizing: border-box;
        animation: lockon-pulse 1.2s infinite cubic-bezier(0.4, 0, 0.6, 1);
    }}
    .cursor-lockon-badge {{
        position: absolute;
        bottom: -26px;
        left: 50%;
        transform: translateX(-50%);
        padding: 3px 8px;
        border-radius: 4px;
        font: 700 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        white-space: nowrap;
        box-shadow: 0 3px 8px rgba(0,0,0,0.45);
        pointer-events: none;
    }}
    @keyframes lockon-pulse {{
        0%, 100% {{ transform: scale(1); opacity: 0.95; }}
        50% {{ transform: scale(1.22); opacity: 0.45; }}
    }}
    </style>
    <script>
    (function() {{
        var stores = {json.dumps(store_pts)};
        var snapRadius = 48;
        var isDark = {str(is_dark).lower()};
        var mapVarName = "{map_var_name}";
        var activeTarget = null;
        var attempts = 0;

        function findMap() {{
            try {{
                if (window.map_div && typeof window.map_div.latLngToContainerPoint === 'function') {{
                    return window.map_div;
                }}
                if (window[mapVarName] && typeof window[mapVarName].latLngToContainerPoint === 'function') {{
                    return window[mapVarName];
                }}
            }} catch(e) {{}}
            var el = document.getElementById('map_div') || document.querySelector('.folium-map');
            if (el && el.id && window[el.id] && typeof window[el.id].latLngToContainerPoint === 'function') {{
                return window[el.id];
            }}
            for (var k in window) {{
                try {{
                    if (window[k] && typeof window[k].latLngToContainerPoint === 'function') {{
                        return window[k];
                    }}
                }} catch(e) {{}}
            }}
            return null;
        }}

        function initLockOn() {{
            var map = findMap();
            if (!map) {{
                if (++attempts < 50) setTimeout(initLockOn, 100);
                return;
            }}
            var container = map.getContainer();
            if (!container || container.querySelector('.cursor-lockon-reticle')) return;

            var reticle = document.createElement('div');
            reticle.className = 'cursor-lockon-reticle';
            var ring = document.createElement('div');
            ring.className = 'cursor-lockon-ring';
            var badge = document.createElement('div');
            badge.className = 'cursor-lockon-badge';
            reticle.appendChild(ring);
            reticle.appendChild(badge);
            container.appendChild(reticle);

            function updateReticle() {{
                if (!activeTarget) return;
                var pt = map.latLngToContainerPoint([activeTarget.lat, activeTarget.lng]);
                reticle.style.left = pt.x + 'px';
                reticle.style.top = pt.y + 'px';
            }}

            function checkProximity(e) {{
                if (!e || !e.latlng) return;
                var mousePt = map.latLngToContainerPoint(e.latlng);
                var closest = null;
                var minDist = snapRadius;

                for (var i = 0; i < stores.length; i++) {{
                    var s = stores[i];
                    var pt = map.latLngToContainerPoint([s.lat, s.lng]);
                    var dx = pt.x - mousePt.x;
                    var dy = pt.y - mousePt.y;
                    var d = Math.sqrt(dx * dx + dy * dy);
                    if (d < minDist) {{
                        minDist = d;
                        closest = {{ store: s, pt: pt }};
                    }}
                }}

                activeTarget = closest ? closest.store : null;

                if (closest) {{
                    var s = closest.store;
                    var color = s.isOpen ? '#10b981' : '#14b8a6';
                    var bg = isDark ? '#151c2cf8' : '#fffffff8';

                    reticle.style.left = closest.pt.x + 'px';
                    reticle.style.top = closest.pt.y + 'px';
                    reticle.style.width = '42px';
                    reticle.style.height = '42px';
                    reticle.style.display = 'block';
                    container.style.cursor = 'pointer';

                    ring.style.border = '2.5px solid ' + color;
                    ring.style.boxShadow = '0 0 12px ' + color;

                    badge.style.background = bg;
                    badge.style.color = color;
                    badge.style.border = '1px solid ' + color;
                    badge.innerHTML = '🎯 <b>' + (s.isOpen ? 'Open ' : 'Store ') + s.id + '</b> &bull; ₹' + Number(s.cost).toLocaleString() + '/d &bull; ' + s.util + '%';
                }} else {{
                    reticle.style.display = 'none';
                    container.style.cursor = '';
                }}
            }}

            map.on('mousemove', checkProximity);
            map.on('move', updateReticle);
            map.on('zoom', updateReticle);
            map.on('mouseout', function() {{
                reticle.style.display = 'none';
                container.style.cursor = '';
                activeTarget = null;
            }});

            map.on('click', function(e) {{
                if (activeTarget) {{
                    map.eachLayer(function(layer) {{
                        if (layer.options && layer.options.className === 'store-marker-circle') {{
                            var latlng = layer.getLatLng();
                            if (Math.abs(latlng.lat - activeTarget.lat) < 0.0001 && Math.abs(latlng.lng - activeTarget.lng) < 0.0001) {{
                                layer.openPopup();
                            }}
                        }}
                    }});
                }}
            }});
        }}

        if (document.readyState === 'complete') {{
            initLockOn();
        }} else {{
            window.addEventListener('load', initLockOn);
            setTimeout(initLockOn, 150);
        }}
    }})();
    </script>
    """
    map_object.get_root().html.add_child(folium.Element(snap_script))
    return map_object


def _nearest_store_id(clicked, stores, max_dist_km=2.0):
    if not isinstance(clicked, dict):
        return None
    latitude = clicked.get("lat")
    longitude = clicked.get("lng")
    if latitude is None or longitude is None:
        return None
    nearest = min(
        stores,
        key=lambda store: haversine_distance_km(
            latitude, longitude, store["latitude"], store["longitude"]
        ),
    )
    if haversine_distance_km(latitude, longitude, nearest["latitude"], nearest["longitude"]) <= max_dist_km:
        return nearest["store_id"]
    return None


def _display_kpis(result):
    if result.status not in ("OPTIMAL", "FEASIBLE_LIMIT"):
        return
    utilization = sum(result.capacity_utilization.values()) / max(len(result.capacity_utilization), 1)

    st.markdown("##### Financial Performance")
    f_row1 = st.columns(3)
    f_row1[0].metric(
        "Net Profit / day",
        f"₹{result.profit:,.0f}",
        help="Net daily profit: Total Revenue minus Total Operating Cost (Fixed Store Cost + Transport Cost). See index at bottom for details.",
    )
    f_row1[1].metric(
        "Total Revenue / day",
        f"₹{result.revenue:,.0f}",
        help="Total daily revenue generated from customer order fulfillment (Total demand × Revenue rate/order).",
    )
    f_row1[2].metric(
        "Total Operating Cost",
        f"₹{result.objective_value:,.0f} / day",
        help="Total daily cost minimized by the solver: Fixed store lease/operations + demand-weighted customer delivery transport cost.",
    )

    f_row2 = st.columns(2)
    f_row2[0].metric(
        "Fixed Store Lease Cost",
        f"₹{result.fixed_cost:,.0f} / day",
        f"{len(result.open_store_ids)} facilities active",
        help="Daily lease, facility, and operational overhead costs across all opened dark stores.",
    )
    f_row2[1].metric(
        "Customer Transport Cost",
        f"₹{result.transport_cost:,.0f} / day",
        f"{result.average_distance_km:.2f} km avg distance",
        help="Demand-weighted delivery transport cost across all assigned customer delivery routes.",
    )

    st.markdown("##### Operational Performance")
    op_row = st.columns(4)
    op_row[0].metric(
        "Stores Opened",
        f"{len(result.open_store_ids)} facilities",
        help="Number of candidate dark stores selected by the optimization model to be activated.",
    )
    op_row[1].metric(
        "Demand Served",
        f"{result.total_demand:,.0f} orders/d",
        help="Total daily customer orders fulfilled. Hard constraint requires 100% of demand to be satisfied.",
    )
    op_row[2].metric(
        "Avg Delivery Distance",
        f"{result.average_distance_km:.2f} km",
        help="Demand-weighted average delivery distance from assigned dark store to customer location.",
    )
    op_row[3].metric(
        "Mean Store Utilization",
        f"{100 * utilization:.1f}%",
        help="Average percent of capacity used across all opened dark stores. High utilization indicates lean operations.",
    )


def _on_focus_store(store_id: str) -> None:
    st.session_state["selected_store_id"] = store_id
    st.session_state["lock_view_store"] = True


def _render_store_directory(stores, result, selected_store_id, is_dark=False, key_prefix="dir"):
    if not stores:
        return
    open_ids = set(result.open_store_ids) if result and result.status in ("OPTIMAL", "FEASIBLE_LIMIT") else set()
    assigned_load, utilization = _store_summary(result)

    open_stores = [s for s in stores if s["store_id"] in open_ids]
    inactive_stores = [s for s in stores if s["store_id"] not in open_ids]

    card_bg = "#151c2c" if is_dark else "#f8fafc"
    card_border = "#26334d" if is_dark else "#cbd5e1"
    sub_color = "#94a3b8" if is_dark else "#475569"
    text_color = "#f1f5f9" if is_dark else "#0f172a"
    bar_bg = "#334155" if is_dark else "#e2e8f0"
    open_color = "#10b981" if is_dark else "#0f7773"

    with st.expander(f"🏬 Dark Store Network Directory ({len(open_stores)} of {len(stores)} stores open)", expanded=True):
        st.caption("Review all open and candidate dark stores. Click **Show on map** to center the map camera and inspect any facility.")

        filter_mode = st.radio(
            "Filter stores by status",
            ["All Stores", f"Open Stores ({len(open_stores)})", f"Inactive Candidates ({len(inactive_stores)})"],
            horizontal=True,
            key=f"{key_prefix}_status_filter",
            label_visibility="collapsed",
        )

        if filter_mode.startswith("Open Stores"):
            displayed_stores = open_stores
        elif filter_mode.startswith("Inactive Candidates"):
            displayed_stores = inactive_stores
        else:
            displayed_stores = open_stores + inactive_stores

        if not displayed_stores:
            st.info("No stores match the selected filter.")
            return

        for s in displayed_stores:
            s_id = s["store_id"]
            is_open = s_id in open_ids
            is_curr_selected = (s_id == selected_store_id)
            load = assigned_load.get(s_id, 0)
            cap = s["capacity"]
            util_pct = round(100 * utilization.get(s_id, 0.0), 1)

            active_border = "#14b8a6" if is_curr_selected else card_border
            active_bg = "#1c253b" if (is_curr_selected and is_dark) else ("#f0fdfa" if is_curr_selected else card_bg)

            c_info, c_btn = st.columns([4.2, 1.2])
            with c_info:
                if is_open:
                    hud_card = (
                        f"<div style='background:{active_bg};border:1.5px solid {active_border};border-radius:8px;padding:8px 12px;margin-bottom:6px;'>"
                        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;'>"
                        f"<span style='font-weight:700;font-size:13px;color:{open_color};'>🟢 Open Dark Store &mdash; <b>{s_id}</b>"
                        f"{' &nbsp;<span style=\"color:#38bdf8;font-size:11px;font-weight:600;\">[VIEWING ON MAP]</span>' if is_curr_selected else ''}</span>"
                        f"<span style='font-size:11.5px;color:{sub_color};'>Fixed Lease: <b>₹{s['fixed_cost']:,.0f}/day</b></span>"
                        f"</div>"
                        f"<div style='display:flex;justify-content:space-between;font-size:11.5px;margin-bottom:4px;color:{text_color};'>"
                        f"<span>Capacity: <b>{cap:,.0f} ord/d</b></span>"
                        f"<span>Assigned: <b>{load:,.0f} ord/d</b></span>"
                        f"<span>Utilization: <b style='color:{open_color};'>{util_pct}%</b></span>"
                        f"</div>"
                        f"<div style='background:{bar_bg};border-radius:4px;height:6px;overflow:hidden;'>"
                        f"<div style='background:{open_color};width:{min(util_pct, 100)}%;height:100%;'></div>"
                        f"</div>"
                        f"</div>"
                    )
                else:
                    # Inactive candidate: NO PERCENTAGE BAR BOX
                    hud_card = (
                        f"<div style='background:{active_bg};border:1.5px solid {active_border};border-radius:8px;padding:8px 12px;margin-bottom:6px;'>"
                        f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
                        f"<span style='font-weight:600;font-size:13px;color:{sub_color};'>⚪ Inactive Candidate &mdash; <b>{s_id}</b>"
                        f"{' &nbsp;<span style=\"color:#38bdf8;font-size:11px;font-weight:600;\">[VIEWING ON MAP]</span>' if is_curr_selected else ''}</span>"
                        f"<span style='font-size:11.5px;color:{sub_color};'>Fixed Lease: <b>₹{s['fixed_cost']:,.0f}/day</b></span>"
                        f"</div>"
                        f"<div style='display:flex;justify-content:space-between;font-size:11.5px;margin-top:4px;color:{sub_color};'>"
                        f"<span>Max Capacity: <b>{cap:,.0f} orders/d</b></span>"
                        f"<span>Status: <i>Inactive (0 orders assigned)</i></span>"
                        f"</div>"
                        f"</div>"
                    )
                st.markdown(hud_card, unsafe_allow_html=True)

            with c_btn:
                btn_label = "🎯 On Map" if is_curr_selected else "📍 Show on map"
                st.button(
                    btn_label,
                    key=f"{key_prefix}_btn_{s_id}",
                    use_container_width=True,
                    disabled=is_curr_selected,
                    on_click=_on_focus_store,
                    args=(s_id,),
                )


def _render_scenario_table(sensitivity_results, pareto_p_set, is_dark=False):
    table_rows = []
    for item in sensitivity_results:
        is_pareto = item.p_value in pareto_p_set
        status_tag = "Frontier" if is_pareto else ("Dominated" if item.result.status in ("OPTIMAL", "FEASIBLE_LIMIT") else "Infeasible")
        table_rows.append({
            "Pareto Optimal": status_tag,
            "P (Limit)": item.p_value,
            "Stores Open": len(item.result.open_store_ids),
            "Status": item.result.status,
            "Profit/day": f"₹{item.result.profit:,.2f}" if item.result.profit is not None else "N/A",
            "Fixed Cost": f"₹{item.result.fixed_cost:,.2f}" if item.result.fixed_cost is not None else "N/A",
            "Transport Cost": f"₹{item.result.transport_cost:,.2f}" if item.result.transport_cost is not None else "N/A",
            "Avg Distance (km)": f"{item.result.average_distance_km:.2f}" if item.result.average_distance_km is not None else "N/A",
            "Elapsed (s)": f"{item.result.elapsed_seconds:.2f}" if item.result.elapsed_seconds is not None else "N/A",
            "Message": item.result.message,
        })

    card_bg = "#151c2c" if is_dark else "#ffffff"
    border_color = "#26334d" if is_dark else "#cbd5e1"
    th_bg = "#1e293b" if is_dark else "#f1f5f9"
    th_color = "#f1f5f9" if is_dark else "#0f172a"
    td_color = "#cbd5e1" if is_dark else "#334155"
    row_odd = "#151c2c" if is_dark else "#ffffff"
    row_even = "#0f172a" if is_dark else "#f8fafc"

    html = [
        f"<div style='border:1px solid {border_color};border-radius:8px;overflow-x:auto;margin:12px 0;background:{card_bg};'>",
        f"<table style='width:100%;border-collapse:collapse;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;font-size:12.5px;'>",
        f"<thead><tr style='background:{th_bg};border-bottom:1px solid {border_color};'>",
        f"<th style='padding:10px 12px;text-align:left;color:{th_color};font-weight:700;'>Trade-Off Status</th>",
        f"<th style='padding:10px 12px;text-align:center;color:{th_color};font-weight:700;'>P</th>",
        f"<th style='padding:10px 12px;text-align:center;color:{th_color};font-weight:700;'>Open</th>",
        f"<th style='padding:10px 12px;text-align:left;color:{th_color};font-weight:700;'>Solver Status</th>",
        f"<th style='padding:10px 12px;text-align:right;color:{th_color};font-weight:700;'>Profit / day</th>",
        f"<th style='padding:10px 12px;text-align:right;color:{th_color};font-weight:700;'>Fixed Cost</th>",
        f"<th style='padding:10px 12px;text-align:right;color:{th_color};font-weight:700;'>Transport Cost</th>",
        f"<th style='padding:10px 12px;text-align:right;color:{th_color};font-weight:700;'>Avg Dist (km)</th>",
        f"<th style='padding:10px 12px;text-align:right;color:{th_color};font-weight:700;'>Solver Time</th>",
        f"</tr></thead><tbody>",
    ]

    for idx, row in enumerate(table_rows):
        bg = row_odd if idx % 2 == 0 else row_even
        tag = row["Pareto Optimal"]
        if tag == "Frontier":
            badge = f"<span style='background:{'#064e3b' if is_dark else '#d1fae5'};color:{'#34d399' if is_dark else '#047857'};border:1px solid {'#059669' if is_dark else '#6ee7b7'};padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;'>★ Pareto Frontier</span>"
        elif tag == "Dominated":
            badge = f"<span style='background:{'#1e293b' if is_dark else '#f1f5f9'};color:{'#94a3b8' if is_dark else '#64748b'};border:1px solid {'#334155' if is_dark else '#cbd5e1'};padding:2px 8px;border-radius:12px;font-size:11px;'>Dominated</span>"
        else:
            badge = f"<span style='background:{'#4c0519' if is_dark else '#ffe4e6'};color:{'#fb7185' if is_dark else '#be123c'};border:1px solid {'#9f1239' if is_dark else '#fecdd3'};padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;'>Infeasible</span>"

        html.append(
            f"<tr style='background:{bg};border-bottom:1px solid {border_color};'>"
            f"<td style='padding:8px 12px;'>{badge}</td>"
            f"<td style='padding:8px 12px;text-align:center;color:{td_color};font-weight:600;'>{row['P (Limit)']}</td>"
            f"<td style='padding:8px 12px;text-align:center;color:{td_color};'>{row['Stores Open']}</td>"
            f"<td style='padding:8px 12px;color:{td_color};font-size:11.5px;'>{row['Status']}</td>"
            f"<td style='padding:8px 12px;text-align:right;color:{'#34d399' if is_dark else '#059669'};font-weight:700;font-variant-numeric:tabular-nums;'>{row['Profit/day']}</td>"
            f"<td style='padding:8px 12px;text-align:right;color:{td_color};font-variant-numeric:tabular-nums;'>{row['Fixed Cost']}</td>"
            f"<td style='padding:8px 12px;text-align:right;color:{td_color};font-variant-numeric:tabular-nums;'>{row['Transport Cost']}</td>"
            f"<td style='padding:8px 12px;text-align:right;color:{td_color};font-variant-numeric:tabular-nums;'>{row['Avg Distance (km)']}</td>"
            f"<td style='padding:8px 12px;text-align:right;color:{td_color};font-variant-numeric:tabular-nums;'>{row['Elapsed (s)']}</td>"
            f"</tr>"
        )
    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    csv_data = _csv_bytes(table_rows, tuple(table_rows[0].keys()))
    st.download_button(
        "📥 Download Scenario Summary (CSV)",
        data=csv_data,
        file_name="sensitivity_scenario_summary.csv",
        mime="text/csv",
        key="download_sens_summary",
    )


def _assignment_download(result):
    if not result or not result.assignments:
        return
    columns = ("customer_id", "store_id", "demand", "distance_km", "transport_cost")
    data = _csv_bytes(result.assignments, columns)
    st.download_button(
        "Download customer assignments",
        data,
        file_name="dark_store_assignments.csv",
        mime="text/csv",
    )


def _compute_pareto_front(feasible_items):
    """Identify non-dominated solutions in (fixed_cost, transport_cost) space.

    Both fixed cost and transport cost are to be minimized.
    A solution is Pareto-optimal if no other configuration achieves both lower
    fixed cost and lower transport cost.
    """
    if not feasible_items:
        return []
    sorted_items = sorted(
        feasible_items,
        key=lambda item: (item.result.fixed_cost or 0.0, item.result.transport_cost or 0.0),
    )
    pareto = []
    min_transport_so_far = float("inf")
    for item in sorted_items:
        trans = item.result.transport_cost if item.result.transport_cost is not None else float("inf")
        if trans < min_transport_so_far:
            pareto.append(item)
            min_transport_so_far = trans
    return pareto


def _render_sensitivity_plot(sensitivity_results, is_dark=False):
    feasible = [
        item for item in sensitivity_results
        if item.result.status in ("OPTIMAL", "FEASIBLE_LIMIT")
    ]
    if feasible:
        pareto_items = _compute_pareto_front(feasible)
        pareto_p_set = {item.p_value for item in pareto_items}
        best_profit_item = max(feasible, key=lambda item: item.result.profit or -float("inf"))
        min_feasible_p = min(item.p_value for item in feasible)
        best_avg_dist = min(
            (item.result.average_distance_km for item in feasible if item.result.average_distance_km is not None),
            default=0.0,
        )

        open_store_counts = [len(item.result.open_store_ids) for item in feasible]
        unique_counts = set(open_store_counts)
        if len(unique_counts) == 1 and len(feasible) > 1:
            st.info(
                f"💡 **Economic Saturation at P* = {min(unique_counts)} stores**: "
                f"All {len(feasible)} evaluated scenarios opened the exact same {min(unique_counts)} stores. "
                f"Under cost minimization with an upper bound (≤ P), fixed facility lease costs (₹{feasible[0].result.fixed_cost:,.0f}/day) "
                f"exceed customer delivery transport savings. The solver intentionally stops opening additional stores "
                f"because doing so would lower net profit. To force evaluating networks with higher store counts (e.g. 3, 4, 5 stores) "
                f"to achieve faster delivery, select **Exact store count (P stores)** in the sidebar."
            )

        st.markdown(f"##### Recommended Network Setup (Optimal Facility Limit P* = {best_profit_item.p_value} Stores)")
        sc_row1 = st.columns(3)
        sc_row1[0].metric(
            "Optimal Daily Profit",
            f"₹{best_profit_item.result.profit:,.0f} / day",
            f"P = {best_profit_item.p_value} stores",
            help="Maximum net profit achieved among all facility limit scenarios (Revenue minus Total Operating Cost).",
        )
        sc_row1[1].metric(
            "Total Daily Revenue",
            f"₹{best_profit_item.result.revenue:,.0f} / day",
            "100% Demand Served",
            help="Total revenue generated from order fulfillment at the optimal configuration.",
        )
        sc_row1[2].metric(
            "Total Operating Cost",
            f"₹{best_profit_item.result.objective_value:,.0f} / day",
            "Fixed + Transport",
            help="Total daily expenditure minimized by the solver at P*.",
        )

        sc_row2 = st.columns(4)
        sc_row2[0].metric(
            "Fixed Store Lease",
            f"₹{best_profit_item.result.fixed_cost:,.0f} / day",
            f"{len(best_profit_item.result.open_store_ids)} open facilities",
            help="Daily facility lease and operational overhead for the open dark stores.",
        )
        sc_row2[1].metric(
            "Customer Transport",
            f"₹{best_profit_item.result.transport_cost:,.0f} / day",
            f"{best_profit_item.result.average_distance_km:.2f} km avg dist",
            help="Demand-weighted delivery transport cost to serve all customer orders.",
        )
        sc_row2[2].metric(
            "Pareto Frontier Count",
            f"{len(pareto_items)} setups",
            "Non-dominated trade-offs",
            help="Number of non-dominated configurations balancing store lease investment against transport savings.",
        )
        sc_row2[3].metric(
            "Min Feasible Stores",
            f"P = {min_feasible_p} stores",
            f"{len(feasible)} feasible evaluated",
            help="Minimum dark stores required to fulfill total demand and meet service distance limits.",
        )

        template = "plotly_dark" if is_dark else "plotly_white"
        bg_card = "#151c2c" if is_dark else "#ffffff"
        bg_plot = "#0b0f19" if is_dark else "#f8fafc"
        text_color = "#f1f5f9" if is_dark else "#0f172a"
        sub_text_color = "#cbd5e1" if is_dark else "#334155"
        grid_color = "#26334d" if is_dark else "#e2e8f0"
        axis_color = "#475569" if is_dark else "#94a3b8"
        frontier_color = "#10b981" if is_dark else "#0f7773"
        profit_color = "#f59e0b" if is_dark else "#d97706"
        dist_color = "#38bdf8" if is_dark else "#0284c7"

        tab_pareto, tab_profit, tab_distance, tab_breakdown = st.tabs([
            "Pareto Frontier",
            "Profit Curve",
            "Service Distance",
            "Cost Breakdown",
        ])

        with tab_pareto:
            fig_pareto = go.Figure()
            # Non-dominated Pareto frontier
            fig_pareto.add_trace(go.Scatter(
                x=[item.result.fixed_cost for item in pareto_items],
                y=[item.result.transport_cost for item in pareto_items],
                mode="lines+markers",
                name="Pareto Efficient Frontier",
                line={"color": frontier_color, "width": 3, "dash": "solid"},
                marker={"size": 11, "symbol": "diamond", "color": frontier_color},
                hovertemplate=(
                    "<b>P=%{customdata[0]} (Pareto-Optimal)</b><br>"
                    "Stores Open: %{customdata[1]}<br>"
                    "Fixed Cost: ₹%{x:,.2f}/day<br>"
                    "Transport Cost: ₹%{y:,.2f}/day<br>"
                    "Total Cost: ₹%{customdata[2]:,.2f}/day<br>"
                    "Profit: ₹%{customdata[3]:,.2f}/day<br>"
                    "Avg Distance: %{customdata[4]:.2f} km<extra></extra>"
                ),
                customdata=[
                    [
                        item.p_value,
                        len(item.result.open_store_ids),
                        (item.result.fixed_cost or 0) + (item.result.transport_cost or 0),
                        item.result.profit or 0,
                        item.result.average_distance_km or 0,
                    ]
                    for item in pareto_items
                ],
            ))
            # Dominated solutions
            dominated = [item for item in feasible if item.p_value not in pareto_p_set]
            if dominated:
                fig_pareto.add_trace(go.Scatter(
                    x=[item.result.fixed_cost for item in dominated],
                    y=[item.result.transport_cost for item in dominated],
                    mode="markers",
                    name="Dominated (Sub-optimal)",
                    marker={"size": 8, "symbol": "circle", "color": "#64748b" if is_dark else "#94a3b8", "opacity": 0.75},
                    hovertemplate=(
                        "<b>P=%{customdata[0]} (Dominated)</b><br>"
                        "Stores Open: %{customdata[1]}<br>"
                        "Fixed Cost: ₹%{x:,.2f}/day<br>"
                        "Transport Cost: ₹%{y:,.2f}/day<br>"
                        "Profit: ₹%{customdata[2]:,.2f}/day<extra></extra>"
                    ),
                    customdata=[
                        [item.p_value, len(item.result.open_store_ids), item.result.profit or 0]
                        for item in dominated
                    ],
                ))
            # Highlight Maximum Profit configuration
            fig_pareto.add_trace(go.Scatter(
                x=[best_profit_item.result.fixed_cost],
                y=[best_profit_item.result.transport_cost],
                mode="markers",
                name=f"Maximum Profit (P={best_profit_item.p_value})",
                marker={"size": 16, "symbol": "star", "color": profit_color, "line": {"width": 2, "color": "#0b0f19" if is_dark else "#17242a"}},
                hovertemplate=(
                    "<b>Maximum Profit Solution (P=%{customdata[0]})</b><br>"
                    "Profit: ₹%{customdata[1]:,.2f}/day<br>"
                    "Fixed Cost: ₹%{x:,.2f}/day<br>"
                    "Transport Cost: ₹%{y:,.2f}/day<extra></extra>"
                ),
                customdata=[[best_profit_item.p_value, best_profit_item.result.profit or 0]],
            ))
            fig_pareto.update_layout(
                template=template,
                title={"text": "Pareto Trade-Off: Fixed Store Investment vs. Customer Delivery Cost", "font": {"color": text_color, "size": 15}},
                xaxis={
                    "title": {"text": "Daily Fixed Cost (₹/day)", "font": {"color": text_color, "size": 13}},
                    "tickfont": {"color": sub_text_color, "size": 11},
                    "gridcolor": grid_color,
                    "linecolor": axis_color,
                    "zerolinecolor": grid_color,
                },
                yaxis={
                    "title": {"text": "Daily Transport Cost (₹/day)", "font": {"color": text_color, "size": 13}},
                    "tickfont": {"color": sub_text_color, "size": 11},
                    "gridcolor": grid_color,
                    "linecolor": axis_color,
                    "zerolinecolor": grid_color,
                },
                height=420,
                margin={"l": 20, "r": 20, "t": 55, "b": 20},
                paper_bgcolor=bg_card,
                plot_bgcolor=bg_plot,
                font={"color": text_color},
                legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1, "font": {"color": text_color}},
            )
            st.plotly_chart(fig_pareto, width="stretch", theme=None)
            st.caption("Configurations on the frontier line are mathematically non-dominated: no alternative setup achieves lower transport cost without additional fixed store investment.")

        with tab_profit:
            fig_profit = go.Figure()
            fig_profit.add_trace(go.Scatter(
                x=[item.p_value for item in feasible],
                y=[item.result.profit for item in feasible],
                mode="lines+markers",
                name="Daily Profit",
                line={"color": frontier_color, "width": 3},
                marker={"size": 10, "color": [profit_color if item.p_value == best_profit_item.p_value else frontier_color for item in feasible]},
                hovertemplate="P=%{x}<br>Stores Open: %{customdata[0]}<br>Profit: ₹%{y:,.2f}/day<extra></extra>",
                customdata=[[len(item.result.open_store_ids)] for item in feasible],
            ))
            fig_profit.update_layout(
                template=template,
                title={"text": "Daily Profit by Facility Limit (P)", "font": {"color": text_color, "size": 15}},
                xaxis={
                    "title": {"text": "Maximum Stores Allowed (P)", "font": {"color": text_color, "size": 13}},
                    "tickfont": {"color": sub_text_color, "size": 11},
                    "gridcolor": grid_color,
                    "linecolor": axis_color,
                    "zerolinecolor": grid_color,
                },
                yaxis={
                    "title": {"text": "Daily Profit (₹/day)", "font": {"color": text_color, "size": 13}},
                    "tickfont": {"color": sub_text_color, "size": 11},
                    "gridcolor": grid_color,
                    "linecolor": axis_color,
                    "zerolinecolor": grid_color,
                },
                height=400,
                margin={"l": 20, "r": 20, "t": 55, "b": 20},
                paper_bgcolor=bg_card,
                plot_bgcolor=bg_plot,
                font={"color": text_color},
            )
            st.plotly_chart(fig_profit, width="stretch", theme=None)

        with tab_distance:
            fig_dist = go.Figure()
            fig_dist.add_trace(go.Scatter(
                x=[len(item.result.open_store_ids) for item in feasible],
                y=[item.result.average_distance_km for item in feasible],
                mode="lines+markers",
                name="Avg Delivery Distance",
                line={"color": dist_color, "width": 3},
                marker={"size": 10, "color": dist_color},
                hovertemplate="Open Stores: %{x}<br>Avg Distance: %{y:.2f} km<extra></extra>",
            ))
            fig_dist.update_layout(
                template=template,
                title={"text": "Customer Delivery Distance Diminishing Returns", "font": {"color": text_color, "size": 15}},
                xaxis={
                    "title": {"text": "Stores Actually Opened", "font": {"color": text_color, "size": 13}},
                    "tickfont": {"color": sub_text_color, "size": 11},
                    "gridcolor": grid_color,
                    "linecolor": axis_color,
                    "zerolinecolor": grid_color,
                },
                yaxis={
                    "title": {"text": "Demand-Weighted Avg Distance (km)", "font": {"color": text_color, "size": 13}},
                    "tickfont": {"color": sub_text_color, "size": 11},
                    "gridcolor": grid_color,
                    "linecolor": axis_color,
                    "zerolinecolor": grid_color,
                },
                height=400,
                margin={"l": 20, "r": 20, "t": 55, "b": 20},
                paper_bgcolor=bg_card,
                plot_bgcolor=bg_plot,
                font={"color": text_color},
            )
            st.plotly_chart(fig_dist, width="stretch", theme=None)

        with tab_breakdown:
            fig_cost = go.Figure()
            fig_cost.add_trace(go.Bar(
                x=[f"P={item.p_value}" for item in feasible],
                y=[item.result.fixed_cost for item in feasible],
                name="Fixed Store Cost",
                marker_color=frontier_color,
            ))
            fig_cost.add_trace(go.Bar(
                x=[f"P={item.p_value}" for item in feasible],
                y=[item.result.transport_cost for item in feasible],
                name="Transport Delivery Cost",
                marker_color=profit_color,
            ))
            fig_cost.update_layout(
                template=template,
                barmode="stack",
                title={"text": "Cost Breakdown by Facility Limit (P)", "font": {"color": text_color, "size": 15}},
                xaxis={
                    "title": {"text": "Facility Limit Scenario", "font": {"color": text_color, "size": 13}},
                    "tickfont": {"color": sub_text_color, "size": 11},
                    "gridcolor": grid_color,
                    "linecolor": axis_color,
                    "zerolinecolor": grid_color,
                },
                yaxis={
                    "title": {"text": "Daily Cost (₹/day)", "font": {"color": text_color, "size": 13}},
                    "tickfont": {"color": sub_text_color, "size": 11},
                    "gridcolor": grid_color,
                    "linecolor": axis_color,
                    "zerolinecolor": grid_color,
                },
                height=400,
                margin={"l": 20, "r": 20, "t": 55, "b": 20},
                paper_bgcolor=bg_card,
                plot_bgcolor=bg_plot,
                font={"color": text_color},
                legend={"font": {"color": text_color}},
            )
            st.plotly_chart(fig_cost, width="stretch", theme=None)

    st.subheader("Scenario Summary Table")
    _render_scenario_table(sensitivity_results, pareto_p_set if feasible else set(), is_dark=is_dark)


def _render_saved_results(is_dark=False):
    saved = st.session_state.get("dark_store_run")
    if not saved:
        return
    customers = saved["customers"]
    stores = saved["stores"]
    workflow = saved["workflow"]
    distance_mode = saved["distance_mode"]
    result = saved.get("result")
    sensitivity_results = saved.get("sensitivity_results")

    st.divider()
    st.subheader("Results")
    if workflow == "Sensitivity analysis":
        _render_sensitivity_plot(sensitivity_results, is_dark=is_dark)
        feasible = [item for item in sensitivity_results if item.result.status in ("OPTIMAL", "FEASIBLE_LIMIT")]
        if feasible:
            selected_p = st.selectbox(
                "Map scenario",
                [item.p_value for item in feasible],
                format_func=lambda value: f"P = {value}",
            )
            result = next(item.result for item in feasible if item.p_value == selected_p)
    if result:
        if result.status in ("OPTIMAL", "FEASIBLE_LIMIT"):
            tone = st.success if result.status == "OPTIMAL" else st.warning
            tone(f"{result.status}: {result.message} Solver: {result.solver_name or 'N/A'}; elapsed: {result.elapsed_seconds or 0:.2f}s.")
            _display_kpis(result)
            _assignment_download(result)
            if result.relative_gap is not None:
                st.caption(f"Relative optimality gap: {100 * result.relative_gap:.2f}%")
        elif result.status == "INFEASIBLE":
            st.error(f"INFEASIBLE: {result.message}")
            if result.unserviceable_customer_ids:
                st.caption(f"Unserviceable customer IDs: {', '.join(map(str, result.unserviceable_customer_ids[:25]))}")
        else:
            st.error(f"{result.status}: {result.message}")

    mode_label = "Straight-line" if distance_mode == "Straight-line" else "Road distance"
    max_distance = saved["max_distance_km"]
    bounds = saved["bounds"]
    open_ids = result.open_store_ids if result and result.status in ("OPTIMAL", "FEASIBLE_LIMIT") else []
    choices = [store["store_id"] for store in stores]

    # Handle map clicks immediately before reading selected_store_id
    map_state = st.session_state.get("dark_store_map")
    if isinstance(map_state, dict):
        clicked = map_state.get("last_object_clicked")
        if clicked:
            click_sig = (round(clicked.get("lat", 0), 4), round(clicked.get("lng", 0), 4))
            if click_sig != st.session_state.get("_last_handled_click_sig"):
                st.session_state["_last_handled_click_sig"] = click_sig
                clicked_store = _nearest_store_id(clicked, stores, max_dist_km=2.0)
                if clicked_store and clicked_store in choices:
                    st.session_state["selected_store_id"] = clicked_store

    selected_default = st.session_state.get("selected_store_id")
    if selected_default not in choices:
        selected_default = choices[0]

    col_sel, col_hud = st.columns([1, 2])
    with col_sel:
        selected_store_id = st.selectbox(
            "Select a store to inspect its area",
            choices,
            index=choices.index(selected_default),
        )
        st.session_state["selected_store_id"] = selected_store_id
        st.session_state.setdefault("lock_view_store", True)
        lock_view = st.checkbox(
            "🎯 Center view on selected store",
            key="lock_view_store",
            help="Automatically locks and centers the map camera onto the currently inspected dark store.",
        )

    with col_hud:
        sel_store = next((s for s in stores if s["store_id"] == selected_store_id), None)
        assigned_load, utilization = _store_summary(result)
        is_sel_open = selected_store_id in open_ids
        if sel_store:
            load = assigned_load.get(selected_store_id, 0)
            cap = sel_store["capacity"]
            util_pct = round(100 * utilization.get(selected_store_id, 0.0), 1)
            status_text = "🟢 Open Dark Store" if is_sel_open else "⚪ Candidate Store (Inactive)"
            status_color = "#10b981" if is_sel_open else ("#94a3b8" if is_dark else "#64748b")
            card_bg = "#151c2c" if is_dark else "#f8fafc"
            card_border = "#26334d" if is_dark else "#cbd5e1"
            if is_sel_open:
                hud_html = (
                    f"<div style='background:{card_bg};border:1px solid {card_border};border-radius:8px;padding:10px 14px;margin-top:4px;'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;'>"
                    f"<span style='font-weight:700;font-size:13.5px;color:{status_color};'>{status_text} &mdash; <b>{selected_store_id}</b></span>"
                    f"<span style='font-size:12px;color:{'#94a3b8' if is_dark else '#475569'};'>Fixed Lease: <b>₹{sel_store['fixed_cost']:,.0f}/day</b></span>"
                    f"</div>"
                    f"<div style='display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px;color:{'#e2e8f0' if is_dark else '#334155'};'>"
                    f"<span>Capacity: <b>{cap:,.0f} orders/d</b></span>"
                    f"<span>Assigned: <b>{load:,.0f} orders/d</b></span>"
                    f"<span>Utilization: <b style='color:{status_color};'>{util_pct}%</b></span>"
                    f"</div>"
                    f"<div style='background:{'#334155' if is_dark else '#e2e8f0'};border-radius:4px;height:7px;overflow:hidden;'>"
                    f"<div style='background:#10b981;width:{min(util_pct, 100)}%;height:100%;'></div>"
                    f"</div>"
                    f"</div>"
                )
            else:
                hud_html = (
                    f"<div style='background:{card_bg};border:1px solid {card_border};border-radius:8px;padding:10px 14px;margin-top:4px;'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;'>"
                    f"<span style='font-weight:700;font-size:13.5px;color:{status_color};'>{status_text} &mdash; <b>{selected_store_id}</b></span>"
                    f"<span style='font-size:12px;color:{'#94a3b8' if is_dark else '#475569'};'>Fixed Lease: <b>₹{sel_store['fixed_cost']:,.0f}/day</b></span>"
                    f"</div>"
                    f"<div style='display:flex;justify-content:space-between;font-size:12px;color:{'#94a3b8' if is_dark else '#64748b'};'>"
                    f"<span>Max Capacity: <b>{cap:,.0f} orders/d</b></span>"
                    f"<span>Status: <i>Inactive candidate (0 orders assigned)</i></span>"
                    f"</div>"
                    f"</div>"
                )
            st.markdown(hud_html, unsafe_allow_html=True)

    _render_store_directory(stores, result, selected_store_id, is_dark=is_dark, key_prefix="main_dir")

    isochrone = None
    isochrone_message = None
    if mode_label == "Road distance":
        cache = st.session_state.setdefault("isochrones", {})
        isochrone = cache.get((selected_store_id, max_distance))
        if isochrone is None:
            if st.button("Load road reachable area", key=f"load_isochrone_{selected_store_id}"):
                client = saved.get("routing_client")
                if client is None:
                    isochrone_message = "Configure an OpenRouteService key to request road reachable areas."
                else:
                    with st.spinner("Requesting road reachable-area polygon..."):
                        response = client.fetch_isochrone(
                            next(store for store in stores if store["store_id"] == selected_store_id),
                            max_distance,
                        )
                    if response.status == "OPTIMAL":
                        cache[(selected_store_id, max_distance)] = response.geojson
                        st.rerun()
                    else:
                        isochrone_message = f"{response.status}: {response.message}"
                        if response.status in ("API_LIMIT_REACHED", "API_ERROR", "INVALID_CREDENTIALS"):
                            isochrone_message += " (If quota was reached, generate a free personal key at openrouteservice.org/dev/#/signup and paste it in the sidebar)."
        if isochrone_message:
            st.warning(isochrone_message)
        st.caption("Road distance matrix controls assignment. The selected-store isochrone is a visual reachable-area layer.")

    show_heatmap = st.checkbox("Customer heatmap", value=True)
    heatmap_metric = st.radio("Heat intensity", ("Orders per day", "Customer count"), horizontal=True) if show_heatmap else "Orders per day"
    show_customers = st.checkbox("Customer markers", value=len(customers) <= 250)
    if show_customers and len(customers) > 500:
        st.caption("Displaying first 500 customer markers for responsiveness. The heatmap visualizes aggregate customer density.")
    show_clusters = st.checkbox("Demand cluster outlines", value=False)
    show_assignments = st.checkbox("Assignments to selected store", value=False)
    collapse_map_menu = st.checkbox(
        "Minimize map layers menu",
        value=True,
        help="Collapses the map layer control into a compact icon in the top right to keep the map clean. Hover or click the icon to expand layer options.",
    )
    map_object = _build_map(
        customers,
        stores,
        result,
        bounds=bounds,
        max_distance_km=max_distance,
        distance_mode=mode_label,
        selected_store_id=selected_store_id,
        show_heatmap=show_heatmap,
        heatmap_metric=heatmap_metric,
        show_customers=show_customers,
        show_cluster_outlines=show_clusters,
        show_assignments=show_assignments,
        isochrone_geojson=isochrone,
        is_dark=is_dark,
        collapse_layers=collapse_map_menu,
        center_on_store=lock_view,
    )
    st_folium(
        map_object,
        height=640,
        width="stretch",
        returned_objects=["last_object_clicked"],
        key="dark_store_map",
    )

    if distance_mode == "Road distance":
        st.caption("Road coverage areas are requested for the selected store. Customers with no eligible route are marked; a full road-network uncovered-area polygon is not computed.")
    elif result and result.status == "INFEASIBLE" and not result.unserviceable_customer_ids:
        st.caption("This infeasibility is caused by capacity or the facility limit, not by a geographic coverage gap.")

    _render_concept_index()


def _render_concept_index():
    st.divider()
    with st.expander("Metric & Concept Index — Formulas, Definitions & Methodology (Click to expand)", expanded=False):
        st.markdown(
            """
            ### Dark Store Network Optimization Index & Reference Guide
            *Hover over any metric card or chart element above for quick tooltips, or refer to this index for detailed mathematical formulas, trade-off explanations, and business definitions.*
            """
        )
        idx_tab1, idx_tab2, idx_tab3, idx_tab4 = st.tabs([
            "Pareto Frontier & Trade-Offs",
            "Financial & Operational KPIs",
            "Optimization Model & Constraints",
            "Distance Modes & Statuses",
        ])

        with idx_tab1:
            st.markdown(
                """
                #### The Pareto Efficient Frontier in Facility Location
                In logistics and dark store planning, decision makers face an inevitable trade-off between **Fixed Facility Overhead** and **Customer Delivery Speed/Cost**:

                - **Fewer Open Stores ($P$ is small)**:
                  - Minimizes total fixed lease, maintenance, and baseline staffing expenses.
                  - Forces couriers to travel longer distances to reach customers, driving up per-order transport costs and delivery times.
                - **More Open Stores ($P$ is large)**:
                  - Places fulfillment nodes much closer to customer clusters, slashing transport costs and delivery radius.
                  - Incurs substantial fixed operating expenses for every additional store opened.

                ---

                #### Key Concepts
                - **Pareto-Optimal / Non-Dominated Configuration (Frontier)**:
                  A solution where **no alternative network setup exists that achieves lower transport cost without requiring higher fixed store investment**. These points form the efficient frontier curve.
                - **Dominated Configuration**:
                  A setup that is mathematically inferior because another configuration achieves equal or lower delivery distance at equal or lower fixed cost.
                - **The Diminishing Returns "Elbow Point"**:
                  Moving from 1 to 4 dark stores typically delivers dramatic reductions in customer transit distance. Beyond the elbow point, each additional store yields only marginal distance improvements while incurring full fixed lease costs, causing net profit to decline.
                - **Optimal Store Limit ($P^*$)**:
                  The specific facility ceiling that maximizes **Net Daily Profit** by perfectly balancing the marginal transport savings against marginal fixed store costs.
                """
            )

        with idx_tab2:
            st.markdown(
                """
                #### Financial & Operational Metric Definitions

                | Metric | Formula / Mathematical Definition | Business Interpretation |
                | :--- | :--- | :--- |
                | **Daily Profit** | $\\text{Daily Revenue} - \\text{Total Cost}$ | Net operating contribution generated per day from fulfilling all customer orders. |
                | **Total Cost (Objective)** | $\\text{Fixed Cost} + \\text{Transport Cost}$ | The primary cost function minimized by the OR-Tools MIP solver. |
                | **Daily Revenue** | $\\sum_{i} \\text{demand}_i \\times \\text{RevenuePerOrder}$ | Constant across all feasible solutions since 100% of demand must be satisfied. |
                | **Fixed Store Cost** | $\\sum_{j \\in \\text{Open}} \\text{fixed\\_cost}_j$ | Sum of daily facility rental, licensing, utilities, and core staffing for open dark stores. |
                | **Transport Cost** | $\\sum_{i} \\sum_{j} (\\text{Rate} \\times d_{ij} \\times \\text{demand}_i \\times x_{ij})$ | Variable logistics cost for dispatching orders from assigned dark stores to customers. |
                | **Demand-Weighted Avg Distance** | $\\frac{\\sum_{i} (\\text{demand}_i \\times d_{i, \\text{store}(i)})}{\\sum_i \\text{demand}_i}$ | True average travel distance per customer order. Direct proxy for delivery SLA (e.g. 10-15 minute delivery feasibility). |
                | **Store Capacity Utilization** | $\\frac{\\sum_{i \\to j} \\text{demand}_i}{\\text{capacity}_j} \\times 100\\%$ | Order throughput load relative to the facility's maximum daily handling capacity. |
                """
            )

        with idx_tab3:
            st.markdown(
                """
                #### Mixed-Integer Linear Programming (MIP) Formulation

                The application solves a **Capacitated Facility Location Problem (CFLP)** formulated in Google OR-Tools:

                $$\\min_{y, x} \\quad \\sum_{j \\in S} \\text{FixedCost}_j \\cdot y_j + \\sum_{i \\in C} \\sum_{j \\in S} \\text{Rate} \\cdot d_{ij} \\cdot \\text{demand}_i \\cdot x_{ij}$$

                **Variables:**
                - $y_j \\in \\{0, 1\\}$: Binary variable equal to 1 if candidate dark store $j$ is opened, 0 otherwise.
                - $x_{ij} \\in \\{0, 1\\}$: Binary assignment variable equal to 1 if customer $i$'s entire demand is served by store $j$.

                **Constraints Enforced:**
                1. **Single-Assignment (No Split Orders)**: Each customer's daily demand is assigned to exactly one open store: $\\sum_{j \\in S} x_{ij} = 1 \\quad \\forall i \\in C$.
                2. **Store Capacity Ceiling**: Total assigned orders cannot exceed facility capacity: $\\sum_{i \\in C} \\text{demand}_i \\cdot x_{ij} \\le \\text{capacity}_j \\cdot y_j \\quad \\forall j \\in S$.
                3. **Maximum Service Distance Limit**: If distance $d_{ij} > \\text{MaxDistance}$, the assignment arc is pruned: $x_{ij} = 0$.
                4. **Facility Limit ($P$)**: When configured, restricts the maximum number of active stores: $\\sum_{j \\in S} y_j \\le P$.
                5. **LP Tightening Cuts**: A valid inequality lower bound ($\\sum y_j \\ge \\text{min\\_stores}$) forces the solver to recognize minimum facility requirements upfront.
                """
            )

        with idx_tab4:
            st.markdown(
                """
                #### Distance Modes & API Architecture
                - **Straight-Line Mode (Haversine)**:
                  - Computes spherical great-circle distances directly on the WGS-84 ellipsoid:
                    $$d = 2R \\arcsin \\sqrt{\\sin^2\\left(\\frac{\\Delta \\phi}{2}\\right) + \\cos \\phi_1 \\cos \\phi_2 \\sin^2\\left(\\frac{\\Delta \\lambda}{2}\\right)}$$
                  - **100% offline, zero latency, and requires NO API key**.
                  - Store service areas are displayed as exact geometric radius circles.
                - **Road Distance Mode (OpenRouteService)**:
                  - Queries real-world street network driving graphs, accounting for one-way streets, bridges, and waterways.
                  - Displays true reachable street polygons (isochrones).
                  - Requires a free OpenRouteService API key because external network requests are made to their routing servers.

                #### Solver Status Dictionary
                - `OPTIMAL`: The solver proved mathematical global optimality within the 0.1% tolerance gap.
                - `FEASIBLE_LIMIT`: A valid feasible solution was found that fulfills 100% of customer orders, but the time limit expired before mathematical optimality could be formally proved.
                - `TIME_LIMIT_NO_SOLUTION`: The solver time limit was reached before discovering any valid feasible assignment.
                - `INFEASIBLE`: The problem cannot be solved under the given constraints (e.g. aggregate customer demand exceeds total candidate store capacity, or some customers are farther than the maximum service distance from all candidate stores).
                """
            )


def run_app():
    st.set_page_config(page_title="Chennai Dark Store Optimizer", layout="wide")

    theme = st.sidebar.radio("Theme", ("Dark", "Light"), index=0, horizontal=True)
    is_dark = (theme == "Dark")

    if is_dark:
        theme_css = """
        :root {
            --ink: #f1f5f9;
            --muted: #94a3b8;
            --paper: #0b0f19;
            --card-bg: #151c2c;
            --card-border: #26334d;
            --teal: #14b8a6;
            --coral: #f97316;
            --border: #26334d;
        }
        .stApp {
            background-color: #0b0f19 !important;
            color: #f1f5f9 !important;
        }
        header[data-testid="stHeader"] {
            background-color: #0b0f19 !important;
            color: #f1f5f9 !important;
        }
        header[data-testid="stHeader"] * {
            color: #f1f5f9 !important;
        }
        section[data-testid="stSidebar"] {
            background-color: #0d1322 !important;
            border-right: 1px solid #1e293b !important;
        }
        [data-testid="stMetric"] {
            background: #151c2c !important;
            border: 1px solid #26334d !important;
            padding: 16px 18px;
            border-radius: 8px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.3) !important;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        [data-testid="stMetric"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(20, 184, 166, 0.15) !important;
        }
        h1, h2, h3, h4, h5, h6 {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-weight: 700;
            color: #f8fafc !important;
        }
        p, span, label, div {
            color: #cbd5e1;
        }

        /* Dark Mode: Textboxes, Number Inputs, and Text Areas */
        div[data-baseweb="input"],
        div[data-baseweb="base-input"],
        div[data-testid="stNumberInputContainer"],
        div[data-testid="stTextInput"] > div > div,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextInput"] input,
        input[type="text"],
        input[type="number"],
        input[type="password"],
        textarea {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
            border-color: #26334d !important;
            -webkit-text-fill-color: #f1f5f9 !important;
        }
        input:focus, textarea:focus {
            border-color: #14b8a6 !important;
            box-shadow: 0 0 0 1px #14b8a6 !important;
        }

        /* Dark Mode: Number input stepper buttons (+ / -) */
        button[data-testid="stNumberInputStepDown"],
        button[data-testid="stNumberInputStepUp"],
        div[data-testid="stNumberInputStepDown"],
        div[data-testid="stNumberInputStepUp"],
        div[data-testid="stNumberInput"] button {
            background-color: #1c253b !important;
            color: #f1f5f9 !important;
            border-color: #26334d !important;
        }
        button[data-testid="stNumberInputStepDown"]:hover,
        button[data-testid="stNumberInputStepUp"]:hover,
        div[data-testid="stNumberInput"] button:hover {
            background-color: #26334d !important;
            color: #14b8a6 !important;
        }
        button[data-testid="stNumberInputStepDown"] svg,
        button[data-testid="stNumberInputStepUp"] svg,
        div[data-testid="stNumberInput"] button svg {
            fill: #f1f5f9 !important;
            color: #f1f5f9 !important;
        }

        /* Dark Mode: Clickboxes — Selectboxes & Dropdowns */
        div[data-baseweb="select"],
        div[data-baseweb="select"] > div,
        div[data-testid="stSelectbox"] > div > div {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
            border-color: #26334d !important;
        }
        div[data-baseweb="select"] * {
            color: #f1f5f9 !important;
            fill: #f1f5f9 !important;
        }
        div[data-baseweb="popover"],
        ul[data-baseweb="menu"],
        li[data-baseweb="menu-item"],
        div[role="listbox"] {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
            border-color: #26334d !important;
        }
        li[data-baseweb="menu-item"]:hover,
        div[role="option"]:hover {
            background-color: #1c253b !important;
            color: #14b8a6 !important;
        }

        /* Dark Mode: Clickboxes — Checkboxes */
        div[data-testid="stCheckbox"] label span {
            color: #cbd5e1 !important;
        }
        div[data-baseweb="checkbox"] > div:first-child,
        div[data-testid="stCheckbox"] span[data-checked] {
            background-color: #151c2c !important;
            border: 2px solid #475569 !important;
        }
        div[data-baseweb="checkbox"] [aria-checked="true"] + div,
        div[data-baseweb="checkbox"] input:checked + div {
            background-color: #14b8a6 !important;
            border-color: #14b8a6 !important;
        }
        div[data-baseweb="checkbox"] svg {
            color: #0b0f19 !important;
            fill: #0b0f19 !important;
        }

        /* Dark Mode: Clickboxes — Radio Buttons */
        div[data-testid="stRadio"] label span {
            color: #cbd5e1 !important;
        }
        div[data-baseweb="radio"] div {
            background-color: #151c2c !important;
            border-color: #475569 !important;
        }
        div[data-baseweb="radio"] input:not(:checked) + div {
            background-color: #151c2c !important;
            border: 2px solid #475569 !important;
        }
        div[data-baseweb="radio"] input:not(:checked) + div * {
            background-color: transparent !important;
        }
        div[data-baseweb="radio"] input:checked + div {
            border: 2px solid #14b8a6 !important;
            background-color: #151c2c !important;
        }
        div[data-baseweb="radio"] input:checked + div > div {
            background-color: #14b8a6 !important;
        }

        /* Dark Mode: Secondary Buttons and Download Buttons */
        button[kind="secondary"],
        div[data-testid="stButton"] button:not([kind="primary"]),
        div[data-testid="stDownloadButton"] button {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
            border: 1px solid #26334d !important;
            font-weight: 600 !important;
        }
        button[kind="secondary"]:hover,
        div[data-testid="stButton"] button:not([kind="primary"]):hover,
        div[data-testid="stDownloadButton"] button:hover {
            background-color: #1c253b !important;
            border-color: #14b8a6 !important;
            color: #14b8a6 !important;
        }

        /* Dark Mode: Primary Action Buttons */
        button[kind="primary"],
        div[data-testid="stButton"] button[kind="primary"] {
            background-color: #14b8a6 !important;
            color: #0b0f19 !important;
            border: 1px solid #14b8a6 !important;
            font-weight: 700 !important;
        }
        button[kind="primary"]:hover,
        div[data-testid="stButton"] button[kind="primary"]:hover {
            background-color: #0d9488 !important;
            border-color: #0d9488 !important;
        }

        /* Dark Mode: File Uploader */
        section[data-testid="stFileUploaderDropzone"] {
            background-color: #151c2c !important;
            border: 1px dashed #334155 !important;
            color: #cbd5e1 !important;
        }
        section[data-testid="stFileUploaderDropzone"]:hover {
            border-color: #14b8a6 !important;
        }
        section[data-testid="stFileUploaderDropzone"] * {
            color: #cbd5e1 !important;
        }
        section[data-testid="stFileUploaderDropzone"] button {
            background-color: #1c253b !important;
            color: #f1f5f9 !important;
            border-color: #26334d !important;
        }

        /* Dark Mode: Expanders */
        details[data-testid="stExpander"],
        div[data-testid="stExpander"],
        details,
        .stExpander {
            border: 1px solid #26334d !important;
            border-radius: 8px !important;
            background-color: #151c2c !important;
        }
        details summary,
        details summary:hover,
        details summary:focus,
        details summary > div,
        summary[data-testid="stExpanderToggle"],
        summary[data-testid="stExpanderToggle"]:hover,
        summary[data-testid="stExpanderToggle"] > div,
        .stExpander summary,
        .stExpander summary * {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
        }
        details summary svg,
        summary[data-testid="stExpanderToggle"] svg {
            fill: #f1f5f9 !important;
        }
        details > div,
        details[data-testid="stExpander"] > div {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
        }

        /* Dark Mode: Tabs */
        div[data-testid="stTabs"] button[role="tab"] {
            color: #94a3b8 !important;
        }
        div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            color: #14b8a6 !important;
            border-bottom-color: #14b8a6 !important;
        }

        /* Dark Mode: Alerts */
        div[data-testid="stAlert"] {
            background-color: #151c2c !important;
            border: 1px solid #26334d !important;
            color: #f1f5f9 !important;
        }

        /* Dark Mode: Inline Code */
        code, .stMarkdown code, p code, span code, li code {
            background-color: #1e253b !important;
            color: #14b8a6 !important;
            border: 1px solid #334155 !important;
            padding: 2px 6px !important;
            border-radius: 4px !important;
            font-weight: 600 !important;
        }
        pre, pre code {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
            border: 1px solid #26334d !important;
        }

        /* Dark Mode: Tables and DataFrames */
        div[data-testid="stDataFrame"],
        div[data-testid="stTable"],
        div[data-testid="stTable"] table {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
        }
        div[data-testid="stTable"] th {
            background-color: #1c253b !important;
            color: #f1f5f9 !important;
            border-bottom: 2px solid #26334d !important;
        }
        div[data-testid="stTable"] td {
            background-color: #151c2c !important;
            color: #cbd5e1 !important;
            border-bottom: 1px solid #26334d !important;
        }

        /* Dark Mode: Question mark / tooltip help icons */
        div[data-testid="stTooltipIcon"] svg,
        div[data-testid="stTooltipHoverTarget"] svg,
        button[data-testid="stTooltipHoverTarget"] svg,
        .stTooltipIcon svg {
            display: none !important;
        }
        button[data-testid="stTooltipHoverTarget"],
        div[data-testid="stTooltipHoverTarget"],
        div[data-testid="stTooltipIcon"] button,
        .stTooltipIcon button {
            background: transparent !important;
            background-color: transparent !important;
            border: none !important;
            padding: 0 !important;
            margin: 0 0 0 4px !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            vertical-align: middle !important;
            cursor: pointer !important;
        }
        button[data-testid="stTooltipHoverTarget"]::after,
        div[data-testid="stTooltipHoverTarget"]::after,
        div[data-testid="stTooltipIcon"] button::after,
        .stTooltipIcon button::after {
            content: "?" !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 17px !important;
            height: 17px !important;
            border-radius: 50% !important;
            font-size: 11px !important;
            font-weight: 700 !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
            line-height: 1 !important;
            text-align: center !important;
            border: 1.5px solid #94a3b8 !important;
            color: #cbd5e1 !important;
            background-color: #1e253b !important;
            transition: all 0.15s ease !important;
        }
        button[data-testid="stTooltipHoverTarget"]:hover::after,
        div[data-testid="stTooltipHoverTarget"]:hover::after,
        div[data-testid="stTooltipIcon"] button:hover::after,
        .stTooltipIcon button:hover::after {
            border-color: #14b8a6 !important;
            color: #14b8a6 !important;
            background-color: #0f2d3a !important;
            transform: scale(1.12) !important;
        }
        div[data-baseweb="popover"],
        div[data-testid="stTooltipContent"],
        div[role="tooltip"] {
            background-color: #151c2c !important;
            color: #f1f5f9 !important;
            border: 1px solid #26334d !important;
            border-radius: 8px !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4) !important;
        }
        div[data-baseweb="popover"] *,
        div[data-testid="stTooltipContent"] *,
        div[role="tooltip"] * {
            color: #f1f5f9 !important;
        }
        """
    else:
        theme_css = """
        :root {
            --ink: #17242a;
            --muted: #64748b;
            --paper: #f8fafc;
            --card-bg: #ffffff;
            --card-border: #e2e8f0;
            --teal: #0f7773;
            --coral: #e16d52;
            --border: #e2e8f0;
        }
        .stApp {
            background-color: #f8fafc !important;
            color: #0f172a !important;
        }
        header[data-testid="stHeader"] {
            background-color: #f8fafc !important;
            color: #0f172a !important;
        }
        header[data-testid="stHeader"] * {
            color: #0f172a !important;
        }
        section[data-testid="stSidebar"] {
            background-color: #ffffff !important;
            border-right: 1px solid #e2e8f0 !important;
        }
        [data-testid="stMetric"] {
            background: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            padding: 16px 18px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        [data-testid="stMetric"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(15, 119, 115, 0.1) !important;
        }
        [data-testid="stMetricLabel"],
        [data-testid="stMetricLabel"] * {
            color: #475569 !important;
        }
        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] * {
            color: #0f172a !important;
        }
        [data-testid="stMetricDelta"],
        [data-testid="stMetricDelta"] * {
            color: #0f7773 !important;
        }
        h1, h2, h3, h4, h5, h6 {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-weight: 700;
            color: #0f172a !important;
        }
        p, span, label, div {
            color: #1e293b;
        }

        /* Light Mode: Textboxes, Number Inputs, and Text Areas */
        div[data-baseweb="input"],
        div[data-baseweb="base-input"],
        div[data-testid="stNumberInputContainer"],
        div[data-testid="stTextInput"] > div > div,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextInput"] input,
        input[type="text"],
        input[type="number"],
        input[type="password"],
        textarea {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border-color: #cbd5e1 !important;
            -webkit-text-fill-color: #0f172a !important;
        }
        input:focus, textarea:focus {
            border-color: #0f7773 !important;
            box-shadow: 0 0 0 1px #0f7773 !important;
        }

        /* Light Mode: Number input stepper buttons (+ / -) */
        button[data-testid="stNumberInputStepDown"],
        button[data-testid="stNumberInputStepUp"],
        div[data-testid="stNumberInputStepDown"],
        div[data-testid="stNumberInputStepUp"],
        div[data-testid="stNumberInput"] button {
            background-color: #f8fafc !important;
            color: #0f172a !important;
            border-color: #cbd5e1 !important;
        }
        button[data-testid="stNumberInputStepDown"]:hover,
        button[data-testid="stNumberInputStepUp"]:hover,
        div[data-testid="stNumberInput"] button:hover {
            background-color: #e2e8f0 !important;
            color: #0f7773 !important;
        }
        button[data-testid="stNumberInputStepDown"] svg,
        button[data-testid="stNumberInputStepUp"] svg,
        div[data-testid="stNumberInput"] button svg {
            fill: #475569 !important;
            color: #475569 !important;
        }

        /* Light Mode: Clickboxes — Selectboxes & Dropdowns */
        div[data-baseweb="select"],
        div[data-baseweb="select"] > div,
        div[data-testid="stSelectbox"] > div > div {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border-color: #cbd5e1 !important;
        }
        div[data-baseweb="select"] * {
            color: #0f172a !important;
        }
        div[data-baseweb="popover"],
        ul[data-baseweb="menu"],
        li[data-baseweb="menu-item"],
        div[role="listbox"] {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
        }
        li[data-baseweb="menu-item"]:hover,
        div[role="option"]:hover,
        li[data-baseweb="menu-item"][aria-selected="true"] {
            background-color: #f1f5f9 !important;
            color: #0f7773 !important;
        }

        /* Light Mode: Clickboxes — Checkboxes */
        div[data-testid="stCheckbox"] label span {
            color: #1e293b !important;
        }
        div[data-baseweb="checkbox"] > div:first-child,
        div[data-testid="stCheckbox"] span[data-checked] {
            background-color: #ffffff !important;
            border: 2px solid #94a3b8 !important;
        }
        div[data-baseweb="checkbox"] [aria-checked="true"] + div,
        div[data-baseweb="checkbox"] input:checked + div {
            background-color: #0f7773 !important;
            border-color: #0f7773 !important;
        }
        div[data-baseweb="checkbox"] svg {
            color: #ffffff !important;
            fill: #ffffff !important;
        }

        /* Light Mode: Clickboxes — Radio Buttons */
        div[data-testid="stRadio"] label span {
            color: #1e293b !important;
        }
        div[data-baseweb="radio"] > div {
            background-color: #ffffff !important;
            border: 2px solid #94a3b8 !important;
        }
        div[data-baseweb="radio"] input:not(:checked) + div {
            background-color: #ffffff !important;
            border: 2px solid #94a3b8 !important;
        }
        div[data-baseweb="radio"] input:not(:checked) + div * {
            background-color: transparent !important;
        }
        div[data-baseweb="radio"] input:checked + div {
            border: 2px solid #0f7773 !important;
            background-color: #ffffff !important;
        }
        div[data-baseweb="radio"] input:checked + div > div {
            background-color: #0f7773 !important;
        }

        /* Light Mode: Secondary Buttons and Download Buttons */
        button[kind="secondary"],
        div[data-testid="stButton"] button:not([kind="primary"]),
        div[data-testid="stDownloadButton"] button {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
            font-weight: 600 !important;
        }
        button[kind="secondary"]:hover,
        div[data-testid="stButton"] button:not([kind="primary"]):hover,
        div[data-testid="stDownloadButton"] button:hover {
            background-color: #f1f5f9 !important;
            border-color: #0f7773 !important;
            color: #0f7773 !important;
        }

        /* Light Mode: Primary Action Buttons */
        button[kind="primary"],
        div[data-testid="stButton"] button[kind="primary"] {
            background-color: #0f7773 !important;
            color: #ffffff !important;
            border: 1px solid #0f7773 !important;
            font-weight: 700 !important;
        }
        button[kind="primary"]:hover,
        div[data-testid="stButton"] button[kind="primary"]:hover {
            background-color: #0d6562 !important;
            border-color: #0d6562 !important;
        }

        /* Light Mode: File Uploader */
        section[data-testid="stFileUploaderDropzone"] {
            background-color: #ffffff !important;
            border: 1px dashed #cbd5e1 !important;
            color: #475569 !important;
        }
        section[data-testid="stFileUploaderDropzone"]:hover {
            border-color: #0f7773 !important;
            background-color: #f8fafc !important;
        }
        section[data-testid="stFileUploaderDropzone"] * {
            color: #475569 !important;
        }
        section[data-testid="stFileUploaderDropzone"] button {
            background-color: #f1f5f9 !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
        }

        /* Light Mode: Expanders */
        details[data-testid="stExpander"],
        div[data-testid="stExpander"],
        .stExpander {
            border: 1px solid #e2e8f0 !important;
            border-radius: 8px !important;
            background-color: #ffffff !important;
        }
        summary[data-testid="stExpanderToggle"] {
            background-color: #ffffff !important;
            color: #0f172a !important;
        }
        summary[data-testid="stExpanderToggle"]:hover {
            color: #0f7773 !important;
            background-color: #f8fafc !important;
        }
        summary[data-testid="stExpanderToggle"] svg {
            fill: #0f172a !important;
        }
        details[data-testid="stExpander"] > div {
            background-color: #ffffff !important;
            color: #0f172a !important;
        }

        /* Light Mode: Tabs */
        div[data-testid="stTabs"] button[role="tab"] {
            color: #64748b !important;
        }
        div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            color: #0f7773 !important;
            border-bottom-color: #0f7773 !important;
        }

        /* Light Mode: Alerts / Callouts */
        div[data-testid="stAlert"] {
            background-color: #f0fdfa !important;
            border: 1px solid #99f6e4 !important;
            color: #134e4a !important;
            border-radius: 8px !important;
        }
        div[data-testid="stAlert"] * {
            color: #134e4a !important;
        }
        div[data-testid="stAlert"] svg {
            fill: #0f7773 !important;
            color: #0f7773 !important;
        }

        /* Light Mode: Inline Code */
        code, .stMarkdown code, p code, span code, li code {
            background-color: #e2e8f0 !important;
            color: #0f7773 !important;
            border: 1px solid #cbd5e1 !important;
            padding: 2px 6px !important;
            border-radius: 4px !important;
            font-weight: 600 !important;
        }
        pre, pre code {
            background-color: #f1f5f9 !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
        }

        /* Light Mode: Tables and DataFrames */
        div[data-testid="stDataFrame"],
        div[data-testid="stTable"],
        div[data-testid="stTable"] table {
            background-color: #ffffff !important;
            color: #0f172a !important;
        }
        div[data-testid="stTable"] th {
            background-color: #f8fafc !important;
            color: #0f172a !important;
            border-bottom: 2px solid #e2e8f0 !important;
        }
        div[data-testid="stTable"] td {
            background-color: #ffffff !important;
            color: #1e293b !important;
            border-bottom: 1px solid #e2e8f0 !important;
        }

        /* Light Mode: Question mark / tooltip help icons */
        div[data-testid="stTooltipIcon"] svg,
        div[data-testid="stTooltipHoverTarget"] svg,
        button[data-testid="stTooltipHoverTarget"] svg,
        .stTooltipIcon svg {
            display: none !important;
        }
        button[data-testid="stTooltipHoverTarget"],
        div[data-testid="stTooltipHoverTarget"],
        div[data-testid="stTooltipIcon"] button,
        .stTooltipIcon button {
            background: transparent !important;
            background-color: transparent !important;
            border: none !important;
            padding: 0 !important;
            margin: 0 0 0 4px !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            vertical-align: middle !important;
            cursor: pointer !important;
        }
        button[data-testid="stTooltipHoverTarget"]::after,
        div[data-testid="stTooltipHoverTarget"]::after,
        div[data-testid="stTooltipIcon"] button::after,
        .stTooltipIcon button::after {
            content: "?" !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 17px !important;
            height: 17px !important;
            border-radius: 50% !important;
            font-size: 11px !important;
            font-weight: 700 !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
            line-height: 1 !important;
            text-align: center !important;
            border: 1.5px solid #cbd5e1 !important;
            color: #475569 !important;
            background-color: #f1f5f9 !important;
            transition: all 0.15s ease !important;
        }
        button[data-testid="stTooltipHoverTarget"]:hover::after,
        div[data-testid="stTooltipHoverTarget"]:hover::after,
        div[data-testid="stTooltipIcon"] button:hover::after,
        .stTooltipIcon button:hover::after {
            border-color: #0f7773 !important;
            color: #0f7773 !important;
            background-color: #e6fffa !important;
            transform: scale(1.12) !important;
        }
        div[data-baseweb="popover"],
        div[data-testid="stTooltipContent"],
        div[role="tooltip"] {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 8px !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1) !important;
        }
        div[data-baseweb="popover"] *,
        div[data-testid="stTooltipContent"] *,
        div[role="tooltip"] * {
            color: #0f172a !important;
        }
        """

    base_css = """
        /* Hide number input spinners and avoid wheel trapping */
        input[type=number]::-webkit-inner-spin-button, 
        input[type=number]::-webkit-outer-spin-button { 
            -webkit-appearance: none; 
            margin: 0; 
        }
        input[type=number] { 
            -moz-appearance: textfield; 
        }
        /* Ensure KPI values never truncate with ... and wrap cleanly */
        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] *,
        [data-testid="stMetricDelta"],
        [data-testid="stMetricDelta"] *,
        [data-testid="stMetricLabel"],
        [data-testid="stMetricLabel"] * {
            white-space: normal !important;
            word-break: break-word !important;
            overflow: visible !important;
            text-overflow: clip !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.35rem !important;
            font-weight: 700 !important;
            line-height: 1.25 !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.88rem !important;
            font-weight: 600 !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.82rem !important;
        }
        div[data-testid="stForm"] { border: 0; padding: 0; }
    """

    st.markdown(f"<style>{theme_css}\n{base_css}</style>", unsafe_allow_html=True)

    # Inject passive wheel listener to release input focus on scroll so user is never trapped
    components.html(
        """
        <script>
        (function() {
            function attachScrollFix() {
                try {
                    const doc = window.parent.document;
                    if (!doc) return;
                    doc.addEventListener('wheel', function(e) {
                        const active = doc.activeElement;
                        if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {
                            if (active.type === 'number') {
                                active.blur();
                            }
                        }
                    }, { passive: true, capture: true });

                    const numberInputs = doc.querySelectorAll('input[type="number"]');
                    numberInputs.forEach(function(inp) {
                        if (!inp.dataset.scrollFixAttached) {
                            inp.dataset.scrollFixAttached = 'true';
                            inp.addEventListener('wheel', function(e) {
                                this.blur();
                            }, { passive: true });
                        }
                    });
                } catch (err) {}
            }
            attachScrollFix();
            setInterval(attachScrollFix, 1500);
        })();
        </script>
        """,
        height=0,
        width=0,
    )

    st.title("Chennai Dark Store Network")
    st.caption("Facility location decisions from demand, capacity, fixed cost, and service distance.")

    workflow = st.radio(
        "What would you like to run?",
        ("Optimizer run", "Sensitivity analysis"),
        horizontal=True,
        key="workflow_choice",
    )
    customer_example, store_example = EXAMPLE_FILES[workflow]
    st.sidebar.header("Inputs and assumptions")
    source = st.sidebar.radio("Data source", ("Example CSVs", "Upload CSVs", "Synthetic Chennai demo"))

    if source == "Upload CSVs":
        uploaded_customers = st.sidebar.file_uploader("Customer CSV", type=["csv"], key="customers_upload")
        uploaded_stores = st.sidebar.file_uploader("Candidate-store CSV", type=["csv"], key="stores_upload")
    else:
        uploaded_customers = uploaded_stores = None

    if source == "Synthetic Chennai demo":
        customer_count = st.sidebar.number_input("Customers", min_value=10, max_value=10000, value=500, step=100)
        store_count = st.sidebar.number_input("Candidate stores", min_value=2, max_value=50, value=20, step=1)
    elif source == "Example CSVs":
        customer_count = len(validate_customers_csv(customer_example.read_bytes(), bounds=None))
        store_count = len(validate_stores_csv(store_example.read_bytes(), bounds=None))
    else:
        customer_count = 10000
        if uploaded_customers is not None:
            try:
                customer_count = len(validate_customers_csv(uploaded_customers.getvalue(), bounds=None))
            except InputValidationError:
                pass
        store_count = 50
        if uploaded_stores is not None:
            try:
                store_count = len(validate_stores_csv(uploaded_stores.getvalue(), bounds=None))
            except InputValidationError:
                pass

    seed = st.sidebar.number_input("Demo/random seed", min_value=0, max_value=2_147_483_647, value=42, step=1)
    with st.sidebar.expander("Chennai map bounds", expanded=False):
        min_lat = st.number_input("Minimum latitude", value=float(DEFAULT_CHENNAI_BOUNDS[0]), format="%.4f")
        max_lat = st.number_input("Maximum latitude", value=float(DEFAULT_CHENNAI_BOUNDS[1]), format="%.4f")
        min_lon = st.number_input("Minimum longitude", value=float(DEFAULT_CHENNAI_BOUNDS[2]), format="%.4f")
        max_lon = st.number_input("Maximum longitude", value=float(DEFAULT_CHENNAI_BOUNDS[3]), format="%.4f")
    bounds = (min_lat, max_lat, min_lon, max_lon)

    distance_mode = st.sidebar.radio("Distance source", ("Straight-line", "Road distance"), horizontal=True)
    max_distance_km = st.sidebar.number_input("Maximum service distance (km)", min_value=0.5, max_value=50.0, value=8.0, step=0.5)
    transport_rate = st.sidebar.number_input(
        "Transport cost (₹ / order-km)",
        min_value=0.0,
        value=0.25,
        step=0.05,
        format="%.2f",
        help="Logistics delivery cost in Rupees per order-kilometer (₹/order-km). Combined with fixed store lease costs in the solver's objective function.",
    )
    revenue_per_order = st.sidebar.number_input(
        "Revenue per order (₹ / order)",
        min_value=0.0,
        value=150.0,
        step=5.0,
        format="%.2f",
        help="Average gross revenue in Rupees generated per fulfilled customer order (₹/order). Used to calculate daily revenue and net profit.",
    )
    solver_limit = st.sidebar.number_input("Solver time limit per run (seconds)", min_value=1, max_value=600, value=30, step=5)
    overall_limit = st.sidebar.number_input("Overall run budget (seconds)", min_value=1, max_value=1800, value=300, step=30)
    route_budget = st.sidebar.number_input("Maximum road matrix elements", min_value=1, max_value=500000, value=100000, step=10000)
    solver_limit = min(float(solver_limit), float(overall_limit))

    secret_key = _get_secret_key()
    if distance_mode == "Road distance":
        user_key = st.sidebar.text_input(
            "OpenRouteService API key",
            value=secret_key if secret_key else "",
            type="password",
            help=(
                "OpenRouteService API key for driving road distances.\n\n"
                "- A shared or saved key may be active by default.\n"
                "- Free tier limits: 2,500 matrix requests and 500 isochrones per day.\n"
                "- If a quota or limit error occurs, generate your own free personal key and paste it here.\n\n"
                "See the guide below for quick 2-minute setup instructions."
            ),
        )
        key = user_key.strip() if user_key else secret_key
        with st.sidebar.expander("How to obtain a free API key (2 min)", expanded=not bool(key)):
            st.markdown(
                """
                1. Visit [openrouteservice.org/dev/#/signup](https://openrouteservice.org/dev/#/signup).
                2. Sign up for a free account and verify your email.
                3. Go to the **Tokens** tab and click **Create Token** (choose **Standard Free**).
                4. Copy your token and paste it into the field above!

                *Note: Straight-line mode requires zero API keys.*
                """
            )
        if not key:
            st.sidebar.warning("No API key provided. Paste a key above or switch to 'Straight-line' mode.")
    else:
        key = secret_key

    candidate_subset_count = None
    if workflow == "Sensitivity analysis" and source == "Upload CSVs":
        candidate_subset_count = st.sidebar.checkbox("Randomly sample a candidate pool once for this analysis", value=False)
        if candidate_subset_count:
            st.sidebar.caption("The sampled pool is held fixed across all P scenarios.")
            subset_count = st.sidebar.number_input("Sampled candidate count", min_value=2, max_value=50, value=10, step=1)
        else:
            subset_count = None
    else:
        subset_count = None

    p_values = []
    exact_open_stores = False
    if workflow == "Optimizer run":
        enforce_facility_limit = st.sidebar.checkbox("Limit the number of open stores", value=False)
        max_open_stores = (
            st.sidebar.number_input("Maximum stores allowed to open (P)", min_value=1, max_value=int(store_count), value=min(5, int(store_count)), step=1)
            if enforce_facility_limit
            else None
        )
    else:
        max_open_stores = None
        preset = st.sidebar.selectbox(
            "P scenario preset",
            (
                "Complete Pareto front (all 1..N candidate counts)",
                "Original benchmark (2, 5, 10, 20, 25)",
                "Additional examples (3, 5, 7, 10)",
                "Range with step",
                "Custom selection",
            ),
        )
        if preset == "Complete Pareto front (all 1..N candidate counts)":
            p_values = list(range(1, int(store_count) + 1))
            st.sidebar.info(f"Optimizing all {len(p_values)} candidate counts (P = 1 to {int(store_count)}) to construct the complete Pareto front.")
        elif preset == "Range with step":
            col_p1, col_p2, col_p3 = st.sidebar.columns(3)
            with col_p1:
                p_start = st.number_input("Min P", min_value=1, max_value=int(store_count), value=1)
            with col_p2:
                p_end = st.number_input("Max P", min_value=int(p_start), max_value=int(store_count), value=int(store_count))
            with col_p3:
                p_step = st.number_input("Step", min_value=1, max_value=max(1, int(store_count)), value=max(1, int(store_count) // 10 or 1))
            p_values = list(range(int(p_start), int(p_end) + 1, int(p_step)))
            if int(p_end) not in p_values:
                p_values.append(int(p_end))
            p_values = sorted(set(p_values))
        elif preset == "Custom selection":
            p_values = st.sidebar.multiselect(
                "Maximum open stores (P)",
                range(1, int(store_count) + 1),
                default=[v for v in [2, 5, 10] if v <= int(store_count)] or [min(2, int(store_count))],
            )
        else:
            p_values = [value for value in P_PRESETS[preset] if value <= int(store_count)]
            st.sidebar.caption("Values above the candidate-pool size are omitted.")
        st.sidebar.caption("The same candidate pool is used for every selected P value.")
        store_constraint_mode = st.sidebar.radio(
            "Store constraint mode",
            ("Exact store count (open exactly P stores)", "Upper limit ceiling (open at most P stores)"),
            index=0,
            help=(
                "• Exact store count (open exactly P stores): Forces the solver to open exactly P stores for each scenario. "
                "Reveals the full trade-off curve across all store counts, demonstrating how each additional store decreases customer delivery distance at the expense of higher fixed rent.\n\n"
                "• Upper limit ceiling (open at most P stores): Allows the solver to open fewer than P stores if opening more is uneconomical. "
                "Once the economic profit-maximizing store count (P*) is reached, all higher limits open the same optimal number of stores."
            ),
        )
        exact_open_stores = (store_constraint_mode == "Exact store count (open exactly P stores)")

    _show_examples(workflow)
    st.caption(f"Example customer file: `{customer_example.name}` | Store file: `{store_example.name}`")

    with st.sidebar:
        run_clicked = st.button("Run optimization" if workflow == "Optimizer run" else "Run sensitivity analysis", type="primary", width="stretch")

    if run_clicked:
        try:
            customers, stores = _collect_inputs(
                workflow,
                source,
                bounds,
                int(customer_count),
                int(store_count),
                int(seed),
                uploaded_customers,
                uploaded_stores,
            )
            if candidate_subset_count:
                if int(subset_count) > len(stores):
                    raise InputValidationError(["Sampled candidate count exceeds the uploaded store pool."])
                stores = random.Random(int(seed)).sample(stores, int(subset_count))
            if not min_lat < max_lat or not min_lon < max_lon:
                raise InputValidationError(["Geographic bounds must have increasing minimum and maximum values."])
            if min_lat < -90 or max_lat > 90 or min_lon < -180 or max_lon > 180:
                raise InputValidationError(["Geographic bounds must stay within valid latitude/longitude ranges."])
            effective_limit = int(max_open_stores) if max_open_stores is not None else None
            if workflow == "Optimizer run":
                try:
                    validate_instance_capacity(customers, stores, effective_limit)
                except InputValidationError as error:
                    st.error(f"INFEASIBLE: {'; '.join(error.errors)}")
                    st.session_state.pop("dark_store_run", None)
                    st.stop()
            else:
                if not p_values:
                    raise InputValidationError(["Select at least one facility-limit scenario."])
                if any(value > len(stores) for value in p_values):
                    raise InputValidationError(["Every P scenario must be no greater than the candidate-store count."])
                try:
                    validate_instance_capacity(customers, stores)
                except InputValidationError as error:
                    st.error(f"INFEASIBLE: {'; '.join(error.errors)}")
                    st.session_state.pop("dark_store_run", None)
                    st.stop()

            routing_client = None
            distance_matrix = None
            if distance_mode == "Road distance":
                if not key:
                    st.error("INVALID_CREDENTIALS: road distance requires an OpenRouteService API key.")
                    st.stop()
                cache_key = _road_matrix_cache_key(customers, stores, max_distance_km)
                matrix_cache = st.session_state.setdefault("road_distance_matrix_cache", {})
                distance_matrix = matrix_cache.get(cache_key)
                routing_client = OpenRouteServiceClient(
                    key,
                    max_total_elements=int(route_budget),
                )
                if distance_matrix is None:
                    with st.spinner("Preparing road-distance matrix..."):
                        routing_result = routing_client.fetch_distance_matrix(customers, stores, max_distance_km)
                    if routing_result.status != "OPTIMAL":
                        st.error(f"{routing_result.status}: {routing_result.message}")
                        if routing_result.status in ("API_LIMIT_REACHED", "API_ERROR", "INVALID_CREDENTIALS"):
                            st.warning(
                                "Quota Exceeded or Key Issue: The current OpenRouteService API key has reached its usage quota or is invalid. "
                                "To continue in road mode, please generate your own free personal API key at [openrouteservice.org/dev/#/signup](https://openrouteservice.org/dev/#/signup) (free, ~2 minutes) and paste it into the sidebar field above, or switch to Straight-line mode which runs 100% offline with zero keys."
                            )
                        st.caption(f"Requested route elements: {routing_result.requested_elements:,}; requests attempted: {routing_result.request_count}")
                        st.stop()
                    distance_matrix = routing_result.distance_matrix_km
                    matrix_cache[cache_key] = distance_matrix
                    while len(matrix_cache) > 2:
                        matrix_cache.pop(next(iter(matrix_cache)))
                    st.caption(f"Road matrix ready: {routing_result.requested_elements:,} route elements across {routing_result.request_count} request(s).")
                else:
                    st.caption("Reused the cached road-distance matrix; no routing API requests were made.")

            if workflow == "Optimizer run":
                with st.spinner("Solving the facility-location model..."):
                    result = solve_location_model(
                        customers,
                        stores,
                        max_distance_km=max_distance_km,
                        transport_cost_per_order_km=transport_rate,
                        revenue_per_order=revenue_per_order,
                        max_open_stores=effective_limit,
                        time_limit_seconds=solver_limit,
                        distance_matrix_km=distance_matrix,
                    )
                st.session_state["dark_store_run"] = {
                    "workflow": workflow,
                    "customers": customers,
                    "stores": stores,
                    "result": result,
                    "sensitivity_results": None,
                    "distance_mode": distance_mode,
                    "max_distance_km": max_distance_km,
                    "bounds": bounds,
                    "routing_client": routing_client,
                }
            else:
                with st.spinner("Solving facility-limit scenarios..."):
                    scenario_results, validation_error = run_sensitivity_scenarios(
                        customers,
                        stores,
                        list(p_values),
                        max_distance_km=max_distance_km,
                        transport_cost_per_order_km=transport_rate,
                        revenue_per_order=revenue_per_order,
                        per_scenario_seconds=solver_limit,
                        total_budget_seconds=overall_limit,
                        distance_matrix_km=distance_matrix,
                        exact_open_stores=exact_open_stores,
                    )
                if validation_error:
                    st.error(f"INVALID_INPUT: {validation_error}")
                    st.stop()
                first_result = scenario_results[0].result if scenario_results else None
                st.session_state["dark_store_run"] = {
                    "workflow": workflow,
                    "customers": customers,
                    "stores": stores,
                    "result": first_result,
                    "sensitivity_results": scenario_results,
                    "distance_mode": distance_mode,
                    "max_distance_km": max_distance_km,
                    "bounds": bounds,
                    "routing_client": routing_client,
                }
            st.session_state.pop("isochrones", None)
        except InputValidationError as error:
            st.error(f"INVALID_INPUT: {'; '.join(error.errors)}")
        except (ValueError, KeyError, TypeError) as error:
            st.error(f"INVALID_INPUT: {error}")
        except Exception as error:
            st.error(f"INTERNAL_ERROR: {type(error).__name__}. Check the inputs and retry.")

    _render_saved_results(is_dark=is_dark)
    if not st.session_state.get("dark_store_run"):
        st.info("Choose a workflow, load example data or upload your own, adjust the assumptions, and run the model.")
        _render_concept_index()


if __name__ == "__main__":
    run_app()
