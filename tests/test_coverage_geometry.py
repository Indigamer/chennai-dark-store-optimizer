import unittest

from coverage_geometry import uncovered_region_geojson, uncovered_road_gap_geojson


class CoverageGeometryTests(unittest.TestCase):
    def test_returns_gap_geometry_when_radius_is_small(self):
        result = uncovered_region_geojson(
            (13.0, 13.1, 80.2, 80.3),
            [{"latitude": 13.05, "longitude": 80.25}],
            1,
        )
        self.assertEqual(result["type"], "FeatureCollection")
        self.assertEqual(len(result["features"]), 1)
        self.assertIn(result["features"][0]["geometry"]["type"], {"Polygon", "MultiPolygon"})

    def test_returns_no_gaps_when_buffer_covers_area(self):
        result = uncovered_region_geojson(
            (13.0, 13.01, 80.2, 80.21),
            [{"latitude": 13.005, "longitude": 80.205}],
            10,
        )
        self.assertEqual(result["features"], [])

    def test_empty_store_list_has_no_covered_polygon(self):
        result = uncovered_region_geojson((13.0, 13.1, 80.2, 80.3), [], 5)
        self.assertEqual(result["features"], [])

    def test_road_gap_returns_gap_geometry_when_isochrone_is_small(self):
        small_poly = {
            "type": "Polygon",
            "coordinates": [[[80.24, 13.04], [80.26, 13.04], [80.26, 13.06], [80.24, 13.06], [80.24, 13.04]]],
        }
        result = uncovered_road_gap_geojson((13.0, 13.1, 80.2, 80.3), [small_poly])
        self.assertEqual(result["type"], "FeatureCollection")
        self.assertEqual(len(result["features"]), 1)
        self.assertIn(result["features"][0]["geometry"]["type"], {"Polygon", "MultiPolygon"})

    def test_road_gap_returns_no_gaps_when_isochrone_covers_area(self):
        large_poly = {
            "type": "Polygon",
            "coordinates": [[[80.19, 12.99], [80.31, 12.99], [80.31, 13.11], [80.19, 13.11], [80.19, 12.99]]],
        }
        result = uncovered_road_gap_geojson((13.0, 13.1, 80.2, 80.3), [large_poly])
        self.assertEqual(result["features"], [])

    def test_road_gap_empty_input_returns_empty_features(self):
        result = uncovered_road_gap_geojson((13.0, 13.1, 80.2, 80.3), [])
        self.assertEqual(result["features"], [])

    def test_road_gap_rejects_invalid_bounds(self):
        with self.assertRaises(ValueError):
            uncovered_road_gap_geojson((13.1, 13.0, 80.2, 80.3), [])


if __name__ == "__main__":
    unittest.main()