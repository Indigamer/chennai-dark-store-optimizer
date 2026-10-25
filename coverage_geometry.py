"""Geographic coverage-gap polygons for the Chennai map."""

import numpy as np
from pyproj import Transformer
from shapely import transform as transform_geometry
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union


_TO_METERS = Transformer.from_crs("EPSG:4326", "EPSG:32644", always_xy=True).transform
_TO_WGS84 = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True).transform


def uncovered_region_geojson(bounds, stores, radius_km):
    """Return study-area regions outside all candidate straight-line buffers.

    ``bounds`` is ``(min_lat, max_lat, min_lon, max_lon)``. The polygon is an
    approximate Haversine service-gap visualization, not a feasibility proof.
    """
    min_lat, max_lat, min_lon, max_lon = map(float, bounds)
    radius_meters = float(radius_km) * 1000
    if not min_lat < max_lat or not min_lon < max_lon or radius_meters < 0:
        raise ValueError("Coverage bounds and radius must be valid.")
    if not stores:
        return {"type": "FeatureCollection", "features": []}

    study_area = box(min_lon, min_lat, max_lon, max_lat)
    projected_study_area = transform_geometry(
        study_area,
        lambda coordinates: np.column_stack(
            _TO_METERS(coordinates[:, 0], coordinates[:, 1])
        ),
    )
    service_buffers = []
    for store in stores:
        longitude = float(store["longitude"])
        latitude = float(store["latitude"])
        x_coord, y_coord = _TO_METERS(longitude, latitude)
        service_buffers.append(Point(x_coord, y_coord).buffer(radius_meters))

    covered = unary_union(service_buffers)
    uncovered = projected_study_area.difference(covered)
    if uncovered.is_empty:
        return {"type": "FeatureCollection", "features": []}
    wgs84_geometry = transform_geometry(
        uncovered,
        lambda coordinates: np.column_stack(
            _TO_WGS84(coordinates[:, 0], coordinates[:, 1])
        ),
    )
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"layer": "uncovered_candidate_service_area"},
            "geometry": mapping(wgs84_geometry),
        }],
    }


def uncovered_road_gap_geojson(bounds, isochrones):
    """Return study-area regions outside all road isochrone polygons.

    ``bounds`` is ``(min_lat, max_lat, min_lon, max_lon)``.
    ``isochrones`` can be a FeatureCollection dict, a list of Features/geometries,
    or a single Feature/geometry dict.
    """
    min_lat, max_lat, min_lon, max_lon = map(float, bounds)
    if not min_lat < max_lat or not min_lon < max_lon:
        raise ValueError("Coverage bounds must be valid.")
    if not isochrones:
        return {"type": "FeatureCollection", "features": []}

    features = []
    if isinstance(isochrones, dict):
        if isochrones.get("type") == "FeatureCollection":
            features = isochrones.get("features", [])
        elif isochrones.get("type") == "Feature":
            features = [isochrones]
        elif "geometry" in isochrones:
            features = [isochrones]
        elif "type" in isochrones and "coordinates" in isochrones:
            features = [{"geometry": isochrones}]
    elif isinstance(isochrones, (list, tuple)):
        for item in isochrones:
            if isinstance(item, dict):
                if item.get("type") == "FeatureCollection":
                    features.extend(item.get("features", []))
                else:
                    features.append(item)

    if not features:
        return {"type": "FeatureCollection", "features": []}

    study_area = box(min_lon, min_lat, max_lon, max_lat)
    projected_study_area = transform_geometry(
        study_area,
        lambda coordinates: np.column_stack(
            _TO_METERS(coordinates[:, 0], coordinates[:, 1])
        ),
    )

    polygons = []
    for feat in features:
        geom_dict = feat.get("geometry", feat) if isinstance(feat, dict) else feat
        if not isinstance(geom_dict, dict) or "type" not in geom_dict:
            continue
        try:
            geom = shape(geom_dict)
            if not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                continue
            projected_geom = transform_geometry(
                geom,
                lambda coordinates: np.column_stack(
                    _TO_METERS(coordinates[:, 0], coordinates[:, 1])
                ),
            )
            polygons.append(projected_geom)
        except Exception:
            continue

    if not polygons:
        return {"type": "FeatureCollection", "features": []}

    covered = unary_union(polygons)
    uncovered = projected_study_area.difference(covered)
    if uncovered.is_empty:
        return {"type": "FeatureCollection", "features": []}

    wgs84_geometry = transform_geometry(
        uncovered,
        lambda coordinates: np.column_stack(
            _TO_WGS84(coordinates[:, 0], coordinates[:, 1])
        ),
    )
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"layer": "uncovered_road_service_area"},
            "geometry": mapping(wgs84_geometry),
        }],
    }