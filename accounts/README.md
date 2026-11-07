# FISP Supply Chain Optimization System — Project Scaffold

This is your starting Django project, pre-wired with the recommended stack:

- Django 5.1.15 (backend + templates, auth/RBAC via built-in `auth` app)
- Bootstrap 5.3 (CDN, no npm needed)
- Chart.js 4.4 (CDN, already wired into the dashboard)
- SQLite (zero-config database, single file)
- statsmodels, pandas, numpy → for ARIMA forecasting
- scikit-learn → optional ensemble model comparison
- PuLP → inventory allocation (linear programming)
- geopy → route optimization
- openpyxl, reportlab → Excel/PDF report generation

## Apps already scaffolded

| App | Purpose | Status |
|---|---|---|
| `accounts` | Login/logout | Working |
| `dashboard` | Monitoring dashboard | Working (placeholder KPIs) |
| `farmers` | Farmer data management | Empty — build models/views next |
| `forecasting` | ARIMA demand forecasting | Empty |
| `inventory` | PuLP allocation optimization | Empty |
| `logistics` | Route optimization | Working (nearest-neighbor geodesic routes) |
| `reports` | PDF/Excel export | Empty |

## Setup (run these in your VS Code terminal, inside this folder)

### 1. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

> If PowerShell blocks the activation script, run this once as admin:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run migrations (creates your local db.sqlite3)

```bash
python manage.py migrate
```

### 4. Create an admin/superuser account

```bash
python manage.py createsuperuser
```
Follow the prompts (username, email, password).

### 5. Run the development server

```bash
python manage.py runserver
```

### Mapbox logistics map

The logistics app uses the Mapbox Matrix API for driving-distance route ordering
and Mapbox GL JS to display the latest route. In PowerShell, configure a
restricted Mapbox public token before starting the server:

```powershell
$env:MAPBOX_ACCESS_TOKEN = "pk.your-token-here"
py manage.py runserver
```

Without a token, route generation falls back to geodesic distances and the page
shows a setup message instead of the map.

Then open:
- **http://127.0.0.1:8000/** → dashboard (redirects to login first)
- **http://127.0.0.1:8000/accounts/login/** → login page
- **http://127.0.0.1:8000/admin/** → Django admin (use your superuser account)

### Stakeholder role access

Create the stakeholder groups after migrations:

```powershell
py manage.py setup_stakeholder_roles
```

Assign users to groups through Django admin. Access is deny-by-default for
unassigned non-farmer accounts:

| Role | Access |
|---|---|
| Ministry of Agriculture | Full operational monitoring and write actions |
| District Agricultural Officer | Farmer, forecast, allocation, and route monitoring; route generation |
| Warehouse Manager | Dashboard, inventory allocation visibility, and route visibility |
| Agro-Dealer | Dashboard and route visibility |
| Smallholder Farmer | Own farmer portal and delivery responses only |

Superusers are treated as Ministry users. A farmer account is identified by
the Farmer record's linked `user` field and remains restricted to the farmer
portal even if the account is also staff.

## VS Code recommended setup

1. Install the **Python extension** (Microsoft) from the Extensions tab.
2. `Ctrl+Shift+P` → "Python: Select Interpreter" → choose the one inside `venv/`.
3. That's it — VS Code will now use your virtual environment automatically for terminals and debugging.

## Suggested build order (maps to your Agile sprints)

1. **farmers app** — build the Farmer model, register in `admin.py`, add a simple list/create view
2. **forecasting app** — load sample/simulated CSV data, build ARIMA model with statsmodels, save predictions
3. **inventory app** — PuLP allocation model consuming forecasting output
4. **logistics app** — Mapbox Matrix nearest-neighbor route logic and map display
5. **dashboard app** — wire real KPIs into the existing Chart.js dashboard
6. **reports app** — PDF (reportlab) and Excel (openpyxl) export views

Each of these can be one Agile sprint, matching Chapter 3 of your proposal.
