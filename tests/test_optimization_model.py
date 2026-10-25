import unittest

from optimization_model import _map_solver_status, haversine_distance_km, solve_location_model
from ortools.linear_solver import pywraplp


class HaversineTests(unittest.TestCase):
    def test_same_location_has_zero_distance(self):
        self.assertAlmostEqual(haversine_distance_km(13.08, 80.27, 13.08, 80.27), 0.0)

    def test_chennai_to_nearby_point_distance_is_reasonable(self):
        distance = haversine_distance_km(13.08, 80.27, 13.09, 80.27)
        self.assertGreater(distance, 1.0)
        self.assertLess(distance, 1.2)


class SolverStatusTests(unittest.TestCase):
    def test_maps_solver_statuses(self):
        self.assertEqual(_map_solver_status(pywraplp.Solver.OPTIMAL), "OPTIMAL")
        self.assertEqual(_map_solver_status(pywraplp.Solver.FEASIBLE), "FEASIBLE_LIMIT")
        self.assertEqual(_map_solver_status(pywraplp.Solver.INFEASIBLE), "INFEASIBLE")
        self.assertEqual(_map_solver_status(pywraplp.Solver.NOT_SOLVED), "TIME_LIMIT_NO_SOLUTION")
        self.assertEqual(_map_solver_status(pywraplp.Solver.MODEL_INVALID), "INVALID_MODEL")
        self.assertEqual(_map_solver_status(-1), "INTERNAL_ERROR")


class LocationModelTests(unittest.TestCase):
    def setUp(self):
        self.customers = [{"customer_id": "C1", "latitude": 13.08, "longitude": 80.27, "demand": 10}]
        self.stores = [
            {"store_id": "near", "latitude": 13.08, "longitude": 80.27, "fixed_cost": 10, "capacity": 10},
            {"store_id": "far-cheap", "latitude": 13.08, "longitude": 80.27, "fixed_cost": 1, "capacity": 10},
        ]
    def test_hand_computable_optimum_uses_lower_total_cost_store(self):
        result = solve_location_model(
            self.customers,
            self.stores,
            max_distance_km=10,
            transport_cost_per_order_km=1,
            revenue_per_order=5,
            distance_matrix_km=[[1, 5]],
        )
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.open_store_ids, ["near"])
        self.assertAlmostEqual(result.objective_value, 20.0)
        self.assertAlmostEqual(result.transport_cost, 10.0)
        self.assertAlmostEqual(result.fixed_cost, 10.0)
        self.assertAlmostEqual(result.revenue, 50.0)
        self.assertAlmostEqual(result.profit, 30.0)
        self.assertEqual(len(result.assignments), 1)

    def test_respects_maximum_service_distance(self):
        result = solve_location_model(
            self.customers,
            self.stores,
            max_distance_km=2,
            transport_cost_per_order_km=1,
            distance_matrix_km=[[1, 5]],
        )
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.open_store_ids, ["near"])

    def test_reports_customer_without_eligible_store(self):
        result = solve_location_model(
            self.customers,
            self.stores,
            max_distance_km=2,
            transport_cost_per_order_km=1,
            distance_matrix_km=[[3, None]],
        )
        self.assertEqual(result.status, "INFEASIBLE")
        self.assertEqual(result.unserviceable_customer_ids, ["C1"])

    def test_rejects_infinite_distance_matrix_values(self):
        result = solve_location_model(
            self.customers,
            self.stores,
            max_distance_km=10,
            transport_cost_per_order_km=1,
            distance_matrix_km=[[float("inf"), 1]],
        )
        self.assertEqual(result.status, "INVALID_INPUT")
        self.assertIn("Distance matrix", result.message)

    def test_rejects_invalid_coordinates(self):
        customer = [{"customer_id": "C1", "latitude": float("nan"), "longitude": 80.27, "demand": 1}]
        result = solve_location_model(
            customer,
            self.stores,
            max_distance_km=10,
            transport_cost_per_order_km=1,
        )
        self.assertEqual(result.status, "INVALID_INPUT")
        self.assertIn("Coordinates", result.message)

    def test_capacity_and_open_limit_make_problem_infeasible(self):
        customers = [
            {"customer_id": "C1", "latitude": 13.08, "longitude": 80.27, "demand": 7},
            {"customer_id": "C2", "latitude": 13.08, "longitude": 80.27, "demand": 6},
        ]
        stores = [
            {"store_id": "S1", "latitude": 13.08, "longitude": 80.27, "fixed_cost": 1, "capacity": 7},
            {"store_id": "S2", "latitude": 13.08, "longitude": 80.27, "fixed_cost": 1, "capacity": 6},
        ]
        result = solve_location_model(
            customers,
            stores,
            max_distance_km=1,
            transport_cost_per_order_km=0,
            max_open_stores=1,
            distance_matrix_km=[[0, 0], [0, 0]],
        )
        self.assertEqual(result.status, "INFEASIBLE")

    def test_invalid_settings_have_explicit_status(self):
        result = solve_location_model(
            self.customers,
            self.stores,
            max_distance_km=-1,
            transport_cost_per_order_km=1,
        )
        self.assertEqual(result.status, "INVALID_INPUT")

    def test_numeric_string_settings_are_normalized(self):
        result = solve_location_model(
            self.customers,
            self.stores,
            max_distance_km="2",
            transport_cost_per_order_km="1",
            distance_matrix_km=[[1, 5]],
        )
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.open_store_ids, ["near"])


if __name__ == "__main__":
    unittest.main()