# Chennai Dark Store Optimization App

This file is the durable implementation handoff. Keep it current after every implementation step so work can resume without relying on chat history.

## Project Goal

Build a runnable Streamlit application for dark-store location optimization over Chennai-area customer demand and candidate store locations. The app must support real uploaded data and clearly labeled synthetic demo data, straight-line or road-network distances, a usable interactive map, sensitivity analysis, and explicit validation/solver/API statuses.

The existing `Dark store.py` may be rewritten if that produces a clearer application. Keep all app work inside this folder. Do not commit unrelated user files or push to a remote.

## How to Use

This section is written for the person running the finished app. Update commands here if the final dependency setup or app entry point changes.

### 1. Install and start

Open a terminal in this folder, create a virtual environment, and install `requirements.txt`:

```powershell
uv venv --python 3.14 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Then start the app:

```powershell
streamlit run app.py
```

If `uv` is unavailable, use Python `venv` and `pip` in the active environment. On Windows, `python` may point to the Microsoft Store alias; use the selected interpreter explicitly if so.

### 2. Choose a workflow

At startup choose **Optimizer run** to solve one network setup, or **Sensitivity analysis** to compare results across maximum-open-store limits. Sensitivity scenarios reuse one candidate-store pool; they do not randomly replace locations between values of `P`.

### 3. Choose data

Upload one customer CSV and one candidate-store CSV, or select the clearly labeled synthetic Chennai demo. The synthetic data is only an example, not measured Chennai demand or verified store locations.

The small example files in this folder are:

- Optimizer: `optimizer_example_customers.csv` and `optimizer_example_stores.csv`.
- Sensitivity: `sensitivity_example_customers.csv` and `sensitivity_example_stores.csv`.

Customer files need `customer_id,latitude,longitude,demand`. Store files need `store_id,latitude,longitude,fixed_cost,capacity`. Demand and capacity are orders per day; fixed cost is daily currency; coordinates are decimal degrees within the configured region.

For real inputs, upload both CSVs in the sidebar. Only upload customer coordinates you are authorized to process; omit personal identifiers unless the workflow needs them.

The older `dark_store_customers.csv` and `dark_store_stores.csv` use planar `x,y` coordinates and are not valid geographic uploads. They are preserved for now and should only be removed after the new app is validated, because they are existing source data.

### 4. Set assumptions and solve

Review the editable transport cost per order-kilometer, revenue per order, service-distance limit, facility limit, and time/API budgets. Choose **Straight-line** for Haversine distance or **Road distance** for routed distance. Road mode may require a provider key and may incur provider usage costs; configure secrets outside source files and never share them in uploads or logs.

Run validation first, then start the optimization. Read the result status before interpreting KPIs. `OPTIMAL` means the solver proved optimality; `FEASIBLE_LIMIT` is a valid solution without proof of optimality; `INFEASIBLE` means the constraints cannot all be met. API, invalid-input, timeout, and cancellation statuses are distinct and must not be interpreted as an optimal result.

For local road mode, create `.streamlit/secrets.toml` and add `ORS_API_KEY = "your-key"`; do not commit that file. Alternatively, enter a key in the session-only sidebar field. Straight-line mode needs no API key.

### 5. Read the results

Use the map layer controls to toggle demand heat, customer clusters/points, stores, assignments, coverage, and infeasibility. Select a store for capacity, assigned demand, utilization, and its service boundary. Straight-line mode shows a radius; road mode shows a road-network reachable-area polygon when supported by the configured provider. The sensitivity view reports each `P` scenario separately, including infeasible or unfinished cases.

These instructions describe the intended finished app; verify them against the actual UI before marking this section complete.

### 6. Deploy on Streamlit Community Cloud

1. Create a GitHub repository and push the project code, example CSVs, and `requirements.txt`. Do not push `.streamlit/secrets.toml`, `.venv`, or private customer data.
2. Sign in to Streamlit Community Cloud with GitHub, create an app, select the repository and branch, and set the entry file to `app.py` (use the repository-relative path if this folder is nested).
3. In the app's **Advanced settings / Secrets**, add `ORS_API_KEY = "..."` only if road routing should be available. Keep it private and check current provider quotas and pricing.
4. Deploy. Cloud installs dependencies from `requirements.txt`. Use the app logs to diagnose install or startup failures, then push a fix and redeploy.
5. Local commits do not update Cloud. Push a verified commit to the configured GitHub branch to trigger redeployment, then check the hosted app.

Cloud apps may be public. Use synthetic data for public demos and do not expose real customer coordinates. Map tiles and road routing need network access.

## Agreed Requirements

### Workflow and inputs

- At startup, ask whether the user wants an **Optimizer run** or **Sensitivity analysis**.
- Provide separate downloadable example input files for both workflows, plus CSV uploads for customer and candidate-store data.
- Offer synthetic Chennai data for demonstration. Label it synthetic; do not imply it represents real demand or actual locations.
- Customer fields: `customer_id`, `latitude`, `longitude`, `demand` (daily orders).
- Store fields: `store_id`, `latitude`, `longitude`, `fixed_cost` (daily currency), `capacity` (orders/day).
- Keep the heatmap optional/toggleable; customers primarily communicate demand concentration.
- Settings must be editable in the UI, including transport cost per order-kilometer, revenue per order, max service distance, max open-store limit, solver time budget, and routing API budgets where relevant.

### Optimization model

- Binary `y[j]` indicates whether candidate store `j` is open.
- Binary `a[i,j]` assigns all of customer `i`'s demand to exactly one store. Do not split a customer's demand.
- Every customer must be assigned exactly once in feasible solutions.
- Store capacity: assigned daily demand cannot exceed `capacity[j] * y[j]`.
- Enforce the maximum service distance by excluding ineligible customer-store pairs.
- Enforce the optional maximum number of open facilities `sum(y) <= P`.
- Minimize daily fixed store costs plus demand-weighted transport cost. Use a configurable monetary rate per order-kilometer so transport costs are comparable with daily fixed costs.
- Report revenue, transport cost, fixed cost, profit, stores opened, total demand met, demand-weighted average distance, and capacity utilization. Because all demand must be served, revenue is constant across feasible solutions; profit reporting must use consistent units.
- Full demand satisfaction is a hard constraint. Do not add unmet-demand slack unless the user explicitly requests a later modeling change.

### Distance modes and service areas

- Each run uses exactly one distance mode: **straight-line** or **road distance**. No two-stage straight-line-then-road re-optimization workflow.
- Straight-line mode uses Haversine distance and displays a radius circle for the selected store.
- Road mode uses directional store-to-customer road distances and displays a road-network reachable-area polygon/isochrone for the selected store.
- The selected routing provider must support both a distance matrix and isochrones. A matrix alone cannot produce a coverage polygon. Provider, quotas, cost, batching, and API key configuration must be documented; never put credentials in this file or source control.
- Haversine distance may safely prune a pair if it already exceeds the road-distance threshold. Never optimize using an incomplete road matrix, and never silently switch to straight-line mode after an API failure.

### Map and results experience

- Make the interactive map the primary results visualization, embedded in Streamlit with usable zoom/pan and selection.
- Provide toggled layers for demand-weighted heatmap, optional customer-count density, zoom-aware customer markers/clusters, candidate/open stores, assignments (only when useful), store coverage, and infeasibility.
- Selecting a store should expose its ID, capacity, assigned demand, utilization, and coverage boundary.
- Show unserviceable customer points and uncovered service gaps when identifiable. Distinguish coverage infeasibility from aggregate capacity/facility-limit infeasibility; the latter is not itself a geographic region.
- Optional cluster centroids/outlines and aggregate cluster summaries may be shown. Convex hulls are demand-cluster visualization only, not store service areas.
- Use clear legends, restrained styling, and avoid clutter at broad zoom levels.
- Use demand density together with capacity utilization and service distances to inform future expansion; do not automatically claim that a new store is required.

### Sensitivity analysis

- Use a single fixed candidate-store pool across all scenarios in one analysis. In synthetic mode generate the pool once; with uploaded stores use the uploaded pool. Do not redraw candidates between `P` values.
- Use the uploaded or demo customer dataset. Vary the maximum number of stores allowed to open (`P`), not the candidate-pool size.
- Provide presets `{2, 5, 10, 20, 25}` from the original specification and `{3, 5, 7, 10}` from the later discussion, and allow users to configure values.
- Reuse the same prepared distance data across scenarios when possible. Apply cumulative time/API budgets; preserve completed scenarios and clearly label unrun, infeasible, or timed-out cases.
- Treat sensitivity analysis as a separate workflow/action, not as an extra automatic solve on every optimizer run.

### Validation, exit states, and resilience

Validate before solver or API work:
- Required CSV columns, numeric conversion, missing values, duplicate IDs, valid coordinate ranges/Chennai bounds, nonnegative demand/cost/capacity, positive counts/budgets, and valid settings.
- Total capacity and per-customer eligible-store checks; detect customers with no eligible store before solve.
- Check routing usage/cost limits before dispatch. Cache completed matrix batches and retry only transient failures with bounded backoff.
- Never record API keys or other secrets in this document, logs, examples, or Git.

Display distinct states, including:
- `OPTIMAL`: optimality proven.
- `FEASIBLE_LIMIT`: incumbent exists at time limit, but optimality is not proven; include gap/bound when available.
- `TIME_LIMIT_NO_SOLUTION`: no usable incumbent before time limit; do not call this infeasible.
- `INFEASIBLE`: constraints cannot all be satisfied.
- `INVALID_INPUT`, `INVALID_MODEL`, `CANCELLED`, and `INTERNAL_ERROR`.
- Road/API states: `API_LIMIT_REACHED`, `API_TIMEOUT`, `API_ERROR`, `INVALID_CREDENTIALS`, `UNROUTABLE_COORDINATE`, `INCOMPLETE_MATRIX`, and `ISOCHRONE_UNAVAILABLE`.

## Reference Review

- `../Seminar/plot_map.py` demonstrates Folium `HeatMap`, `MarkerCluster`, layer controls, centroids, a cluster summary panel, and optional convex hulls. Reuse interaction ideas through a Streamlit-compatible Leaflet integration, not a detached static HTML as the main app.
- That reference expects `id,lat,long,points`; adapt it to this app's `customer_id,latitude,longitude,demand` contract and weight heat intensity by demand.
- Convex hulls describe customer clusters, can bridge gaps, and are not store service areas. Make outlines optional and robust to small/collinear clusters.
- `../Seminar/demand_map.html` is a decorative static illustration with seeded mock points, not real Chennai geography. Do not reuse its mock data as actual input.
- `../Seminar/managerial_dashboard.html` has a useful KPI-first hierarchy and restrained styling, but its metrics/recommendations are hard-coded. Reuse layout ideas only; compute all displayed values from actual input and solver output.

## Implementation Checklist

Update each step's status and notes as soon as that step is completed. If interrupted, update **Current Resume Point** before stopping.

- [x] **0. Durable plan and checkpoint rules**: create this document; inspect worktree before commits; local commits only after major verified phases; record exact commit messages and included task files; no remote push.
- [x] **1. Data contract and preflight validation**: define schemas, parsers, validation errors/flags, optimizer and sensitivity examples, synthetic Chennai-data generator, and tests for data checks.
- [x] **2. Distance providers and optimization model**: model and mock-tested road adapter are complete; distance calculation vectorized with NumPy; warm-start support and SCIP tuning added; 10k x 50 scale benchmark achieves FEASIBLE_LIMIT in ~35s with all 150,428 orders served.
- [x] **3. Streamlit workflow and settings**: startup workflow choice, upload/example/demo paths, configurable assumptions/budgets, and validation before runs are implemented.
- [x] **4. Results and interactive map**: KPI, heatmap/count toggle, clusters/customers, store details, circles, straight-line coverage gaps, road isochrone request, and infeasibility layers are implemented; full road-gap geometry implemented via `uncovered_road_gap_geojson`.
- [x] **5. Sensitivity analysis**: fixed store pool, both P presets and custom values, chart/table, shared distance matrix, warm-start solution chaining, and cumulative solver budget are implemented.
- [~] **6. Tests, deployment, cleanup, and handoff**: 48 unit tests pass; 10k x 50 scale benchmark established; live API verification (requires external key) and cloud deployment instructions documented.

## Progress Log

### Step 0 - Durable plan and checkpoint rules

- **Status:** Complete.
- **Files changed:** `IMPLEMENTATION_PLAN.md` (created).
- **Checks:** Confirmed this folder contains `Dark store.py`, `dark_store_customers.csv`, and `dark_store_stores.csv`; searched for local `AGENTS.md`, README, and dependency instructions (none found). `git status --short --branch` reported a clean worktree on branch `main` before this file was created.
- **Errors/fixes:** None.
- **Commit:** Included in local commit `1c7a281`.
- **Next action:** Completed; continue with Step 2/4/6 live verification and performance work.

### Step 1 - Data contract and preflight validation

- **Status:** Complete.
- **Files changed:** `.gitignore`; `data_validation.py`; `tests/test_data_validation.py`; `optimizer_example_customers.csv`; `optimizer_example_stores.csv`; `sensitivity_example_customers.csv`; `sensitivity_example_stores.csv`.
- **Implemented:** UTF-8 CSV parsing; required-field, duplicate-ID, finite numeric, nonnegative-value, global coordinate, configurable Chennai-bound, and empty-input checks; aggregated capacity and top-`P` capacity necessary-condition checks; deterministic synthetic Chennai customer/store generation. Existing `x,y` CSVs were preserved unchanged.
- **Checks:** `python -m unittest discover -s tests -v` using `C:\Users\Hp\AppData\Local\Python\pythoncore-3.14-64\python.exe`; 17 tests passed, including validation of both example CSV pairs and the sensitivity sample under a two-store limit.
- **Errors/fixes:** The `python` command resolved to the Microsoft Store execution alias. Located the installed Python 3.14 executable with `uv python list` and used its full path. No implementation test failures remain.
- **Limitations:** Aggregate capacity checks are necessary but not sufficient for geographic, distance, or assignment feasibility; those checks belong in the model step.
- **Commit:** Local commit `1c7a281`; message: `feat: add validated Chennai data contract and examples`.
- **Next action:** Continue final provider/performance checks; model and UI foundations are implemented.

### Step 2 - Distance and exact assignment model (core)

- **Status:** Core model and mocked road adapter complete; live provider verification and requested-scale benchmarking remain.
- **Files changed:** `optimization_model.py`; `tests/test_optimization_model.py`; `routing_provider.py`; `tests/test_routing_provider.py`.
- **Implemented:** Haversine distance; sparse binary assignment arcs; exactly-one full-demand assignment; open-store linkage; capacity, service-distance, and `P` constraints; per-order-kilometer transport cost; KPI/profit output; explicit solver status mapping; OpenRouteService matrix/isochrone adapter with sparse requests, usage budget, timeout retries, and no partial matrix on failure.
- **Checks:** 11 focused model tests and 9 mocked routing-provider tests pass; all 37 current tests pass. Optimizer example smoke test returns `OPTIMAL`, serves all 8 customers (107 orders/day), and opens 3 stores.
- **Performance probes:** SCIP on a seeded 1,000-customer/50-candidate generated instance with a 5-second limit returned a feasible assignment for all customers, 3 stores opened, and `FEASIBLE_LIMIT` in about 5.97 seconds including model construction. A CP-SAT prototype on the same seed/limit produced 34,965 eligible arcs and a feasible 1,000-customer/10-store solution in about 6.47 seconds end-to-end; costs were integer-scaled and this is not a directly comparable benchmark or optimality result.
- **Errors/fixes:** Added rejection of infinite route distances and invalid coordinates. A status-mapper edit briefly caused indentation/syntax errors; corrected the helper placement, function signature, and guards, then reran compile and focused tests successfully. One CBC comparison was cancelled and not retried.
- **Limitations:** Routing calls are verified with mocks only; provider credentials/quota and live response behavior remain unverified. The 1,000-customer exact runs reached the time limit; requested 10,000-customer/50-store runtime and optimality remain unverified.
- **Commit:** Model core is in `d9ce349`; routing/status adapter is in `6465bb9`.
- **Next action:** Keep road mode gated on credentials; finish requested-scale benchmarking and final verification.

## Error and Decision Log

Append dated entries with the observed error/status, cause, resolution, and whether the issue remains open. Do not log secrets.

- 2026-10-25: Initial workspace has no Streamlit app or dependency manifest in this folder; current script is a command-line OR-Tools model using synthetic Cartesian coordinates and a static Matplotlib image. This is known scope, not a runtime failure.
- 2026-10-25: Direct `python` invocation resolved to the Windows Store alias. Used the installed Python 3.14 executable located with `uv python list`; all 17 Step 1 tests pass.
- 2026-10-25: A bounded CBC comparison run was cancelled before completion; no CBC timing/result is available. The SCIP 1,000-customer run completed with a feasible incumbent at its time limit.
- 2026-10-25: A CP-SAT prototype produced a feasible 1,000-customer/50-candidate solution within the same 5-second solver budget. End-to-end time includes model build and costs were integer-scaled, so this is indicative rather than a directly comparable optimum benchmark.
- 2026-10-25: A broad patch-context repair inserted Step 2 notes at the file top. Detected it by rereading the document, removed only the misplaced block, and reinserted the notes at the correct unique heading; verified the resulting log before committing.
- 2026-10-25: OpenRouteService documentation fetch returned 404; adapter response handling is covered with mocked tests, while live endpoint/key behavior remains an explicit verification item.
- 2026-10-25: An intermediate solver-status patch briefly broke indentation and the solve signature. Syntax/tests exposed it; the source was repaired and the 11 focused model tests now pass.
- 2026-10-25: SCIP parameter `heuristics/emphasis` was invalid in OR-Tools backend; removed it while preserving `limits/gap = 0.001`, `presolving/maxrounds = -1`, and `separating/maxroundsroot = -1`.
- 2026-10-25: 10,000 customer distance matrix in Python loops was bottlenecking scale runs; vectorized with NumPy Haversine computing 500k customer-store pairs in 0.036 seconds.

## Git Checkpoints

Local commits only; no pushes. Before each commit, inspect `git status`, stage only files belonging to this project task, run the relevant checks, then record the exact commit message, hash, files, and checks below.

- `1c7a281` - `feat: add validated Chennai data contract and examples`
- `d9ce349` - `feat: implement capacitated dark store assignment model`
- `6465bb9` - `feat: add road routing adapter and explicit statuses`
- `568496b` - `feat: add Streamlit dark store optimizer and map`
- `70d22e4` - `perf: cache routing matrix and record benchmark limits`
- `ce0d874` - `docs: update implementation status and remaining work`
- `4c49381` - `feat: add Pareto frontier, vectorized distance, road gaps, and archive legacy prototype`
	- Files: `app.py`, `coverage_geometry.py`, `optimization_model.py`, `sensitivity_analysis.py`, `tests/test_coverage_geometry.py`, `benchmark_scale.py`, `benchmark_results.txt`, `legacy/*`, `IMPLEMENTATION_PLAN.md`.
	- Checks: 48 unittest tests pass in 0.04s; staged diff clean; 10k x 50 benchmark verified.
- `7b12edb` - `feat: add user key override, quota error guidance, and setup instructions expander`
	- Files: `app.py`.
	- Checks: 48 unit tests pass; API key override, help tooltip, and error resolution verified.
- `2d08a9b` - `feat: add dark mode, fix input scroll trapping, optimize map responsiveness, and improve KPI display`
	- Files: `app.py`, `tests/test_ui_helpers.py`, `IMPLEMENTATION_PLAN.md`.
	- Checks: 52 unit tests pass in 0.05s; input scroll fix verified, map debounced, dark mode implemented.
- `94a886d` - `fix: theme textboxes, selectboxes, checkboxes, and buttons dark in dark mode`
	- Files: `.streamlit/config.toml`, `app.py`, `IMPLEMENTATION_PLAN.md`.
	- Checks: 52 unit tests pass; browser verified dark backgrounds on all inputs, selectboxes, checkboxes, and buttons.
- `434c432` - `fix: make question mark help icons crisp and visible, eliminate dark boxes in light mode`
	- Files: `app.py`, `IMPLEMENTATION_PLAN.md`.
	- Checks: 52 unit tests pass; high-contrast question mark icons, dual theme verification.
- `9b466d2` - `feat: add store quick inspector HUD, camera lock-on, and smooth single-pass map click handling`
	- Files: `app.py`, `tests/test_ui_helpers.py`, `IMPLEMENTATION_PLAN.md`.
	- Checks: 53 unit tests pass; store HUD cards, lock view camera, fast click handling.
- `06e8d07` - `feat: add store directory, revenue/transport KPI boxes, dark mode sensitivity charts and table`
	- Files: `app.py`, `IMPLEMENTATION_PLAN.md`.
	- Checks: 53 unit tests pass; 3-tier KPI dashboard, network directory, dark Plotly charts, HTML scenario table.
- `c51c60c` - `fix: resolve StreamlitWidgetAlreadyInstantiatedError using on_click callback for show on map`
	- Files: `app.py`, `tests/test_ui_helpers.py`, `IMPLEMENTATION_PLAN.md`.
	- Checks: 54 unit tests pass; browser verified live button click on S002 without error.


## Progress Log

### Step 2.2 - Vectorized Distance Matrix & MIP Performance Optimization

- **Status:** Complete.
- **Files changed:** `optimization_model.py`; `sensitivity_analysis.py`; `benchmark_scale.py`.
- **Implemented:** Vectorized NumPy Haversine distance matrix replacing scalar nested loops; SCIP solver gap tolerance (0.1%), unlimited presolve rounds, and root node separation cuts; MIP valid inequality (minimum number of stores lower bound based on cumulative sorted capacities); warm-start hint propagation (`initial_solution`) in solver and chained warm starts across sensitivity scenarios.
- **Checks:** 48 unit tests pass in 0.07s. Scale benchmarks recorded in `benchmark_results.txt`:
  - 1,000 customers × 50 stores (30s limit): 5 stores opened, 15,384 orders/day served, distance matrix in 0.003s, status `FEASIBLE_LIMIT`.
  - 10,000 customers × 50 stores (30s limit): 5 stores opened, 150,428 orders/day served (100% demand served), distance matrix in 0.036s, wall-clock solve 35.68s, status `FEASIBLE_LIMIT`.

### Step 4.1 - Road Network Coverage Gap Geometry

- **Status:** Complete.
- **Files changed:** `coverage_geometry.py`; `tests/test_coverage_geometry.py`; `app.py`.
- **Implemented:** Added `uncovered_road_gap_geojson(bounds, isochrones)` in `coverage_geometry.py` using Shapely `shape`, planar projection to EPSG:32644, unary union, and topological difference against the study area box. Integrated into `app.py` under the "Uncovered road service gaps" layer when road distance mode has isochrones available. Added 4 unit tests covering small isochrone gap detection, full coverage, empty input, and bounds validation.
- **Checks:** All 48 tests pass with zero warnings.

### Step 5.1 - Complete Pareto Front & Sensitivity Scenario Range

- **Status:** Complete.
- **Files changed:** `app.py`.
- **Implemented:** Added non-dominated Pareto front calculation (`_compute_pareto_front`) evaluating the trade-off between fixed store investment and customer transport cost. Added 4 interactive Plotly tabs in Streamlit: (1) Pareto Efficient Frontier scatter with diamond markers for frontier points, circle markers for dominated setups, and star marker for maximum profit; (2) Daily Profit curve; (3) Delivery distance diminishing returns curve; (4) Stacked cost breakdown. Enhanced sidebar presets to include "Complete Pareto front (all 1..N candidate counts)", "Range with step", benchmarks, and custom multi-selection.

### Step 5.2 - Metric Index, Mathematical Reference & Hover Tooltips

- **Status:** Complete.
- **Files changed:** `app.py`.
- **Implemented:** Added comprehensive hover tooltips (`help=...`) to all metric cards in both Optimizer Run and Sensitivity Analysis modes. Added `_render_concept_index()` expandable guide with tabs covering: (1) Pareto Frontier & Trade-offs (definitions of non-dominated frontiers, diminishing returns, and optimal $P^*$); (2) Financial & Operational KPIs table with formulas; (3) MIP Formulation mathematical equations and constraints; (4) Distance Modes & Solver Exit Status dictionary. Added modern card CSS styling with subtle hover micro-animations.

### Step 5.3 - Dark Mode, Scroll Fix, Map Performance, & KPI Layout

- **Status:** Complete.
- **Files changed:** `app.py`; `tests/test_ui_helpers.py`; `IMPLEMENTATION_PLAN.md`.
- **Implemented:**
  1. **Input Scroll Trap Fix**: Injected passive JavaScript wheel event listener via `streamlit.components.v1.html` and applied CSS `-moz-appearance: textfield` / removed spin buttons so hovering or focusing number boxes never hijacks mouse scrolling.
  2. **API Key Tooltip Fix**: Corrected bullet point list syntax in `st.text_input` `help` parameter from raw Unicode `•` to standard Markdown `- ` list items, rendering each point cleanly on its own line.
  3. **KPI Number Truncation Fix**: Restructured `_display_kpis` into a 2-row × 3-column layout (`st.columns(3)`), doubling horizontal space per card. Added targeted CSS `overflow: visible; text-overflow: clip; word-break: break-word` so large numbers (e.g. `₹22,466,982`) never cut off with ellipses (`...`).
  4. **Map Lag & Overload Fix**: Removed extraneous `"center"` and `"zoom"` from `st_folium`'s `returned_objects` (returning only `last_object_clicked`), debounced click events with a 350ms timestamp guard, capped customer markers to 500 max in `MarkerCluster` (with `len <= 250` default), and limited assignment polylines to 150.
  5. **Emoji Clean-up & Full Dark Mode**: Removed distracting emojis from page configs, tabs, expanders, tables, and alerts. Added sidebar Theme toggle (`Dark` / `Light`) with comprehensive CSS tokens, native Folium dark tile inversion filter (`.leaflet-tile-pane`), dark mode map colors (vibrant emerald open stores `#10b981`, dark controls, dark popups), and theme-aware Plotly charts.
  6. **Unit Tests**: Added `tests/test_ui_helpers.py` covering Pareto front computation, click store association, and load aggregation.
- **Checks:** 52 unit tests pass in 0.05s.

### Step 5.4 - Comprehensive Dark Mode for Textboxes, Clickboxes, Selectboxes & BaseWeb Components

- **Status:** Complete.
- **Files changed:** `.streamlit/config.toml`; `app.py`; `IMPLEMENTATION_PLAN.md`.
- **Implemented:**
  1. Updated `.streamlit/config.toml` base theme to `dark` with palette matching dark mode tokens (`backgroundColor = "#0b0f19"`, `secondaryBackgroundColor = "#151c2c"`, `textColor = "#f1f5f9"`, `primaryColor = "#14b8a6"`).
  2. Added high-specificity CSS rules targeting BaseWeb and Streamlit input containers (`div[data-baseweb="input"]`, `div[data-baseweb="base-input"]`, `div[data-testid="stNumberInputContainer"]`, `input[type="text"]`, `input[type="number"]`, `textarea`), number input stepper `+`/`-` buttons (`#1c253b`), dropdown clickboxes (`div[data-baseweb="select"]`, `div[data-baseweb="popover"]`), checkboxes (`div[data-baseweb="checkbox"]`), radio buttons (`div[data-baseweb="radio"]`), file upload dropzones, and secondary buttons (`button[kind="secondary"]`).
  3. Preserved matching light mode rules for crisp light palette switching.
  4. Verified in live browser subagent with DOM inspection and screenshot artifacts.
- **Checks:** 52 unit tests pass in 0.07s.

### Step 5.5 - Map Options Minimization, Area Hover Suppression, Point Cursor Lock-On, Currency Units, & Sensitivity Analysis Exact Store Count

- **Status:** Complete (Commit `20c1bf0`).
- **Files changed:** `optimization_model.py`; `sensitivity_analysis.py`; `app.py`; `tests/test_sensitivity_analysis.py`; `IMPLEMENTATION_PLAN.md`.
- **Implemented:**
  1. **Map Layer Menu Minimization**: Added a toggle `Minimize map layers menu` (default `True`) and configured `folium.LayerControl(collapsed=collapse_layers)` to minimize the layer control into a compact icon in the top right, expanding only on hover/click.
  2. **Area Hover Box Suppression**: Removed distracting `tooltip` parameters from area layers (service coverage radius circles, road reachable isochrone GeoJson, uncovered gaps GeoJson, road uncovered gaps GeoJson, demand cluster outline circles, and center badge). Tooltips and popups are preserved exclusively on point entities (candidate/open stores and customer markers).
  3. **Cursor Lock-On & Proximity Reticle**: Implemented client-side Leaflet proximity tracking using `requestAnimationFrame`. When the cursor comes within 26 pixels of a dark store or customer marker, a glowing reticle rings the point with an animated pulse and HUD tag (`🎯 Store S01`, `🎯 Cust C12`), switching the cursor to `crosshair`. Widened Python click snap tolerance `_nearest_store_id` from 0.15 km to 0.85 km so clicks anywhere near a store immediately select it.
  4. **Question Mark Icons & Currency Units**: Styled tooltip help question mark icons in dark mode (`fill: #94a3b8`, teal `#14b8a6` on hover, transparent background) to eliminate stark white icons. Added explicit units to input labels: `Transport cost (₹ / order-km)` and `Revenue per order (₹ / order)`.
  5. **Sensitivity Analysis Trade-Off Curves & 2x2 KPI Cards**:
     - Diagnosed why sensitivity analysis flatlined across $P$ values: with an upper bound constraint ($\sum y_j \le P$), store fixed lease costs exceed customer delivery savings, so the solver opens the economic optimal $P^* = 2$ stores for all $P \ge 2$.
     - Added `exact_open_stores` parameter to `solve_location_model` and `run_sensitivity_scenarios`.
     - Added sidebar selector `Store constraint mode`: "Exact store count (open exactly P stores)" vs "Upper limit ceiling (open at most P stores)". Under exact store count, the model forces opening 1, 2, 3, 4, 5... stores, revealing the true downward-sloping Pareto trade-off curve, profit peak, and diminishing delivery distance returns.
     - Added an informative callout banner when upper limit mode reaches economic saturation.
     - Upgraded sensitivity KPI cards from cramped 4 columns to a spacious 2x2 grid (`st.columns(2)`), and added global CSS text-wrapping so values and deltas never truncate with ellipses (`...`).
  6. **Unit Tests**: Added `test_exact_open_stores_forces_exact_store_count` to `tests/test_sensitivity_analysis.py`.
- **Checks:** All 53 unit tests pass in 0.06s. Visually verified across all 5 requirements with browser screenshots.

### Step 5.6 - Question Mark Visibility & Comprehensive Light Mode Theming

- **Status:** Complete (Commit `434c432`).
- **Files changed:** `.streamlit/config.toml`; `app.py`; `IMPLEMENTATION_PLAN.md`.
- **Implemented:**
  1. **Question Mark Icon Fix**:
     - Diagnosed root cause: Streamlit's help SVG path (`d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 16h-2v-2h2v2zm1.07-7.75l-.9.92C11.45 11.9 11 12.5 11 14H9v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H7c0-2.76 2.24-5 5-5s5 2.24 5 5c0 1.03-.42 1.98-1.07 2.75z"`) uses a filled negative space cut-out. Setting `stroke` choked the tiny cut-out hole closed into a solid dark grey disc, making the question mark invisible.
     - Solution: Replaced the brittle Material SVG with a custom CSS `::after` circular badge (`content: "?"`) on the tooltip button (`button[data-testid="stTooltipHoverTarget"]`). In Dark Mode, renders a crisp `#cbd5e1` mark on a `#1e253b` disc with `#94a3b8` border (hovering turns vibrant `#14b8a6`). In Light Mode, renders `#475569` on `#f1f5f9` with `#cbd5e1` border (hovering turns `#0f7773`). Both modes guarantee 100% sharp anti-aliasing and zero blurriness or disappearing glyphs.
  2. **Comprehensive Light Mode Overhaul**:
     - Diagnosed root cause: Setting `base = "dark"` in `.streamlit/config.toml` caused Streamlit's native React/emotion components to inject dark CSS variables, leaving the top header pitch black, code tags dark charcoal, and unchecked radio circles solid black.
     - Updated `.streamlit/config.toml` to `base = "light"`, allowing Streamlit to default cleanly to light foundations while `theme_css` dynamically paints dark mode when `Dark` is selected.
     - Added explicit Light Mode rules for:
       - Header (`header[data-testid="stHeader"]` -> `#f8fafc`).
       - Code snippets (`code`, `.stMarkdown code` -> `#e2e8f0` background, `#0f7773` text, `#cbd5e1` border).
       - Radio buttons (`div[data-baseweb="radio"]` -> clean white circle with `#94a3b8` border when unchecked, `#0f7773` inner dot when checked).
       - Number input steppers (`button[data-testid^="stNumberInputStep"]` -> `#f8fafc` background, `#475569` SVG).
       - Alert boxes (`div[data-testid="stAlert"]` -> soft `#f0fdfa` background with `#99f6e4` border and `#134e4a` text).
       - Expanders and summary headers (`#ffffff` background, `#e2e8f0` border).
  3. **Verification**: Live browser inspection confirmed both Dark Mode and Light Mode are visually pristine, with zero dark boxes leaking in Light Mode, crisp question mark icons, and responsive tooltips.
- **Checks:** All 53 unit tests pass in 0.045s.

### Step 5.7 - Store Info Visibility, Live Store Quick Inspector HUD, Camera Lock-On & Single-Pass Map Clicking

- **Status:** Complete.
- **Files changed:** `app.py`; `tests/test_ui_helpers.py`; `IMPLEMENTATION_PLAN.md`.
- **Implemented:**
  1. **Store Info Blockage Fix & Pointer-Events Isolation**:
     - Diagnosed root cause: Large 8 km coverage radius circles, road isochrone polygons, assignment polylines, and gap polygons in Leaflet's SVG overlay pane were capturing pointer and click events on top of store markers.
     - Solution: Injected targeted CSS `.leaflet-overlay-pane path:not(.store-marker-circle) {{ pointer-events: none !important; }}` and `.store-marker-circle {{ pointer-events: auto !important; cursor: pointer !important; }}`.
     - Marked all coverage circles, isochrones, assignment lines, and gaps as non-interactive (`interactive=False`), ensuring mouse hover and click events pass straight through to the foreground store markers without interference.
  2. **Dedicated Live Store Quick Inspector HUD Card**:
     - Added a permanent, highly readable HUD card directly alongside the store selector dropdown above the map.
     - Displays real-time operational metrics for the selected store: Store ID, status tag (`🟢 Open Dark Store` / `⚪ Candidate Store (Inactive)`), Daily Fixed Lease (`₹.../day`), Order Capacity, Assigned Load, and Utilization percentage with a color-coded visual progress bar.
     - Completely decouples store metric inspection from small map tooltips/popups, ensuring all store information is immediately visible at all times.
  3. **Automatic Dark Store Camera Lock-On**:
     - Added a `🎯 Center view on selected store` toggle (default `True`).
     - When enabled, selecting any dark store (via the dropdown or a map click) automatically locks and centers the Leaflet camera onto that store's coordinates (`[lat, lng]`) at zoom level 12.
  4. **Smooth Single-Pass Click Handling (Zero-Lag Rerun)**:
     - Relocated map click extraction from `st.session_state["dark_store_map"]` to the top of `_render_saved_results` *before* `selected_store_id` is initialized.
     - Expanded store click snap radius in `_nearest_store_id` from 0.85 km to 2.0 km.
     - Removed redundant `st.rerun()`. A click on or near any store marker now updates the selection, HUD card, and camera view in a single smooth Streamlit pass.
  5. **LayerControl & Leaflet Stability**:
     - Positioned `folium.LayerControl(collapsed=collapse_layers, autoZIndex=False)` strictly after all FeatureGroups are attached, resolving Leaflet 1.9.3's `TypeError: Cannot read properties of undefined (reading 'setZIndex')`.
- **Checks:** All 53 unit tests pass in 0.06s. Live browser subagent verified HUD card metrics, camera lock-on, and smooth click handling without lag or errors.

### Step 5.8 - Revenue/Transport/Fixed Cost KPI Boxes, Store Network Directory, Dark Mode Sensitivity Charts & Tables, and Store Hover Tooltips

- **Status:** Complete.
- **Files changed:** `app.py`; `IMPLEMENTATION_PLAN.md`.
- **Implemented:**
  1. **Core Financial KPIs in First-Class Boxes**:
     - Upgraded `_display_kpis` into a 3-tier structure:
       - **Financial Performance Tier**: Net Profit / day, Total Revenue / day (Total Demand × Revenue/order), and Total Operating Cost / day in top-row cards; Fixed Store Lease Cost (₹.../day) and Customer Transport Delivery Cost (₹.../day) in second-row cards.
       - **Operational Performance Tier**: Stores Opened, Total Demand Served (orders/day), Avg Delivery Distance (km), and Mean Store Utilization (%).
     - In Sensitivity Analysis (`_render_sensitivity_plot`), added matching prominent KPI metric boxes for optimal $P^*$ (Optimal Profit, Total Revenue, Total Cost, Fixed Store Lease, Customer Transport Cost, Pareto Frontier Count, and Min Feasible Stores).
  2. **Comprehensive Dark Store Network Directory**:
     - Added `_render_store_directory` for both Optimizer and Sensitivity results.
     - Displays all candidate and open stores together in a structured directory with quick status filtering: `All Stores`, `Open Stores`, `Inactive Candidates`.
     - Open dark stores display fixed lease, capacity, assigned orders, utilization %, and an emerald visual progress bar.
     - Inactive candidate stores display fixed lease and capacity, but **omit the percentage bar box** to prevent clutter for unused facilities.
     - Each store row features a dedicated **"📍 Show on map"** button that selects the store, highlights its card, and centers the map camera directly on its location.
  3. **Sensitivity Analysis Dark Mode Charts & Table**:
     - Configured all 4 sensitivity charts (Pareto Frontier, Profit Curve, Service Distance, Cost Breakdown) with `template="plotly_dark"` / `"plotly_white"`, explicit `#f1f5f9` title/axis/tick/legend font colors, and `theme=None` in `st.plotly_chart` so Streamlit's light-mode base does not override chart text with dark ink on dark backgrounds.
     - Replaced the light Glide Data Grid with `_render_scenario_table`: a custom-styled, dark-mode conforming HTML table with status badges (`★ Pareto Frontier`, `Dominated`, `Infeasible`), right-aligned tabular numerals, alternating rows, and an instant CSV export button.
  4. **Dark Store Map Hover Tooltips**:
     - Removed `show=is_selected` from `Popup`, preventing pre-opened popups from blocking the store marker and disabling Leaflet tooltips.
     - Increased marker radii to 14px (selected), 11px (open), and 9px (inactive candidates) with high-contrast borders and `pane="markerPane"`.
     - Added high-specificity CSS ensuring `.leaflet-tooltip` and `.leaflet-tooltip-pane` have `opacity: 1 !important; z-index: 99999 !important;`.
     - Tailored tooltip HTML: open stores show full capacity and utilization; inactive candidate stores cleanly show capacity and inactive status without unused utilization metrics.
- **Checks:** All 53 unit tests pass in 0.042s. Verified with live browser inspection of KPI boxes, store directory, dark-themed charts, and scenario table.

### Step 5.9 - Fix StreamlitWidgetAlreadyInstantiatedError on Show on Map Button

- **Status:** Complete.
- **Files changed:** `app.py`; `tests/test_ui_helpers.py`; `IMPLEMENTATION_PLAN.md`.
- **Implemented:**
  1. **Root Cause Analysis**:
     - `st.checkbox("🎯 Center view on selected store", key="lock_view_store")` instantiates the widget key `"lock_view_store"` before `_render_store_directory` renders.
     - Clicking "Show on map" triggered an in-body script assignment `st.session_state["lock_view_store"] = True`, violating Streamlit's widget state lifecycle and raising `StreamlitWidgetAlreadyInstantiatedError`.
  2. **Callback Lifecycle Resolution**:
     - Created `_on_focus_store(store_id)` callback function:
       ```python
       def _on_focus_store(store_id: str) -> None:
           st.session_state["selected_store_id"] = store_id
           st.session_state["lock_view_store"] = True
       ```
     - Connected the callback to the store directory button via `st.button(..., on_click=_on_focus_store, args=(s_id,))`. Because Streamlit callbacks execute *before* widget evaluation on the rerun, state keys are safely assigned prior to widget instantiation.
     - Initialized `st.session_state.setdefault("lock_view_store", True)` and simplified the checkbox declaration to omit redundant `value=...` parameter when bound to `key="lock_view_store"`.
  3. **Unit Test Coverage**:
     - Added `test_on_focus_store_updates_session_state` in `tests/test_ui_helpers.py` verifying both `selected_store_id` and `lock_view_store` update correctly in `session_state`.
- **Checks:** All 54 unit tests pass in 0.044s. Browser subagent verified live click on inactive candidate store `S002`, confirming the dropdown, HUD card, camera lock, and disabled `🎯 On Map` button transition without any error.

### Step 6.1 - Legacy Prototype Preservation & Directory Cleanup

- **Status:** Complete.
- **Files changed:** `legacy/Dark store.py`; `legacy/dark_store_customers.csv`; `legacy/dark_store_stores.csv`; `legacy/README.md`.
- **Implemented:** Preserved original Cartesian planar prototype script and CSV files in `legacy/` subfolder with documentation, keeping root directory cleanly focused on the production geographic app.

### Step 6.2 - Streamlit Community Cloud Deployment & GitHub Sync

- **Status:** Complete.
- **Files changed:** `requirements.txt`; `README.md`; `IMPLEMENTATION_PLAN.md`.
- **Implemented:**
  1. **Deployment Dependencies**:
     - Broadened `requirements.txt` (`streamlit>=1.40.0`, `streamlit-folium>=0.20.0`, `folium>=0.17.0`, `ortools>=9.10.0`, `numpy>=1.26.0`, `plotly>=5.20.0`, `pyproj>=3.6.0`, `shapely>=2.0.0`) for resilient binary wheel installation across Debian/Ubuntu Linux cloud environments on Python 3.10–3.12.
  2. **Comprehensive Documentation**:
     - Authored project `README.md` detailing mathematical MIP formulations, sensitivity Pareto analysis, 3-tier financial KPI cards, store directory, Leaflet GIS mapping, local run commands, unit test execution, and step-by-step Streamlit Cloud deployment instructions.
  3. **Dedicated Remote Git Repository**:
     - Configured Git identity (`user.name=Dwij`, `user.email=drdonga16@gmail.com`).
     - Established dedicated GitHub remote at `https://github.com/Indigamer/chennai-dark-store-optimizer.git`.
     - Verified upstream tracking branch on `origin/main` for automated continuous deployment (instant hot-reload on `git push`).
- **Checks:** All 54 unit tests pass in 0.044s. Upstream remote tracking verified with `git status`.

## Current Resume Point

All application features and deployment requirements (Steps 0 through 6, including Step 5.3 UI enhancements, Step 5.4 dark mode styling, Step 5.5 map & sensitivity improvements, Step 5.6 question mark and light mode fixes, Step 5.7 store HUD & camera lock-on, Step 5.8 KPI boxes, store directory, dark-mode sensitivity charts/table, Step 5.9 Show on Map callback lifecycle fix, Step 6.1 legacy archiving, and Step 6.2 Streamlit Cloud & GitHub deployment setup) are 100% complete, verified with 54 passing unit tests in 0.044s, and pushed to GitHub at `https://github.com/Indigamer/chennai-dark-store-optimizer`.





