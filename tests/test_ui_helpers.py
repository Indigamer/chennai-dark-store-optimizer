"""Tests for UI helper logic in app.py."""

import unittest
from types import SimpleNamespace

from app import _compute_pareto_front, _nearest_store_id, _store_summary


class UiHelperTests(unittest.TestCase):
    def test_compute_pareto_front_identifies_non_dominated_tradeoffs(self):
        # Scenario A: fixed=1000, trans=500 (Pareto)
        # Scenario B: fixed=1200, trans=400 (Pareto)
        # Scenario C: fixed=1500, trans=450 (Dominated by B)
        # Scenario D: fixed=2000, trans=300 (Pareto)
        scenarios = [
            SimpleNamespace(p_value=1, result=SimpleNamespace(status="OPTIMAL", fixed_cost=1000.0, transport_cost=500.0)),
            SimpleNamespace(p_value=2, result=SimpleNamespace(status="OPTIMAL", fixed_cost=1200.0, transport_cost=400.0)),
            SimpleNamespace(p_value=3, result=SimpleNamespace(status="OPTIMAL", fixed_cost=1500.0, transport_cost=450.0)),
            SimpleNamespace(p_value=4, result=SimpleNamespace(status="OPTIMAL", fixed_cost=2000.0, transport_cost=300.0)),
        ]
        pareto = _compute_pareto_front(scenarios)
        pareto_p = [item.p_value for item in pareto]
        self.assertEqual(pareto_p, [1, 2, 4])

    def test_compute_pareto_front_handles_empty_input(self):
        self.assertEqual(_compute_pareto_front([]), [])

    def test_nearest_store_id_identifies_close_clicks(self):
        stores = [
            {"store_id": "S1", "latitude": 13.0827, "longitude": 80.2707},
            {"store_id": "S2", "latitude": 13.0400, "longitude": 80.2500},
        ]
        # Click very close to S1 (e.g. 10 meters away)
        clicked = {"lat": 13.08272, "lng": 80.27072}
        self.assertEqual(_nearest_store_id(clicked, stores), "S1")

        # Click far away from any store (> 150m)
        far_click = {"lat": 13.1500, "lng": 80.2000}
        self.assertIsNone(_nearest_store_id(far_click, stores))

        # Invalid click dict
        self.assertIsNone(_nearest_store_id(None, stores))
        self.assertIsNone(_nearest_store_id({}, stores))

    def test_store_summary_aggregates_assignments(self):
        result = SimpleNamespace(
            assignments=[
                {"store_id": "S1", "demand": 10.0},
                {"store_id": "S1", "demand": 15.0},
                {"store_id": "S2", "demand": 50.0},
            ],
            capacity_utilization={"S1": 0.25, "S2": 0.50},
        )
        loads, util = _store_summary(result)
        self.assertEqual(loads["S1"], 25.0)
        self.assertEqual(loads["S2"], 50.0)
        self.assertEqual(util["S1"], 0.25)

    def test_on_focus_store_updates_session_state(self):
        import streamlit as st
        from app import _on_focus_store

        _on_focus_store("S003")
        self.assertEqual(st.session_state["selected_store_id"], "S003")
        self.assertTrue(st.session_state["lock_view_store"])


if __name__ == "__main__":
    unittest.main()
