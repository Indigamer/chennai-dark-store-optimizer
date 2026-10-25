"""Budgeted OpenRouteService client for road distances and isochrones."""

from dataclasses import dataclass
import json
import math
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from optimization_model import haversine_distance_km


ORS_BASE_URL = "https://api.openrouteservice.org/v2"


@dataclass
class RoutingResult:
    status: str
    message: str
    distance_matrix_km: Optional[list] = None
    geojson: Optional[dict] = None
    requested_elements: int = 0
    request_count: int = 0


class OpenRouteServiceClient:
    """Fetch road matrices and distance isochrones without exposing API keys."""

    def __init__(
        self,
        api_key,
        *,
        profile="driving-car",
        timeout_seconds=20,
        max_elements_per_request=2500,
        max_total_elements=100_000,
        max_retries=2,
        retry_backoff_seconds=0.5,
        request_json=None,
        sleep=time.sleep,
    ):
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.max_elements_per_request = max_elements_per_request
        self.max_total_elements = max_total_elements
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._request_json = request_json or self._post_json
        self._sleep = sleep

    def _post_json(self, path, payload):
        request = Request(
            f"{ORS_BASE_URL}/{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _http_error_status(error):
        if error.code in (401, 403):
            return "INVALID_CREDENTIALS", "Routing provider rejected the configured credentials."
        if error.code in (413, 429):
            return "API_LIMIT_REACHED", "Routing provider rejected the request because of a size or rate limit."
        return "API_ERROR", f"Routing provider returned HTTP {error.code}."

    def _safe_request(self, path, payload):
        if not self._api_key:
            return None, RoutingResult(
                status="INVALID_CREDENTIALS",
                message="Road mode requires an OpenRouteService API key.",
            )
        for attempt in range(self.max_retries + 1):
            try:
                return self._request_json(path, payload), None
            except HTTPError as error:
                status, message = self._http_error_status(error)
                return None, RoutingResult(status=status, message=message)
            except URLError as error:
                if isinstance(error.reason, TimeoutError):
                    status, message = "API_TIMEOUT", "Routing request timed out."
                else:
                    status, message = "API_ERROR", "Could not connect to the routing provider."
            except TimeoutError:
                status, message = "API_TIMEOUT", "Routing request timed out."
            except OSError:
                status, message = "API_ERROR", "Could not connect to the routing provider."
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
                return None, RoutingResult(status="INCOMPLETE_MATRIX", message="Routing provider returned malformed JSON.")

            if attempt < self.max_retries:
                self._sleep(self.retry_backoff_seconds * (2 ** attempt))
        return None, RoutingResult(status=status, message=message)

    def fetch_distance_matrix(self, customers, stores, max_distance_km):
        """Return a sparse road-distance matrix in km; pruned pairs remain None."""
        if not customers or not stores:
            return RoutingResult(status="INVALID_INPUT", message="Customers and stores are required for road routing.")
        if not math.isfinite(float(max_distance_km)) or float(max_distance_km) < 0:
            return RoutingResult(status="INVALID_INPUT", message="Maximum road distance must be finite and nonnegative.")
        if not isinstance(self.max_elements_per_request, int) or self.max_elements_per_request < 1:
            return RoutingResult(status="INVALID_INPUT", message="Per-request route-element limit must be a positive integer.")
        if not isinstance(self.max_total_elements, int) or self.max_total_elements < 1:
            return RoutingResult(status="INVALID_INPUT", message="Total route-element budget must be a positive integer.")

        max_distance_km = float(max_distance_km)
        matrix = [[None] * len(stores) for _ in customers]
        store_destinations = []
        total_elements = 0
        request_count = 0
        for store in stores:
            source = [float(store["longitude"]), float(store["latitude"])]
            eligible_customers = []
            for customer_index, customer in enumerate(customers):
                straight_distance = haversine_distance_km(
                    float(customer["latitude"]),
                    float(customer["longitude"]),
                    float(store["latitude"]),
                    float(store["longitude"]),
                )
                if straight_distance <= max_distance_km:
                    eligible_customers.append(customer_index)
            store_destinations.append((source, eligible_customers))
            total_elements += len(eligible_customers)
            if eligible_customers:
                request_count += math.ceil(len(eligible_customers) / self.max_elements_per_request)

        if total_elements > self.max_total_elements:
            return RoutingResult(
                status="API_LIMIT_REACHED",
                message=(
                    f"Road matrix requires {total_elements:,} route elements, above the configured "
                    f"budget of {self.max_total_elements:,}. Increase the budget or reduce the data size."
                ),
                requested_elements=total_elements,
                request_count=request_count,
            )

        completed_elements = 0
        completed_requests = 0
        for store_index, (source, customer_indices) in enumerate(store_destinations):
            for offset in range(0, len(customer_indices), self.max_elements_per_request):
                batch = customer_indices[offset:offset + self.max_elements_per_request]
                payload = {
                    "locations": [source] + [
                        [float(customers[index]["longitude"]), float(customers[index]["latitude"])]
                        for index in batch
                    ],
                    "sources": [0],
                    "destinations": list(range(1, len(batch) + 1)),
                    "metrics": ["distance"],
                    "units": "km",
                }
                response, error = self._safe_request(f"matrix/{self.profile}", payload)
                if error:
                    error.requested_elements = total_elements
                    error.request_count = completed_requests + 1
                    return error
                try:
                    values = response["distances"]
                    if len(values) != 1 or len(values[0]) != len(batch):
                        raise ValueError
                    parsed = []
                    for value in values[0]:
                        if value is None:
                            parsed.append(None)
                            continue
                        distance = float(value)
                        if not math.isfinite(distance) or distance < 0:
                            raise ValueError
                        parsed.append(distance)
                except (KeyError, TypeError, ValueError):
                    return RoutingResult(
                        status="INCOMPLETE_MATRIX",
                        message="Routing provider returned a missing, partial, or invalid distance matrix.",
                        requested_elements=total_elements,
                        request_count=completed_requests + 1,
                    )

                for customer_index, distance in zip(batch, parsed):
                    matrix[customer_index][store_index] = distance
                completed_elements += len(batch)
                completed_requests += 1

        if completed_elements != total_elements:
            return RoutingResult(
                status="INCOMPLETE_MATRIX",
                message="Road matrix is incomplete; no optimization result should be produced.",
                requested_elements=total_elements,
                request_count=completed_requests,
            )
        return RoutingResult(
            status="OPTIMAL",
            message="Road-distance matrix prepared.",
            distance_matrix_km=matrix,
            requested_elements=total_elements,
            request_count=completed_requests,
        )

    def fetch_isochrone(self, store, max_distance_km):
        """Fetch a GeoJSON reachable-area polygon for one store and distance limit."""
        try:
            max_distance_km = float(max_distance_km)
            latitude = float(store["latitude"])
            longitude = float(store["longitude"])
            if (
                not math.isfinite(max_distance_km)
                or max_distance_km <= 0
                or not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return RoutingResult(status="INVALID_INPUT", message="Store coordinates and isochrone distance are invalid.")

        payload = {
            "locations": [[longitude, latitude]],
            "range_type": "distance",
            "range": [int(round(max_distance_km * 1000))],
            "attributes": ["area"],
        }
        response, error = self._safe_request(f"isochrones/{self.profile}", payload)
        if error:
            return error
        try:
            features = response["features"]
            geometry = features[0]["geometry"]
            if geometry.get("type") not in ("Polygon", "MultiPolygon") or not geometry.get("coordinates"):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            return RoutingResult(
                status="ISOCHRONE_UNAVAILABLE",
                message="Routing provider did not return a valid reachable-area polygon.",
            )
        return RoutingResult(status="OPTIMAL", message="Road reachable-area polygon prepared.", geojson=response)