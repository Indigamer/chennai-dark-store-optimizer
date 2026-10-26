# 📂 Chennai Dark Store Optimization — Sample Datasets

This directory contains **8 calibrated, pre-validated test dataset pairs** designed for grading, testing, and demonstrating the **Chennai Dark Store Network Optimizer** application across all operating tiers — from smoke tests to the **flagship 10,000 customer × 50 candidate dark store** benchmark.

All locations represent authentic Chennai neighborhoods (Central/T. Nagar, Adyar, Velachery, Guindy, Anna Nagar, George Town, OMR, Ambattur, Porur, Madhavaram, Tambaram) within coordinates `12.80°N–13.20°N` and `80.10°E–80.30°E`.

---

## 📋 Complete Dataset Pairs Overview

| # | Pair Name | Customers | Stores | Total Demand | Total Capacity | Recommended Max Service Dist | Recommended Sensitivity Limit ($P$) | Evaluation Focus |
|---|---|---|---|---|---|---|---|---|
| **01** | `01_Quick_Check_15_Customers_4_Stores` | **15** | **4** | 283 ord/d | 711 ord/d | 8 – 12 km | 2 – 3 | Quick verification, hand verification of assignments |
| **02** | `02_Central_Core_40_Customers_7_Stores` | **40** | **7** | 746 ord/d | 3,253 ord/d | 8 – 12 km | 2 – 6 | Central Chennai (T. Nagar/Mylapore), smooth Pareto curve |
| **03** | `03_Metro_Distribution_100_Customers_12_Stores` | **100** | **12** | 1,650 ord/d | 5,937 ord/d | 8 – 12 km | 3 – 10 | Multi-hub metro distribution, heatmap visualization |
| **04** | `04_Urban_Dense_250_Customers_18_Stores` | **250** | **18** | 4,156 ord/d | 15,016 ord/d | 8 – 12 km | 4 – 15 | Heavy grocery network, overlapping radii, rich trade-offs |
| **05** | `05_Enterprise_Scale_500_Customers_25_Stores` | **500** | **25** | 8,495 ord/d | 31,929 ord/d | 8 – 12 km | 5 – 20 | Enterprise planning, multi-store load balancing |
| **06** | `06_Sub_Regional_1500_Customers_30_Stores` | **1,500** | **30** | 22,500 ord/d | 145,000 ord/d | 8 – 12 km | 6 – 22 | Sub-regional network, clear P < 5 capacity boundary |
| **07** | `07_Regional_City_4000_Customers_40_Stores` | **4,000** | **40** | 60,000 ord/d | 420,000 ord/d | 8 – 12 km | 8 – 30 | Greater Chennai metropolis, deep Pareto frontier sweep |
| **08** | `08_Flagship_Scale_10000_Customers_50_Stores` | **10,000** | **50** | 150,000 ord/d | 1,100,000 ord/d | 8 – 10 km | 10 – 35 | Flagship 10k x 50 milestone benchmark, 500k pair matrix |

---

## 🚀 How to Use in the Web Application

1. Open the **Chennai Dark Store Optimizer** web application (locally via `streamlit run app.py` or online on Streamlit Community Cloud).
2. In the **left sidebar**, look for the **Upload Custom Data** section.
3. Upload the matching pair:
   - Drag & drop the `..._customers.csv` file into **Customer CSV**.
   - Drag & drop the `..._stores.csv` file into **Candidate-store CSV**.
4. Configure solver parameters:
   - **Max service distance**: `8.0 – 12.0 km` (recommended `8.0 – 10.0 km` for high scales).
   - **Transport cost**: `0.25 ₹ / order-km`.
   - **Revenue per order**: `150.00 ₹ / order`.
5. Choose your workflow:
   - **Run optimization**: For single-network assignment, KPI metrics, interactive map, and store directory.
   - **Sensitivity analysis**: To sweep open store limits ($P$) and generate the complete Pareto efficient frontier.

---

## 🎯 Sensitivity Analysis Guidance for High-Scale Datasets

### For Pair 06 (`1,500 Customers × 30 Stores`)
- **Capacity Infeasibility Threshold**: $P < 5$ stores is capacity-constrained (`INFEASIBLE`).
- **Feasible Frontier**: $P = 5, 6, 8, 10, 12, 15, 20$.
- **Expected Behavior**: Demonstrates how adding facilities initially boosts profit by cutting delivery transport distances, peaking around $P=7–9$, before fixed lease costs cause diminishing returns.

### For Pair 07 (`4,000 Customers × 40 Stores`)
- **Capacity Infeasibility Threshold**: $P < 7$ stores is capacity-constrained.
- **Feasible Frontier**: $P = 7, 8, 10, 12, 15, 20, 25$.
- **Expected Behavior**: Spans the entire greater metropolitan area, displaying rich customer clustering and distinct trade-offs between transport and lease costs.

### For Pair 08 (`10,000 Customers × 50 Stores` — Flagship Milestone)
- **Scale & Complexity**: 500,000 customer-store potential assignment pairs.
- **Vectorized Haversine Speed**: Prunes and builds the entire distance matrix in **~0.035 seconds** via NumPy vectorization.
- **Recommended Sensitivity Scenarios**: $P = 8, 10, 12, 15, 20, 25$.
- **Recommended Time Limit**: 30 – 60 seconds per run (or standard default).
- **Expected Behavior**: Demonstrates enterprise-scale operations research, achieving near-zero optimality gaps with multi-million rupee daily profit optimizations.

---

## 📝 CSV Format Specifications

### Customer CSV (`..._customers.csv`)
```csv
customer_id,latitude,longitude,demand
C00001,13.0418,80.2341,18
C00002,13.0368,80.2676,12
...
```

### Candidate Store CSV (`..._stores.csv`)
```csv
store_id,latitude,longitude,fixed_cost,capacity
S01,13.0450,80.2320,2800,24000
S02,13.0380,80.2650,2450,22500
...
```
