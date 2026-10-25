import unittest
from urllib.error import HTTPError, URLError

from routing_provider import OpenRouteServiceClient


class FakeRequester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, path, payload):
        self.calls.append((path, payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RoutingProviderTests(unittest.TestCase):
    def setUp(self):
        self.customers = [
            {"customer_id": "C1", "latitude": 13.08, "longitude": 80.27},
            {"customer_id": "C2", "latitude": 13.081, "longitude": 80.27},
            {"customer_id": "C3", "latitude": 13.18, "longitude": 80.27},
        ]
        self.stores = [
            {"store_id": "S1", "latitude": 13.08, "longitude": 80.27},
            {"store_id": "S2", "latitude": 13.08, "longitude": 80.271},
        ]

    def test_builds_sparse_distance_matrix_and_batches(self):
        fake = FakeRequester([
            {"distances": [[0.0, 0.2]]},
            {"distances": [[0.1, 0.0]]},
        ])
        client = OpenRouteServiceClient(
            "dummy-key",
            max_elements_per_request=2,
            max_total_elements=10,
            request_json=fake,
        )
        result = client.fetch_distance_matrix(self.customers, self.stores, max_distance_km=1)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.requested_elements, 4)
        self.assertEqual(result.request_count, 2)
        self.assertEqual(result.distance_matrix_km, [[0.0, 0.1], [0.2, 0.0], [None, None]])
        self.assertEqual(fake.calls[0][1]["units"], "km")

    def test_budget_is_checked_before_any_api_request(self):
        fake = FakeRequester([])
        client = OpenRouteServiceClient("dummy", max_total_elements=1, request_json=fake)
        result = client.fetch_distance_matrix(self.customers, self.stores, max_distance_km=1)
        self.assertEqual(result.status, "API_LIMIT_REACHED")
        self.assertEqual(fake.calls, [])

    def test_missing_key_has_explicit_status(self):
        client = OpenRouteServiceClient("")
        result = client.fetch_distance_matrix(self.customers, self.stores, max_distance_km=1)
        self.assertEqual(result.status, "INVALID_CREDENTIALS")

    def test_rate_limit_has_explicit_status_and_no_partial_matrix(self):
        fake = FakeRequester([HTTPError("url", 429, "limited", {}, None)])
        client = OpenRouteServiceClient("dummy", max_total_elements=20, request_json=fake)
        result = client.fetch_distance_matrix(self.customers, self.stores, max_distance_km=1)
        self.assertEqual(result.status, "API_LIMIT_REACHED")
        self.assertIsNone(result.distance_matrix_km)

    def test_transient_timeout_is_retried_then_succeeds(self):
        fake = FakeRequester([
            URLError(TimeoutError("temporary timeout")),
            {"distances": [[0.0, 0.2]]},
            {"distances": [[0.1, 0.0]]},
        ])
        client = OpenRouteServiceClient(
            "dummy",
            max_elements_per_request=10,
            max_total_elements=20,
            retry_backoff_seconds=0,
            request_json=fake,
            sleep=lambda _: None,
        )
        result = client.fetch_distance_matrix(self.customers[:2], self.stores, max_distance_km=1)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(len(fake.calls), 3)

    def test_timeout_exhaustion_has_explicit_status(self):
        fake = FakeRequester([TimeoutError("timeout"), TimeoutError("timeout"), TimeoutError("timeout")])
        client = OpenRouteServiceClient(
            "dummy",
            max_total_elements=20,
            retry_backoff_seconds=0,
            request_json=fake,
            sleep=lambda _: None,
        )
        result = client.fetch_distance_matrix(self.customers[:2], self.stores, max_distance_km=1)
        self.assertEqual(result.status, "API_TIMEOUT")
        self.assertIsNone(result.distance_matrix_km)

    def test_partial_matrix_has_explicit_status(self):
        fake = FakeRequester([{"distances": [[0.0]]}])
        client = OpenRouteServiceClient("dummy", max_total_elements=20, request_json=fake)
        result = client.fetch_distance_matrix(self.customers, self.stores, max_distance_km=1)
        self.assertEqual(result.status, "INCOMPLETE_MATRIX")
        self.assertIsNone(result.distance_matrix_km)

    def test_isochrone_returns_valid_geojson(self):
        geojson = {
            "features": [{
                "geometry": {"type": "Polygon", "coordinates": [[[80.2, 13.0], [80.3, 13.0], [80.2, 13.0]]]},
            }],
        }
        fake = FakeRequester([geojson])
        client = OpenRouteServiceClient("dummy", request_json=fake)
        result = client.fetch_isochrone(self.stores[0], 5)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.geojson, geojson)
        self.assertEqual(fake.calls[0][1]["range"], [5000])

    def test_missing_isochrone_geometry_has_explicit_status(self):
        client = OpenRouteServiceClient("dummy", request_json=FakeRequester([{"features": []}]))
        result = client.fetch_isochrone(self.stores[0], 5)
        self.assertEqual(result.status, "ISOCHRONE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()