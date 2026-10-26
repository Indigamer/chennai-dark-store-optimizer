# 📂 Chennai Dark Store Optimization — Sample Datasets

This directory contains **5 pre-validated test dataset pairs** designed for grading, testing, and demonstrating the **Chennai Dark Store Network Optimizer** application across multiple operating scales.

All locations represent authentic Chennai neighborhoods (Central/T. Nagar, Adyar, Velachery, Guindy, Anna Nagar, George Town, OMR, Ambattur, Porur) within coordinates `12.80°N–13.20°N` and `80.10°E–80.30°E`.

---

## 📋 Dataset Pairs Overview

| # | Pair Name | Customers | Stores | Total Demand | Total Capacity | Recommended Max Service Dist | Recommended Open Limit (P) |
|---|---|---|---|---|---|---|---|
| 01 | `15_Customers_4_Stores` | 15 | 4 | 283 ord/d | 711 ord/d | 8.0 – 12.0 km | 2 – 3 |
| 02 | `40_Customers_7_Stores` | 40 | 7 | 746 ord/d | 3,253 ord/d | 8.0 – 12.0 km | 2 – 6 |
| 03 | `100_Customers_12_Stores` | 100 | 12 | 1,650 ord/d | 5,937 ord/d | 8.0 – 12.0 km | 2 – 11 |
| 04 | `250_Customers_18_Stores` | 250 | 18 | 4,156 ord/d | 15,016 ord/d | 8.0 – 12.0 km | 2 – 17 |
| 05 | `500_Customers_25_Stores` | 500 | 25 | 8,495 ord/d | 31,929 ord/d | 8.0 – 12.0 km | 2 – 24 |

---

## 🚀 How to Use in the Web Application

1. Open the **Chennai Dark Store Optimizer** web application (locally via `streamlit run app.py` or online on Streamlit Community Cloud).
2. In the **left sidebar**, look for the **Upload Custom Data** section.
3. Upload the matching pair:
   - Drag & drop the `..._customers.csv` file into **Customer CSV**.
   - Drag & drop the `..._stores.csv` file into **Candidate-store CSV**.
4. Configure solver parameters (e.g. Max service distance = `10 km`, Transport cost = `0.25 ₹/order-km`, Revenue = `150 ₹/order`).
5. Click **Run optimization** for single-network assignment, or choose **Sensitivity analysis** to evaluate the complete Pareto frontier over open store limits ($P$).

---

## 📊 Scenario Descriptions

### 1. `01_Quick_Check_15_Customers_4_Stores`
- **Scale:** Small (15 micro-zones, 4 candidate dark stores).
- **Purpose:** Rapid smoke testing, visual inspection of assignments, and hand verification of solver outputs.
- **Expected Behavior:** Solves instantly (<0.02s). Demonstrates clear single-store or two-store coverage in central Chennai.

### 2. `02_Central_Core_40_Customers_7_Stores`
- **Scale:** Medium-Compact (40 customer zones, 7 candidate dark stores).
- **Purpose:** Testing core urban coverage trade-offs across central business districts (T. Nagar, Mylapore, Nungambakkam).
- **Expected Behavior:** Ideal for Sensitivity Analysis sweeping $P=2$ to $P=6$, clearly illustrating the diminishing return curve of adding facilities.

### 3. `03_Metro_Distribution_100_Customers_12_Stores`
- **Scale:** Realistic Metro Network (100 customer zones, 12 candidate stores).
- **Purpose:** Multi-hub urban-suburban logistics balancing central retail hubs against southern IT corridors (OMR, Velachery, Guindy).
- **Expected Behavior:** Excellent customer heatmap visualization, demand cluster separation, and capacity utilization metrics.

### 4. `04_Urban_Dense_250_Customers_18_Stores`
- **Scale:** Large High-Density (250 customer points, 18 candidate stores).
- **Purpose:** Heavy quick-commerce grocery delivery network with overlapping service radii.
- **Expected Behavior:** Displays rich geospatial heatmap gradients, complex Pareto frontiers, and clear distinction between optimal and dominated scenarios.

### 5. `05_Enterprise_Scale_500_Customers_25_Stores`
- **Scale:** Enterprise Planning (500 demand zones, 25 candidate stores).
- **Purpose:** Stress testing SCIP solver efficiency, vectorized distance calculation performance, and memory responsiveness.
- **Expected Behavior:** Solves in ~0.5 to 1.5 seconds. Shows deep network optimization with tight capacity allocation and multi-store load balancing.

---

## 📝 CSV Format Specifications

### Customer CSV (`..._customers.csv`)
```csv
customer_id,latitude,longitude,demand
C01,13.0418,80.2341,18
C02,13.0368,80.2676,12
...
```

### Candidate Store CSV (`..._stores.csv`)
```csv
store_id,latitude,longitude,fixed_cost,capacity
S01,13.0450,80.2320,2200,85
S02,13.0380,80.2650,1950,70
...
```
