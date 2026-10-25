"""Facility-limit scenario runner with shared distances and time budgets."""

from dataclasses import dataclass
import math
import time

from optimization_model import OptimizationResult, solve_location_model


@dataclass
class SensitivityResult:
    p_value: int
    result: OptimizationResult


def run_sensitivity_scenarios(
    customers,
    stores,
    p_values,
    *,
    max_distance_km,
    transport_cost_per_order_km,
    revenue_per_order,
    per_scenario_seconds,
    total_budget_seconds,
    distance_matrix_km=None,
    exact_open_stores=False,
):
    """Solve selected P values while reusing distances and respecting a time budget."""
    try:
        per_scenario_seconds = float(per_scenario_seconds)
        total_budget_seconds = float(total_budget_seconds)
    except (TypeError, ValueError):
        return [], "Scenario time limits must be numeric."
    if (
        not math.isfinite(per_scenario_seconds)
        or not math.isfinite(total_budget_seconds)
        or per_scenario_seconds <= 0
        or total_budget_seconds <= 0
    ):
        return [], "Scenario time limits must be positive and finite."
    if not p_values:
        return [], "Select at least one facility-limit scenario."
    if any(isinstance(value, bool) or not isinstance(value, int) for value in p_values):
        return [], "Facility-limit values must be whole numbers."
    if any(value < 1 or value > len(stores) for value in p_values):
        return [], "Facility-limit values must be between one and the number of candidates."

    started = time.monotonic()
    results = []

    # Sort ascending for warm-start chaining: a P=k solution is feasible for P=k+1
    sorted_p = sorted(p_values)
    previous_solution = None

    for p_value in sorted_p:
        remaining = total_budget_seconds - (time.monotonic() - started)
        if remaining <= 0:
            timeout_result = OptimizationResult(
                status="TIME_LIMIT_NO_SOLUTION",
                message="Overall sensitivity-analysis time budget was exhausted before this scenario.",
            )
            results.append(SensitivityResult(p_value=p_value, result=timeout_result))
            continue
        result = solve_location_model(
            customers,
            stores,
            max_distance_km=max_distance_km,
            transport_cost_per_order_km=transport_cost_per_order_km,
            revenue_per_order=revenue_per_order,
            max_open_stores=p_value,
            exact_open_stores=exact_open_stores,
            time_limit_seconds=min(per_scenario_seconds, remaining),
            distance_matrix_km=distance_matrix_km,
            initial_solution=previous_solution if not exact_open_stores else None,
        )
        results.append(SensitivityResult(p_value=p_value, result=result))

        # Chain feasible solutions as warm-starts for the next (larger P) scenario
        if result.status in ("OPTIMAL", "FEASIBLE_LIMIT"):
            previous_solution = {
                "open_store_ids": result.open_store_ids,
                "assignments": result.assignments,
            }

    # Re-sort to match the caller's original P-value order
    p_order = {p: i for i, p in enumerate(p_values)}
    results.sort(key=lambda r: p_order.get(r.p_value, 0))

    return results, None