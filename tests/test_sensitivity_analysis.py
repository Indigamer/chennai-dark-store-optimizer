import unittest

from sensitivity_analysis import run_sensitivity_scenarios


class SensitivityTests(unittest.TestCase):
    def setUp(self):
        self.customers = [{"customer_id": "C1", "latitude": 13.08, "longitude": 80.27, "demand": 4}]
        self.stores = [
            {"store_id": "S1", "latitude": 13.08, "longitude": 80.27, "fixed_cost": 8, "capacity": 4},
            {"store_id": "S2", "latitude": 13.08, "longitude": 80.28, "fixed_cost": 6, "capacity": 4},
        ]

    def test_scenarios_share_distance_matrix_and_return_results(self):
        matrix = [[0.0, 1.1]]
        results, error = run_sensitivity_scenarios(
            self.customers,
            self.stores,
            [1, 2],
            max_distance_km=5,
            transport_cost_per_order_km=1,
            revenue_per_order=10,
            per_scenario_seconds=3,
            total_budget_seconds=10,
            distance_matrix_km=matrix,
        )
        self.assertIsNone(error)
        self.assertEqual([item.p_value for item in results], [1, 2])
        self.assertTrue(all(item.result.status == "OPTIMAL" for item in results))

    def test_invalid_scenario_values_are_rejected(self):
        results, error = run_sensitivity_scenarios(
            self.customers,
            self.stores,
            [3],
            max_distance_km=5,
            transport_cost_per_order_km=1,
            revenue_per_order=10,
            per_scenario_seconds=3,
            total_budget_seconds=10,
        )
        self.assertEqual(results, [])
        self.assertIn("number of candidates", error)

    def test_empty_scenario_list_is_rejected(self):
        results, error = run_sensitivity_scenarios(
            self.customers,
            self.stores,
            [],
            max_distance_km=5,
            transport_cost_per_order_km=1,
            revenue_per_order=10,
            per_scenario_seconds=3,
            total_budget_seconds=10,
        )
        self.assertEqual(results, [])
        self.assertIn("Select at least one", error)

    def test_exact_open_stores_forces_exact_store_count(self):
        customers = [
            {"customer_id": "C1", "latitude": 13.08, "longitude": 80.27, "demand": 2},
            {"customer_id": "C2", "latitude": 13.08, "longitude": 80.28, "demand": 2},
        ]
        stores = [
            {"store_id": "S1", "latitude": 13.08, "longitude": 80.27, "fixed_cost": 8, "capacity": 4},
            {"store_id": "S2", "latitude": 13.08, "longitude": 80.28, "fixed_cost": 6, "capacity": 4},
        ]
        results, error = run_sensitivity_scenarios(
            customers,
            stores,
            [1, 2],
            max_distance_km=5,
            transport_cost_per_order_km=1,
            revenue_per_order=10,
            per_scenario_seconds=3,
            total_budget_seconds=10,
            exact_open_stores=True,
        )
        self.assertIsNone(error)
        self.assertEqual(len(results[0].result.open_store_ids), 1)
        self.assertEqual(len(results[1].result.open_store_ids), 2)


if __name__ == "__main__":
    unittest.main()