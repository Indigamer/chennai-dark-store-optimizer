import csv
import io
import unittest
from pathlib import Path

from data_validation import (
    DEFAULT_CHENNAI_BOUNDS,
    InputValidationError,
    generate_demo_data,
    validate_customers_csv,
    validate_instance_capacity,
    validate_stores_csv,
)


class CustomerCsvTests(unittest.TestCase):
    def test_parses_valid_utf8_csv(self):
        content = b"customer_id,latitude,longitude,demand\nC1,13.08,80.27,12\n"
        rows = validate_customers_csv(content)
        self.assertEqual(rows[0]["customer_id"], "C1")
        self.assertEqual(rows[0]["demand"], 12.0)

    def test_rejects_missing_columns(self):
        with self.assertRaisesRegex(InputValidationError, "Missing required columns"):
            validate_customers_csv("customer_id,latitude\nC1,13.08\n")

    def test_rejects_duplicate_ids_and_negative_demand(self):
        content = "customer_id,latitude,longitude,demand\nC1,13.08,80.27,4\nC1,13.09,80.26,-1\n"
        with self.assertRaises(InputValidationError) as context:
            validate_customers_csv(content)
        message = str(context.exception)
        self.assertIn("duplicate customer_id", message)
        self.assertIn("demand cannot be negative", message)

    def test_rejects_nonfinite_values_and_out_of_region_coordinates(self):
        content = "customer_id,latitude,longitude,demand\nC1,nan,80.27,4\nC2,13.08,80.5,3\n"
        with self.assertRaises(InputValidationError) as context:
            validate_customers_csv(content)
        self.assertIn("finite number", str(context.exception))
        self.assertIn("outside the configured region bounds", str(context.exception))

    def test_accepts_custom_bounds(self):
        content = "customer_id,latitude,longitude,demand\nC1,13.25,80.35,4\n"
        rows = validate_customers_csv(content, bounds=(13.2, 13.3, 80.3, 80.4))
        self.assertEqual(len(rows), 1)

    def test_rejects_empty_csv(self):
        with self.assertRaisesRegex(InputValidationError, "CSV is empty"):
            validate_customers_csv("  ")


class StoreCsvTests(unittest.TestCase):
    def test_parses_valid_store_csv(self):
        content = "store_id,latitude,longitude,fixed_cost,capacity\nS1,13.08,80.27,1200,500\n"
        rows = validate_stores_csv(content)
        self.assertEqual(rows[0]["store_id"], "S1")
        self.assertEqual(rows[0]["capacity"], 500.0)

    def test_rejects_invalid_cost_and_capacity(self):
        content = "store_id,latitude,longitude,fixed_cost,capacity\nS1,13.08,80.27,-5,NaN\n"
        with self.assertRaises(InputValidationError) as context:
            validate_stores_csv(content)
        message = str(context.exception)
        self.assertIn("fixed_cost cannot be negative", message)
        self.assertIn("capacity must be a finite number", message)


class InstancePreflightTests(unittest.TestCase):
    def setUp(self):
        self.customers = [{"customer_id": "C1", "demand": 60.0}, {"customer_id": "C2", "demand": 40.0}]
        self.stores = [
            {"store_id": "S1", "capacity": 70.0},
            {"store_id": "S2", "capacity": 50.0},
            {"store_id": "S3", "capacity": 20.0},
        ]

    def test_accepts_capacity_within_limit(self):
        summary = validate_instance_capacity(self.customers, self.stores, max_open_stores=2)
        self.assertEqual(summary["total_demand"], 100.0)
        self.assertEqual(summary["total_capacity"], 140.0)

    def test_rejects_insufficient_total_capacity(self):
        with self.assertRaisesRegex(InputValidationError, "below total demand"):
            validate_instance_capacity(self.customers, self.stores[:1])

    def test_rejects_insufficient_capacity_under_store_limit(self):
        with self.assertRaisesRegex(InputValidationError, "highest-capacity stores"):
            validate_instance_capacity(self.customers, self.stores, max_open_stores=1)

    def test_rejects_invalid_store_limit(self):
        with self.assertRaisesRegex(InputValidationError, "whole number"):
            validate_instance_capacity(self.customers, self.stores, max_open_stores=1.5)

    def test_rejects_empty_instance(self):
        with self.assertRaisesRegex(InputValidationError, "At least one customer"):
            validate_instance_capacity([], self.stores)


class DemoDataTests(unittest.TestCase):
    def test_generator_is_deterministic_and_within_chennai_bounds(self):
        customers_a, stores_a = generate_demo_data(15, 5, seed=7)
        customers_b, stores_b = generate_demo_data(15, 5, seed=7)
        self.assertEqual(customers_a, customers_b)
        self.assertEqual(stores_a, stores_b)
        min_lat, max_lat, min_lon, max_lon = DEFAULT_CHENNAI_BOUNDS
        for row in customers_a + stores_a:
            self.assertTrue(min_lat <= row["latitude"] <= max_lat)
            self.assertTrue(min_lon <= row["longitude"] <= max_lon)

    def test_generator_rejects_nonpositive_counts(self):
        with self.assertRaisesRegex(ValueError, "must both be positive"):
            generate_demo_data(n_customers=0)

    def test_generator_capacity_supports_two_open_store_scenario(self):
        customers, stores = generate_demo_data(100, 20, seed=13)
        validate_instance_capacity(customers, stores, max_open_stores=2)

    def test_generated_rows_match_upload_validators(self):
        customers, stores = generate_demo_data(20, 6, seed=9)
        customer_buffer = io.StringIO()
        customer_writer = csv.DictWriter(customer_buffer, fieldnames=customers[0].keys())
        customer_writer.writeheader()
        customer_writer.writerows(customers)
        store_buffer = io.StringIO()
        store_writer = csv.DictWriter(store_buffer, fieldnames=stores[0].keys())
        store_writer.writeheader()
        store_writer.writerows(stores)
        self.assertEqual(len(validate_customers_csv(customer_buffer.getvalue())), 20)
        self.assertEqual(len(validate_stores_csv(store_buffer.getvalue())), 6)

    def test_example_inputs_validate_and_sensitivity_capacity_is_feasible(self):
        examples = Path(__file__).resolve().parents[1]
        optimizer_customers = validate_customers_csv(
            (examples / "optimizer_example_customers.csv").read_bytes()
        )
        optimizer_stores = validate_stores_csv(
            (examples / "optimizer_example_stores.csv").read_bytes()
        )
        sensitivity_customers = validate_customers_csv(
            (examples / "sensitivity_example_customers.csv").read_bytes()
        )
        sensitivity_stores = validate_stores_csv(
            (examples / "sensitivity_example_stores.csv").read_bytes()
        )

        validate_instance_capacity(optimizer_customers, optimizer_stores, max_open_stores=3)
        validate_instance_capacity(sensitivity_customers, sensitivity_stores, max_open_stores=2)


if __name__ == "__main__":
    unittest.main()