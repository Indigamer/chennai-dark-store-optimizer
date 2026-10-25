"""Benchmark script for testing solver performance at requested scale (10k×50).

Usage:
    python benchmark_scale.py [--customers N] [--stores M] [--time-limit S] [--seed SEED]

Results are printed to stdout and saved to benchmark_results.txt.
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import time

from data_validation import generate_demo_data
from optimization_model import solve_location_model


def run_benchmark(n_customers, n_stores, time_limit, seed, max_distance_km=8.0):
    """Run a single benchmark and return the result dict."""
    print(f"\n{'=' * 60}")
    print(f"  BENCHMARK: {n_customers:,} customers × {n_stores} stores")
    print(f"  Solver time limit: {time_limit}s | Seed: {seed}")
    print(f"  Max service distance: {max_distance_km} km")
    print(f"{'=' * 60}\n")

    # --- Data generation ---
    t0 = time.perf_counter()
    customers, stores = generate_demo_data(n_customers, n_stores, seed=seed)
    t_data = time.perf_counter() - t0
    print(f"[1/3] Data generated in {t_data:.3f}s")
    total_demand = sum(c["demand"] for c in customers)
    total_capacity = sum(s["capacity"] for s in stores)
    print(f"      Total demand: {total_demand:,.0f} orders/day")
    print(f"      Total capacity: {total_capacity:,.0f} orders/day")
    print(f"      Capacity ratio: {total_capacity / total_demand:.2f}x\n")

    # --- Distance matrix ---
    t1 = time.perf_counter()
    # solve_location_model computes Haversine internally; measure that phase
    # by doing a dry-run of vectorized distance computation
    from optimization_model import _vectorized_haversine_matrix
    dist_matrix = _vectorized_haversine_matrix(customers, stores)
    t_dist = time.perf_counter() - t1
    eligible_count = (dist_matrix <= max_distance_km).sum()
    total_pairs = n_customers * n_stores
    print(f"[2/3] Distance matrix computed in {t_dist:.3f}s")
    print(f"      Total pairs: {total_pairs:,}")
    print(f"      Eligible pairs (≤{max_distance_km} km): {eligible_count:,}")
    print(f"      Sparsity: {100 * (1 - eligible_count / total_pairs):.1f}% pruned\n")

    # --- Solver ---
    print(f"[3/3] Solving (time limit: {time_limit}s)...")
    t2 = time.perf_counter()
    result = solve_location_model(
        customers,
        stores,
        max_distance_km=max_distance_km,
        transport_cost_per_order_km=0.25,
        revenue_per_order=150.0,
        max_open_stores=None,
        time_limit_seconds=time_limit,
    )
    t_solve = time.perf_counter() - t2
    t_total = time.perf_counter() - t0

    print(f"\n{'─' * 60}")
    print(f"  RESULTS")
    print(f"{'─' * 60}")
    print(f"  Status:           {result.status}")
    print(f"  Message:          {result.message}")
    print(f"  Solver:           {result.solver_name}")
    print(f"  Solver elapsed:   {result.elapsed_seconds:.2f}s")
    print(f"  Wall-clock solve: {t_solve:.2f}s")
    print(f"  Total wall-clock: {t_total:.2f}s")

    if result.status in ("OPTIMAL", "FEASIBLE_LIMIT"):
        print(f"\n  Stores opened:    {len(result.open_store_ids)}")
        print(f"  Demand served:    {result.total_demand:,.0f} orders/day")
        print(f"  Objective:        {result.objective_value:,.2f}")
        print(f"  Profit:           {result.profit:,.2f}/day")
        print(f"  Transport cost:   {result.transport_cost:,.2f}/day")
        print(f"  Fixed cost:       {result.fixed_cost:,.2f}/day")
        print(f"  Avg distance:     {result.average_distance_km:.3f} km")
        if result.relative_gap is not None:
            print(f"  Optimality gap:   {100 * result.relative_gap:.3f}%")
        if result.best_bound is not None:
            print(f"  Best bound:       {result.best_bound:,.2f}")
        utilization = sum(result.capacity_utilization.values()) / max(len(result.capacity_utilization), 1)
        print(f"  Mean utilization: {100 * utilization:.1f}%")
    print(f"{'=' * 60}\n")

    return {
        "customers": n_customers,
        "stores": n_stores,
        "time_limit": time_limit,
        "seed": seed,
        "status": result.status,
        "solver": result.solver_name,
        "solver_seconds": result.elapsed_seconds,
        "wall_seconds": t_total,
        "data_seconds": t_data,
        "distance_seconds": t_dist,
        "stores_opened": len(result.open_store_ids) if result.open_store_ids else 0,
        "objective": result.objective_value,
        "profit": result.profit,
        "gap": result.relative_gap,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark dark-store solver at scale")
    parser.add_argument("--customers", type=int, default=10000, help="Number of customers (default: 10000)")
    parser.add_argument("--stores", type=int, default=50, help="Number of candidate stores (default: 50)")
    parser.add_argument("--time-limit", type=float, default=60.0, help="Solver time limit in seconds (default: 60)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--max-distance", type=float, default=8.0, help="Max service distance km (default: 8.0)")
    args = parser.parse_args()

    result = run_benchmark(
        args.customers,
        args.stores,
        args.time_limit,
        args.seed,
        args.max_distance,
    )

    # Save results to file
    with open("benchmark_results.txt", "a", encoding="utf-8") as f:
        from datetime import datetime
        f.write(f"\n{'=' * 60}\n")
        f.write(f"Benchmark: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        for key, value in result.items():
            f.write(f"  {key}: {value}\n")
        f.write(f"{'=' * 60}\n")

    print(f"Results appended to benchmark_results.txt")
    return 0 if result["status"] in ("OPTIMAL", "FEASIBLE_LIMIT") else 1


if __name__ == "__main__":
    sys.exit(main())
