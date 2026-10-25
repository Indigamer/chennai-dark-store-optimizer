# 🏬 Chennai Dark Store Network Optimizer

An advanced Operations Research (OR) and geospatial intelligence platform for quick-commerce dark store location-allocation, capacity planning, and multi-objective trade-off optimization in Chennai, India.

---

## 🌟 Key Features

1. **Capacitated Mixed-Integer Linear Programming (MIP)**:
   - Solves the fixed-charge facility location and customer-store assignment problem to mathematical optimality using the **SCIP** solver via **Google OR-Tools**.
   - Enforces facility capacity constraints, customer single/split delivery assignment, maximum coverage radius thresholds, and facility count bounds.

2. **Multi-Objective Sensitivity & Pareto Frontier**:
   - Sweeps open store limits ($P$) to generate the complete **Pareto Efficient Frontier**.
   - Quantifies the fundamental logistics trade-off between **Fixed Lease Overhead** and **Customer Transportation Costs**.
   - Interactive Plotly analytics with dark/light mode synchronization and an exportable scenario comparison matrix.

3. **Geospatial Intelligence & Leaflet Mapping**:
   - Interactive Folium map with theme-adaptive CartoDB tiles (`dark_matter` and `positron`).
   - Customer order density heatmap, candidate facility markers with dynamic hit targets, and road-network isochrone coverage.
   - Exact geometric polygon gap analysis highlighting unserviced urban regions.
   - Camera lock-on and one-click store focusing.

4. **Executive KPI Dashboard & Network Directory**:
   - 3-tier financial and operational cards: Net Profit, Total Revenue, Total Operating Cost, Fixed Lease Cost, Customer Transport Cost, Stores Opened, Demand Served, Avg Distance, and Mean Utilization.
   - Searchable and filterable **Dark Store Network Directory** with capacity progress bars for active facilities and instant "Show on map" camera centering.

5. **In-App Methodology Index**:
   - Detailed formulations, constraint definitions, solver tuning parameters, and business trade-off documentation.

---

## 🚀 How to Deploy on Streamlit Community Cloud (streamlit.io)

Follow these steps to deploy or access the application on [Streamlit Community Cloud](https://share.streamlit.io):

### Deployment Configuration
- **Repository**: `Indigamer/chennai-dark-store-optimizer`
- **Branch**: `main`
- **Main file path**: `app.py`
- **App URL**: `https://chennai-dark-store-optimizer.streamlit.app`

### Continuous Deployment (CI/CD)
Streamlit Cloud is linked to the `main` branch. Any future commit pushed to GitHub (`git push origin main`) will automatically trigger an instant hot-reload and redeploy of the live website within seconds.

### Environment & Secrets (Optional)
If you wish to pre-configure an OpenRouteService API key in Streamlit Cloud, go to **App Settings** -> **Secrets**:
```toml
ORS_API_KEY = "your-api-key-here"
```
*(Alternatively, operators can paste and update their API key anytime directly inside the web interface sidebar).*


---

## 💻 Running Locally

### Prerequisites
- Python 3.10, 3.11, or 3.12

### Installation
```bash
# Clone the repository
git clone https://github.com/<your-username>/<repo-name>.git
cd "Dark Store Optimization"

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Launch App
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## 🧪 Testing

Run the automated test suite (54 unit tests covering optimization models, routing adapters, geometry calculations, and session state lifecycles):

```bash
python -m unittest discover -s tests -v
```

---

## 📁 Repository Structure

```text
├── app.py                             # Main Streamlit web application & UI
├── optimization_model.py              # OR-Tools SCIP MIP formulation & distance matrices
├── sensitivity_analysis.py            # Multi-scenario solver & Pareto frontier engine
├── coverage_geometry.py               # Shapely coverage polygons & gap analysis
├── data_validation.py                 # CSV schemas & Chennai coordinate boundaries
├── routing_provider.py                # OpenRouteService road routing & isochrones
├── benchmark_scale.py                 # 10k customer scale benchmark script
├── requirements.txt                   # Deployment dependencies
├── .streamlit/
│   └── config.toml                    # Streamlit server and theme configuration
├── tests/                             # 54 passing unit tests
├── legacy/                            # Preserved planar Cartesian prototype
└── README.md                          # Project documentation
```

---

## 📄 License
MIT License. Developed for Operations Research and Supply Chain Network Design.
