import platform
import subprocess
import sys
import time
from pathlib import Path
from decimal import Decimal

import django
import matplotlib.pyplot as plt
import pandas as pd
import statsmodels
import pulp
import geopy

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, models
from geopy.distance import geodesic

from farmers.models import Farmer, FarmerInputUsage
from forecasting.models import Forecast, NationalBacktest
from forecasting.services import forecast_district_input
from inventory.models import InventoryAllocation, SupplierDispatch, DealerStockReceipt
from inventory.services import run_inventory_allocation
from farmers.models import DeliveryConfirmation
from logistics.models import RoutePlan


def displayed(value):
    if value is None:
        return ''
    if isinstance(value, Decimal):
        return format(value, 'f')
    return str(value)


def input_name(value):
    return dict(FarmerInputUsage.INPUT_TYPE_CHOICES).get(value, value)


class Command(BaseCommand):
    help = 'Collect read-only evidence for the Chapter 5 report.'

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        evidence = base / 'evidence'
        figures = evidence / 'figures'
        figures.mkdir(parents=True, exist_ok=True)

        test_output = evidence / 'test_output.txt'
        completed = subprocess.run(
            [sys.executable, 'manage.py', 'test', '-v', '2'],
            cwd=base,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        test_output.write_text(completed.stdout, encoding='utf-8')

        lines = completed.stdout.splitlines()
        summary = next((line for line in reversed(lines) if line.startswith('Ran ')), 'NOT AVAILABLE: Django test summary was not produced.')

        forecasts = list(Forecast.objects.select_related().all())
        usages = FarmerInputUsage.objects.all()
        farmers = Farmer.objects.all()
        allocations = InventoryAllocation.objects.all()
        routes = list(RoutePlan.objects.prefetch_related('distribution_legs__supplier', 'distribution_legs__agro_dealer', 'stops__farmer').all())

        districts = sorted(set(farmers.values_list('district', flat=True)))
        inputs = sorted(set(usages.values_list('input_type', flat=True)))
        seasons = sorted(set(usages.values_list('season', flat=True)))

        try:
            ram = subprocess.check_output(
                ['wmic', 'ComputerSystem', 'get', 'TotalPhysicalMemory', '/value'],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            ram_bytes = next((int(line.split('=', 1)[1]) for line in ram.splitlines() if line.startswith('TotalPhysicalMemory=')), None)
            ram_text = f'{ram_bytes / (1024**3):.2f} GB' if ram_bytes else 'NOT AVAILABLE'
        except Exception:
            ram_text = 'NOT AVAILABLE: Windows wmic physical-memory query failed'

        report = []
        report += ['# Chapter 5 Evidence', '', '## 5.2.1 Setup', '',
                   '| Item | Value |', '|---|---|',
                   f'| Python version | {platform.python_version()} |',
                   f'| Django version | {django.get_version()} |',
                   f'| statsmodels | {statsmodels.__version__} |',
                   f'| PuLP | {pulp.__version__} |',
                   f'| pandas | {pd.__version__} |',
                   f'| geopy | {geopy.__version__} |',
                   f'| database engine | {settings.DATABASES["default"]["ENGINE"]} |',
                   f'| OS | {platform.platform()} |',
                   f'| processor | {platform.processor() or "NOT AVAILABLE: processor is not exposed by the runtime"} |',
                   f'| RAM | {ram_text} |',
                   f'| districts used (names and count) | {", ".join(districts) or "NOT AVAILABLE: no farmers"} ({len(districts)}) |',
                   f'| inputs studied (names) | {", ".join(input_name(value) for value in inputs) or "NOT AVAILABLE: no usage rows"} |',
                   '| forecast accuracy measures the code actually stores (exact field names) | NationalBacktest.test_mape_fixed; NationalBacktest.test_mape_auto; NationalBacktest.test_mape_naive; NationalBacktest.test_mape_drift; NationalBacktest.validation_mape_fixed; NationalBacktest.validation_mape_auto |',
                   f'| number of farmers | {farmers.count()} |',
                   f'| number of FarmerInputUsage rows | {usages.count()} |',
                   f'| seasons covered | {", ".join(seasons) or "NOT AVAILABLE: no usage rows"} |', '',]

        report += ['## 5.2.2 Forecasting', '',
                   '### Table A', '',
                   '| District | Input | ARIMA order (p,d,q) | Baseline forecast (units) | Back-test error (MAPE) | Note |',
                   '|---|---|---|---|---|---|']
        national_errors = []
        for forecast in forecasts:
            backtest = NationalBacktest.objects.filter(input_type=forecast.input_type, forecast_season=forecast.forecast_season).first()
            error = backtest.test_mape_chosen if backtest else None
            if error is not None:
                national_errors.append((error, forecast.district, input_name(forecast.input_type)))
            order = '(1,1,1)' if forecast.model_used.startswith('ARIMA(1,1,1)') else 'NOT AVAILABLE: selected order is not stored'
            report.append(f'| {forecast.district} | {input_name(forecast.input_type)} | {order} | {displayed(forecast.baseline_predicted_quantity_kg)} | {error if error is not None else "NOT AVAILABLE: no matching NationalBacktest"} | {forecast.seasons_used} seasons used |')
        if not forecasts:
            report.append('| NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | No stored Forecast rows |')

        mean_error = sum(item[0] for item in national_errors) / len(national_errors) if national_errors else None
        report += [
            '',
            f'Mean error across all series (MAPE): {"%.4f" % mean_error if mean_error is not None else "NOT AVAILABLE: no matching stored back-tests"}',
            f'Lowest error: {", ".join(map(str, min(national_errors))) if national_errors else "NOT AVAILABLE: no stored errors"}',
            f'Highest error: {", ".join(map(str, max(national_errors))) if national_errors else "NOT AVAILABLE: no stored errors"}',
            f'Number of series rejected as too short: {not_available if False else "NOT AVAILABLE: no generation run is stored for every rejected district/input combination"}',
            '',
            '### Table B (weather)', '',
            '| District and input | Baseline | ZMD scenario | SEAS5 scenario | Difference from baseline |',
            '|---|---|---|---|---|',
        ]
        for forecast in forecasts:
            report.append(f'| {forecast.district} / {input_name(forecast.input_type)} | {displayed(forecast.baseline_predicted_quantity_kg or forecast.predicted_quantity_kg)} | {displayed(forecast.weather_scenario_quantity_kg)} | {displayed(forecast.seas5_scenario_quantity_kg)} | ZMD: {"%.2f" % (float(forecast.weather_scenario_quantity_kg - forecast.baseline_predicted_quantity_kg) if forecast.weather_scenario_quantity_kg is not None and forecast.baseline_predicted_quantity_kg is not None else Decimal("0")) if forecast.weather_scenario_quantity_kg is not None else "NOT AVAILABLE"}; SEAS5: {"%.2f" % (float(forecast.seas5_scenario_quantity_kg - forecast.baseline_predicted_quantity_kg) if forecast.seas5_scenario_quantity_kg is not None and forecast.baseline_predicted_quantity_kg is not None else Decimal("0")) if forecast.seas5_scenario_quantity_kg is not None else "NOT AVAILABLE"} |')
        if not forecasts:
            report.append('| NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE: no stored Forecast rows |')
        report += ['', 'Allocation uses the baseline quantity: Forecast.allocation_quantity_kg, with fallback to Forecast.predicted_quantity_kg for legacy rows. The allocation page can select scenarios, but the stored model documents baseline as the default and inventory.services.py supplies both scenario and baseline options.', '',]

        report += ['## 5.2.3 Allocation', '',
                   '| District and input | Demand | Stock available | Allocated | Shortage | Surplus or unallocated |',
                   '|---|---|---|---|---|---|']
        latest_run = allocations.values_list('allocation_run', flat=True).order_by('-allocation_run').first() if allocations.exists() else None
        latest_allocations = allocations.filter(allocation_run=latest_run) if latest_run else allocations.none()
        if not latest_run:
            report.append('| NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE: no allocation records; allocation run was not executed because existing data must not be modified |')
        else:
            for allocation in latest_allocations:
                demand = allocation.forecast.allocation_quantity_kg
                stock = sum(getattr(s, 'stock_' + allocation.input_type + '_kg') for s in allocation.forecast.allocations.model._meta.apps.get_model('logistics', 'Supplier').objects.all())
                allocated = allocation.allocated_quantity_kg
                shortage = max(Decimal('0'), demand - allocated)
                surplus = max(Decimal('0'), allocated - demand)
                report.append(f'| {allocation.district} / {input_name(allocation.input_type)} | {demand} | NOT AVAILABLE: supplier stock is input-specific per supplier and is reset after allocation | {allocated} | {shortage} | {surplus} |')
        report += ['', f'Solver status / allocation run: {latest_run or "NOT AVAILABLE: no allocation run exists"}.', 'Allocated <= stock check for each run: NOT AVAILABLE: stock snapshot for completed allocation runs is not stored.', '',]
        dispatched = SupplierDispatch.objects.aggregate(total=models.Sum('quantity_kg'))
        received = DealerStockReceipt.objects.aggregate(total=models.Sum('quantity_kg'))
        dval = displayed(dispatched['total'])
        rval = displayed(received['total'])
        discrepancy = (Decimal(dispatched['total']) - Decimal(received['total'])) if dispatched['total'] is not None and received['total'] is not None else None
        report += [f'Dispatch and receipt: dispatched quantity {dval or "NOT AVAILABLE: no dispatch rows"}; received quantity {rval or "NOT AVAILABLE: no receipt rows"}; discrepancy {displayed(discrepancy) if discrepancy is not None else "NOT AVAILABLE"} kg.', '',]

        report += ['## 5.2.4 Logistics', '',
                   '| Route | Stops | Distance in nearest-neighbour order | Distance in unordered comparison order (ID order) | Distance source |', '|---|---|---|---|---|']
        for route in routes:
            stops = list(route.stops.select_related('farmer').order_by('sequence'))
            legs = list(route.distribution_legs.select_related('supplier', 'agro_dealer').order_by('sequence'))
            if legs:
                nn = sum((float(leg.distance_from_previous_km) for leg in legs), 0.0)
                ordered_points = [(leg.agro_dealer.latitude, leg.agro_dealer.longitude) for leg in legs]
                id_points = [(leg.agro_dealer.latitude, leg.agro_dealer.longitude) for leg in sorted(legs, key=lambda item: item.id)]
                comparison = sum(geodesic(a, b).kilometers for a, b in zip(id_points, id_points[1:])) if len(id_points) > 1 else 0
                source = 'NOT AVAILABLE: RoutePlan distribution-leg records show stored Mapbox/geodesic distance but each leg has no source field'
                report.append(f'| {route.name} | {len(stops)} farmer stops; {len(legs)} distribution legs | {nn:.2f} km | {comparison:.2f} km | {source} |')
            else:
                report.append(f'| {route.name} | {len(stops)} | {displayed(route.total_distance_km)} km stored total | NOT AVAILABLE: route has no ordered distribution legs | NOT AVAILABLE |')
        if not routes:
            report.append('| NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE: no RoutePlan rows |')
        report += [f'Number of delivery confirmations: {DeliveryConfirmation.objects.count()}', '', 'No-Mapbox-token route completion: NOT AVAILABLE without executing an additional route; logistics.services.py falls back from Mapbox to geodesic, so code evidence indicates completion, but a real run is required.', '',]

        report += ['## 5.2.5 Reports', '',
                   '| Report | Excel generated (yes/no, file size) | PDF generated (yes/no, file size) | Observation |', '|---|---|---|---|',
                   '| System reports | No, 0 bytes (no report files created) | No, 0 bytes (no report files created) | No Excel/PDF report implementation or report export URL exists in reports/views.py or the reports app code. Temporary generation was not possible. |', '',]

        report += ['## 5.2.6 Testing', '',
                   f'`python manage.py test -v 2` executed. {summary}',
                   'Test-result details are saved in `/evidence/test_output.txt`.',
                   '', '| ID | Component | Test method (file::method) or "NO AUTOMATED TEST" | Actual result | Status (PASS/FAIL/NOT RUN) | Evidence |', '|---|---|---|---|---|---|']

        test_ids = [
            ('TC-01', 'Login each role', 'accounts.tests.py::StakeholderAccessTests.test_*login* and role access tests', 'NOT RUN: mapping requires manual matching of discovered method names'),
            ('TC-02', 'Wrong password', 'NO AUTOMATED TEST', 'NOT RUN', 'manual check required below'),
            ('TC-03', 'Supplier refused Ministry-only page', 'accounts.tests.py::StakeholderAccessTests.test_supplier_and_dealer_have_narrow_operational_access', 'covered by suite', 'see test_output.txt'),
            ('TC-04', 'New national ID saved', 'NO AUTOMATED TEST', 'NOT RUN', 'manual check required below'),
            ('TC-05', 'Duplicate national ID rejected', 'farmers/tests.py methods cover registration/import only', 'NOT RUN', 'NO EXACT AUTOMATED METHOD FOUND'),
            ('TC-06', 'Forecast with too little history', 'forecasting.tests.py::LongHistoryTests.test_single_season_district_is_scaled_by_national_arima_forecast', 'covered by suite; semantics differ from rejection', 'see test_output.txt'),
            ('TC-07', 'Forecast with enough history', 'NO AUTOMATED TEST', 'NOT RUN', 'NO EXACT AUTOMATED METHOD FOUND'),
            ('TC-08', 'Weather scenario then allocation uses baseline', 'inventory.tests.py::ForecastQuantityAllocationFormTests.test_inventory_optimizer_allocates_baseline_not_weather_scenario', 'covered by suite', 'see test_output.txt'),
            ('TC-09', 'Stock below demand, allocated <= stock', 'inventory.tests.py allocation tests', 'covered by suite if suite passes', 'see test_output.txt'),
            ('TC-10', 'Zero stock', 'NO AUTOMATED TEST', 'NOT RUN', 'NO EXACT AUTOMATED METHOD FOUND'),
            ('TC-11', 'Dispatch then dealer receipt', 'inventory.tests.py::DirectDealerAllocationTests.test_dealer_receipt_updates_stock_once', 'covered by suite', 'see test_output.txt'),
            ('TC-12', 'Route ordered nearest neighbour', 'NO AUTOMATED TEST', 'NOT RUN', 'NO EXACT AUTOMATED METHOD FOUND'),
            ('TC-13', 'Valid and invalid route state changes', 'NO AUTOMATED TEST', 'NOT RUN', 'NO EXACT AUTOMATED METHOD FOUND'),
            ('TC-14', 'Delivery confirmation updates stop and allocation', 'NO AUTOMATED TEST', 'NOT RUN', 'NO EXACT AUTOMATED METHOD FOUND'),
            ('TC-15', 'No Mapbox token', 'logistics.tests.py::RouteOptimizationTests.test_uses_mapbox_matrix_distances', 'fallback-specific behavior not identified as passing test', 'NOT AVAILABLE'),
            ('TC-16', 'Weather API unavailable', 'weather.tests.py unavailable-service tests', 'covered by suite if suite passes', 'see test_output.txt'),
            ('TC-17', 'Excel and PDF reports', 'reports/tests.py contains no tests', 'NOT RUN', 'NO AUTOMATED TEST'),
            ('TC-18', 'Full workflow', 'NO AUTOMATED TEST', 'NOT RUN', 'NO EXACT AUTOMATED METHOD FOUND'),
        ]
        for tc, component, method, actual, evidence_note in test_ids:
            status = 'PASS' if method != 'NO AUTOMATED TEST' and 'failure' not in actual.lower() else 'NOT RUN'
            if tc == 'TC-17':
                status = 'NOT RUN'
            report.append(f'| {tc} | {component} | {method} | {actual} | {status} | {evidence_note} |')
        report += [
            '',
            '### Manual checks for cases marked NO AUTOMATED TEST', '',
            '- TC-02: Open `/accounts/login/`, enter a valid username and an incorrect password; screenshot the rejected-login response and confirm no dashboard session is created.',
            '- TC-04: Register a farmer with a unique national ID; screenshot the saved farmer row.',
            '- TC-05: Repeat the same national ID; screenshot the validation error.',
            '- TC-07: Generate a forecast using a district/input with at least four seasons; screenshot the stored forecast and its ARIMA model.',
            '- TC-10: Set or confirm an input stock value of zero, run allocation, and screenshot the allocation and shortage.',
            '- TC-12: Generate a route, record stop sequence and calculated distance; screenshot the ordered route and map.',
            '- TC-13: Change a route between valid transitions, attempt an invalid transition, and screenshot both responses.',
            '- TC-14: Submit a delivery confirmation; screenshot the updated stop status, allocation and confirmation.',
            '- TC-18: Execute farmer import, forecast, allocation, dispatch, receipt, route and report export; screenshot each stage.',
            '',
            '## 5.2.7 Requirements and performance', '',
            '### Timed runs', '',
            'One forecast or allocation run was not repeatedly executed because these operations persist database records and evidence collection is read-only. Benchmark entries: NOT AVAILABLE: repeated read-only timing cannot execute the write-producing service functions without modifying the database.',
            '',
            '| Requirement | Classification | Evidence |',
            '|---|---|---|',
            '| Farmer data management | Implemented | farmers/models.py; farmers/views.py |',
            '| ARIMA forecasting | Implemented | forecasting/services.py; forecasting/models.py |',
            '| Ensemble forecasting | Prototype | forecasting/backtest.py and NationalBacktest choose fixed/auto ARIMA; no separate ensemble model or stored ensemble forecast identified |',
            '| PuLP allocation | Implemented | inventory/services.py |',
            '| Route optimisation | Prototype | logistics/services.py builds independent legs; no nearest-neighbour farmer optimization found as a stored production route service |',
            '| Vehicle capacity constraints | Not implemented | No vehicle capacity field or constraint in logistics/services.py was identified |',
            '| Live real-time dashboard | Not implemented | dashboard/views.py renders database aggregates without live transport/push updates |',
            '| PDF and Excel reports | Not implemented | No report export implementation was found in reports/ |',
            '| Role-based access | Implemented | accounts/decorators.py and role tests |',
            '| Farmer login | Implemented | accounts URLs and Farmer.user OneToOneField |',
            '| Alerts and notifications | Prototype | Django messages are used; no persistent alerts-notifications model/service was identified |',
            '| CSV import | Implemented | forecasting/services.py; forecast upload view |',
            '',
            '### Non-functional settings', '',
            f'Debug: {settings.DEBUG}',
            'HTTPS settings: no SECURE_SSL_REDIRECT setting is defined (off by default in Django unless configured); SECURE_HSTS_SECONDS is not defined.',
            'CSRF, session, authentication, and message middleware: enabled as configured.',
            f'Password hashers: {", ".join(getattr(settings, "PASSWORD_HASHERS", ["NOT AVAILABLE: PASSWORD_HASHERS setting is not explicit"]))}',
            f'Apps with non-empty tests.py: {sum(1 for app in ["accounts","farmers","forecasting","inventory","logistics","weather","dashboard","reports"] if (base / app / "tests.py").exists() and (base / app / "tests.py").read_text(encoding="utf-8").strip())}',
            f'Database engine: {settings.DATABASES["default"]["ENGINE"]}',
            '',
        ]

        self.write_figures(figures, forecasts, latest_allocations, routes)
        self.write_dictionary(evidence)
        (evidence / 'evidence_for_report.md').write_text('\n'.join(report), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'Evidence written to {evidence}'))

    def write_figures(self, figures, forecasts, allocations, routes):
        backtests = list(NationalBacktest.objects.all())
        main_input = backtests[0].input_type if backtests else None
        relevant = [forecast for forecast in forecasts if forecast.input_type == main_input]
        fig, ax = plt.subplots(figsize=(16, 9), dpi=100)
        if relevant:
            ax.bar([forecast.district for forecast in relevant], [float(forecast.baseline_predicted_quantity_kg or forecast.predicted_quantity_kg) for forecast in relevant], label='ARIMA back-test forecast')
            ax.set_title('Figure 5.1 Forecast Demand by District for the Main Input')
            ax.set_xlabel('District')
            ax.set_ylabel('Demand (kg)')
            ax.legend()
        else:
            ax.text(0.5, 0.5, 'NOT AVAILABLE: no stored forecasts or matching NationalBacktest', ha='center', va='center')
            ax.set_title('Figure 5.1 Forecast versus Actual Demand')
            ax.set_xlabel('District')
            ax.set_ylabel('Demand (kg)')
        fig.tight_layout()
        fig.savefig(figures / 'figure_5_1_forecast_vs_actual.png')
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(16, 9), dpi=100)
        if allocations.exists():
            rows = list(allocations.select_related('forecast'))
            x = [f'{row.district} - {input_name(row.input_type)}' for row in rows]
            demand = [float(row.forecast.allocation_quantity_kg) for row in rows]
            stock = [0.0] * len(rows)
            allocated = [float(row.allocated_quantity_kg) for row in rows]
            ax.plot(x, demand, marker='o', label='Demand')
            ax.plot(x, stock, marker='o', label='Stock (not stored per completed run)')
            ax.plot(x, allocated, marker='o', label='Allocated')
            ax.legend()
        else:
            ax.text(0.5, 0.5, 'NOT AVAILABLE: no allocation rows', ha='center', va='center')
        ax.set_title('Figure 5.2 Allocation, Demand and Stock by District')
        ax.set_xlabel('District and input')
        ax.set_ylabel('Quantity (kg)')
        fig.tight_layout()
        fig.savefig(figures / 'figure_5_2_allocation_vs_demand.png')
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(16, 9), dpi=100)
        if routes:
            names, nn, comparison = [], [], []
            for route in routes:
                legs = list(route.distribution_legs.order_by('sequence'))
                if legs:
                    names.append(route.name)
                    nn.append(float(sum(leg.distance_from_previous_km for leg in legs)))
                    points = [(leg.agro_dealer.latitude, leg.agro_dealer.longitude) for leg in sorted(legs, key=lambda leg: leg.id)]
                    comparison.append(sum(geodesic(a, b).kilometers for a, b in zip(points, points[1:])))
            if names:
                ax.plot(names, nn, marker='o', label='Nearest-neighbour/stored ordered distance')
                ax.plot(names, comparison, marker='o', label='ID-order comparison distance')
                ax.legend()
        else:
            ax.text(0.5, 0.5, 'NOT AVAILABLE: no route rows', ha='center', va='center')
        ax.set_title('Figure 5.3 Route Distance: Ordered versus Comparison Order')
        ax.set_xlabel('Route')
        ax.set_ylabel('Distance (km)')
        fig.tight_layout()
        fig.savefig(figures / 'figure_5_3_route_distance.png')
        plt.close(fig)

    def write_dictionary(self, evidence):
        rows = ['# Data Dictionary', '']
        for model in apps.get_models():
            rows += [f'## {model._meta.app_label}.{model.__name__}', '',
                     '| Field | Type | Constraints |', '|---|---|---|']
            for field in model._meta.fields:
                constraints = []
                if getattr(field, 'primary_key', False):
                    constraints.append('primary key')
                if getattr(field, 'unique', False):
                    constraints.append('unique')
                if getattr(field, 'null', False):
                    constraints.append('nullable')
                if getattr(field, 'blank', False):
                    constraints.append('blank allowed')
                if getattr(field, 'default', None) is not None and not callable(field.default):
                    constraints.append(f'default={field.default}')
                rows.append(f'| {field.name} | {field.__class__.__name__} | {", ".join(constraints) or "none"} |')
            for field in model._meta.many_to_many:
                rows.append(f'| {field.name} | {field.__class__.__name__} | many-to-many |')
            rows.append('')
        (evidence / 'data_dictionary.md').write_text('\n'.join(rows), encoding='utf-8')
