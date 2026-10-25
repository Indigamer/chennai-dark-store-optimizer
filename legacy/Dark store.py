import argparse
import csv
import math
import os
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ortools.linear_solver import pywraplp


def generate_large_dataset(customers_path, stores_path, n_customers=10000, n_stores=40):
    """Create a larger synthetic dataset with clustered customers and candidate stores."""
    import random

    random.seed(42)

    cluster_centers = [
        (20, 20), (25, 75), (50, 25), (55, 80), (80, 25),
        (85, 75), (35, 45), (65, 45), (15, 55), (90, 55)
    ]

    customer_rows = []
    for i in range(1, n_customers + 1):
        cx, cy = cluster_centers[(i - 1) % len(cluster_centers)]
        x = max(0, min(100, cx + random.uniform(-10, 10)))
        y = max(0, min(100, cy + random.uniform(-10, 10)))
        demand = random.randint(5, 25)
        customer_rows.append({
            "customer_id": i,
            "x": round(x, 2),
            "y": round(y, 2),
            "demand": demand,
        })

    total_demand = sum(row["demand"] for row in customer_rows)

    with open(customers_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["customer_id", "x", "y", "demand"])
        writer.writeheader()
        writer.writerows(customer_rows)

    # Candidate store locations spread across the area.
    # Ensure the total capacity is at least total demand so the optimization instance is feasible.
    store_rows = []
    target_capacity_per_store = max(150.0, total_demand / n_stores * 1.25)
    remaining_capacity = total_demand

    for j in range(1, n_stores + 1):
        x = 10 + (j % 8) * 12 + random.uniform(-2, 2)
        y = 10 + ((j // 8) % 5) * 18 + random.uniform(-2, 2)
        x = max(0, min(100, x))
        y = max(0, min(100, y))
        fixed_cost = random.randint(1200, 3200)

        if j == n_stores:
            capacity = max(200, math.ceil(remaining_capacity))
        else:
            capacity = max(150, int(round(random.uniform(0.8, 1.3) * target_capacity_per_store)))
            remaining_capacity -= min(capacity, remaining_capacity)

        store_rows.append({
            "store_id": j,
            "x": round(x, 2),
            "y": round(y, 2),
            "fixed_cost": fixed_cost,
            "capacity": capacity,
        })

    if sum(row["capacity"] for row in store_rows) < total_demand:
        store_rows[-1]["capacity"] = int(math.ceil(total_demand))

    with open(stores_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["store_id", "x", "y", "fixed_cost", "capacity"])
        writer.writeheader()
        writer.writerows(store_rows)

    return customer_rows, store_rows


def load_customers(csv_path):
    customers = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            customers.append({
                "customer_id": int(row["customer_id"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "demand": float(row["demand"]),
            })
    return customers


def load_stores(csv_path):
    stores = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stores.append({
                "store_id": int(row["store_id"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "fixed_cost": float(row["fixed_cost"]),
                "capacity": float(row["capacity"]),
            })
    return stores


def cluster_customers_for_visual(customers, grid_size=8):
    """Aggregate nearby customers into visual clusters, while keeping stores as single points."""
    grid = defaultdict(list)
    for customer in customers:
        gx = int(customer["x"] // grid_size)
        gy = int(customer["y"] // grid_size)
        grid[(gx, gy)].append(customer)

    clusters = []
    for (gx, gy), items in grid.items():
        x_avg = sum(item["x"] for item in items) / len(items)
        y_avg = sum(item["y"] for item in items) / len(items)
        clusters.append({
            "x": x_avg,
            "y": y_avg,
            "count": len(items),
        })
    return clusters


def plot_before_and_after(customers, stores, open_stores, assignments):
    """Visualize all possible locations vs final store selection using clustered customer points."""
    fig, axes = plt.subplots(1, 2, figsize=(18, 8))
    store_colors = [
        "#ff7f0e", "#2ca02c", "#1f77b4", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#bcbd22", "#17becf", "#7f7f7f",
        "#ffbb78", "#98df8a", "#aec7e8", "#ff9896", "#c5b0d5"
    ]

    # Before: candidate stores and clustered customers
    ax = axes[0]
    customer_clusters = cluster_customers_for_visual(customers, grid_size=8)
    for cluster in customer_clusters:
        size = min(500, 20 + cluster["count"] * 0.6)
        ax.scatter(cluster["x"], cluster["y"], s=size, color="lightgray", alpha=0.8, edgecolors="black", linewidth=0.3)

    for store in stores:
        ax.scatter(store["x"], store["y"], s=120, color="orange", edgecolors="black", linewidth=1.0)
        ax.text(store["x"] + 1.0, store["y"] + 1.2, f"S{store['store_id']}", fontsize=8, fontweight="bold")

    ax.set_title("Before: candidate locations and clustered customer demand")
    ax.set_xlabel("X coordinate")
    ax.set_ylabel("Y coordinate")
    ax.grid(True, linestyle="--", alpha=0.3)
    ax.set_aspect("equal")

    # After: only selected stores and demand clusters assigned to them
    ax = axes[1]
    assigned_by_customer = {}
    for customer_index, customer in enumerate(customers):
        assigned_store = None
        for store_index, qty in assignments.get(customer_index, []):
            if qty > 1e-6:
                assigned_store = store_index
                break
        assigned_by_customer[customer_index] = assigned_store

    cluster_assignment = defaultdict(list)
    for customer_index, customer in enumerate(customers):
        assigned_store = assigned_by_customer[customer_index]
        if assigned_store is None:
            continue
        gx = int(customer["x"] // 8)
        gy = int(customer["y"] // 8)
        cluster_assignment[(gx, gy)].append(assigned_store)

    for cluster in customer_clusters:
        cx = cluster["x"]
        cy = cluster["y"]
        cell = (int(cx // 8), int(cy // 8))
        store_votes = cluster_assignment.get(cell, [])
        if not store_votes:
            store_id = None
        else:
            store_id = Counter(store_votes).most_common(1)[0][0]

        if store_id is None:
            color = "lightgray"
        else:
            color = store_colors[store_id % len(store_colors)]
        size = min(700, 20 + cluster["count"] * 0.6)
        ax.scatter(cx, cy, s=size, color=color, alpha=0.85, edgecolors="black", linewidth=0.5)

    for store in stores:
        is_open = store["store_id"] - 1 in open_stores
        ax.scatter(
            store["x"], store["y"],
            s=150,
            color="green" if is_open else "red",
            edgecolors="black",
            linewidth=1.0,
            marker="D" if is_open else "X"
        )
        ax.text(store["x"] + 1.0, store["y"] + 1.2, f"S{store['store_id']}", fontsize=8, fontweight="bold")

    ax.set_title("After: selected stores and clustered customer assignment")
    ax.set_xlabel("X coordinate")
    ax.set_ylabel("Y coordinate")
    ax.grid(True, linestyle="--", alpha=0.3)
    ax.set_aspect("equal")

    plt.tight_layout()
    plt.savefig("dark_store_visualization.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def solve_dark_store_location(customers, stores):
    n_customers = len(customers)
    n_stores = len(stores)

    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        solver = pywraplp.Solver.CreateSolver("CBC")
    if solver is None:
        raise RuntimeError("No suitable linear solver found in OR-Tools.")

    y = {j: solver.BoolVar(f"y_{j}") for j in range(n_stores)}
    x = {
        (i, j): solver.NumVar(0.0, float(customers[i]["demand"]), f"x_{i}_{j}")
        for i in range(n_customers)
        for j in range(n_stores)
    }

    for i in range(n_customers):
        demand = customers[i]["demand"]
        solver.Add(sum(x[(i, j)] for j in range(n_stores)) == demand)

    for j in range(n_stores):
        capacity = stores[j]["capacity"]
        solver.Add(sum(x[(i, j)] for i in range(n_customers)) <= capacity * y[j])

    for i in range(n_customers):
        demand = customers[i]["demand"]
        for j in range(n_stores):
            solver.Add(x[(i, j)] <= demand * y[j])

    objective_terms = []
    for i in range(n_customers):
        cx = customers[i]["x"]
        cy = customers[i]["y"]
        for j in range(n_stores):
            sx = stores[j]["x"]
            sy = stores[j]["y"]
            distance = math.hypot(cx - sx, cy - sy)
            objective_terms.append(distance * x[(i, j)])

    for j in range(n_stores):
        objective_terms.append(stores[j]["fixed_cost"] * y[j])

    solver.Minimize(sum(objective_terms))
    status = solver.Solve()

    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise RuntimeError("No feasible solution found.")

    open_stores = [j for j in range(n_stores) if y[j].solution_value() > 0.5]
    assignments = {
        i: [(j, x[(i, j)].solution_value()) for j in range(n_stores) if x[(i, j)].solution_value() > 1e-6]
        for i in range(n_customers)
    }

    print("=== Dark Store Location Optimisation ===")
    print(f"Customers: {n_customers}")
    print(f"Stores: {n_stores}")
    print(f"Objective value: {solver.Objective().Value():.2f}")
    print(f"Open stores: {open_stores}")

    assigned_count = sum(1 for i in range(n_customers) if assignments[i])
    print(f"Assigned customers: {assigned_count}")

    plot_before_and_after(customers, stores, open_stores, assignments)

    return {
        "objective": solver.Objective().Value(),
        "open_stores": open_stores,
        "assignments": assignments,
    }


def main():
    parser = argparse.ArgumentParser(description="Dark store location optimization")
    parser.add_argument("--customers-file", default="dark_store_customers.csv", help="CSV file with customer_id,x,y,demand")
    parser.add_argument("--stores-file", default="dark_store_stores.csv", help="CSV file with store_id,x,y,fixed_cost,capacity")
    parser.add_argument("--n-customers", type=int, default=10000, help="Number of customers to generate if files do not exist")
    parser.add_argument("--n-stores", type=int, default=40, help="Number of candidate stores to generate if files do not exist")
    parser.add_argument("--generate-data", action="store_true", help="Generate a larger synthetic dataset first")
    args = parser.parse_args()

    if args.generate_data or (not os.path.exists(args.customers_file) or not os.path.exists(args.stores_file)):
        generate_large_dataset(args.customers_file, args.stores_file, args.n_customers, args.n_stores)

    customers = load_customers(args.customers_file)
    stores = load_stores(args.stores_file)
    solve_dark_store_location(customers, stores)


if __name__ == "__main__":
    main()
