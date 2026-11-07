# Claude Prompt: Chapter Four Documentation for the Agricultural Supply Chain System

Use this prompt with Claude when preparing **Chapter Four: System Design and Implementation**. Paste the prompt into Claude together with this project folder or the relevant source files if Claude supports project/file access.

---

## Role

You are an academic technical writer, software architect, and systems analyst writing a formal university project report. Produce polished, original, technically accurate Chapter Four content suitable for direct review and conversion into Microsoft Word.

## Project Context

Write Chapter Four for the project entitled:

**Development of an Intelligent Agricultural Supply Chain Management System for Zambia's Farmer Input Support Programme (FISP)**

The system supports planning and distribution of maize seed, fertilizer, and other agricultural inputs. It uses historical farmer data and forecasts to estimate demand, optimizes allocation of available inputs, plans supplier-to-dealer and dealer-to-farmer distribution, and provides weather-aware planning information.

### Project facts to use

- Main framework: Django 5.1.15.
- Programming language: Python 3.12.
- Database: SQLite using `db.sqlite3`.
- Front end: Django templates, HTML, CSS, and JavaScript.
- Main application modules: accounts, farmers, forecasting, inventory, logistics, weather, dashboard, and reports.
- Demand forecasting: ARIMA; statsmodels is the primary forecasting library.
- National historical comparison: FAOSTAT national input and maize-area series.
- Farmer survey data: FISP Southern Province survey data for 340 maize farmers.
- Inventory allocation optimization: PuLP linear programming.
- Route support: nearest-neighbour route logic, geospatial coordinates, geopy, and the Mapbox Matrix API where an access token is configured.
- Weather: Open-Meteo global-model weather and ECMWF SEAS5 seasonal rainfall data, with a local 2026/2027 seasonal rainfall outlook where available.
- Geospatial and mapping tools: GeoJSON, PyShp, Shapely, Leaflet or browser mapping code, and seasonal map JavaScript.
- Report generation: Django views/templates, ReportLab, and OpenPyXL.
- User roles represented by Django authentication groups: Ministry of Agriculture, District, Supplier, and Agro-Dealer. The login interface may also represent a farmer stakeholder role, but farmers should be treated through farmer records and delivery workflows unless implemented as authenticated users.
- Tests are provided in Django application `tests.py` files, and Django's built-in test runner is used.
- Deployment in the project is currently local development deployment: Python virtual environment, SQLite migrations, static files, and `python manage.py runserver`.

### Important analytical boundaries

1. Explain ARIMA demand forecasts separately from weather scenarios:
   - The ARIMA result is the baseline demand used by allocation.
   - ZMD and ECMWF SEAS5 weather adjustments are planning scenarios.
   - Weather-adjusted quantities are not silently substituted for the baseline allocation quantity.

2. Do not claim that all stakeholder roles are fully implemented if the evidence is only stored in roles, links, or partial views. Clearly distinguish implemented components, planned components, and prototype/demo components.

3. Do not invent implementation details, test results, performance figures, or deployment infrastructure such as Docker, cloud hosting, PostgreSQL, or a production server unless those technologies appear in the supplied project files.

4. If a required fact is not available, write `[To be confirmed from project implementation]` rather than fabricating it.

## Required Chapter Structure

Produce all headings exactly or closely matching the supplied project guidelines:

### CHAPTER FOUR: SYSTEM DESIGN AND IMPLEMENTATION

#### 4.1 Introduction

Explain that this chapter presents the system architecture, detailed design, implementation, testing, and deployment.

#### 4.2 Architectural Design

Describe the selected architectural style, preferably a modular Django Model-Template-View architecture with separate domain applications. Include:

- Presentation layer: Django templates, HTML, CSS, JavaScript, dashboard, maps, reports, and role-based pages.
- Application/business logic: Django views, services, management commands, forecasting logic, allocation logic, route logic, and role authorization.
- Data layer: Django ORM and SQLite.
- External integrations: weather APIs, Mapbox routing, FAOSTAT data, FISP survey data, and ZMD seasonal forecast documents.
- Justify the architecture by explaining separation of concerns, modularity, maintainability, and support for independent testing.

Create a labelled Mermaid architecture diagram and explain its components and data flows. Model the browser/client connecting to Django views, which coordinate the domain modules, ORM, SQLite, reports, external APIs, and geospatial data.

#### 4.3 Software Design

Explain how design requirements were translated into reusable modules, database entities, interfaces, and controlled workflows.

##### 4.3.1 Software Design Tools

Discuss tools used or suitable for the project, including:

- Django documentation and Django ORM conventions.
- Draw.io, diagrams.net, PlantUML, or Mermaid for diagrams.
- Visual Studio Code, PyCharm, or the IDE used by the developer if known.
- SQLite DB Browser or Django ORM tools for database inspection.
- Git/GitHub for version control if confirmed.
- Microsoft Excel/OpenPyXL for dataset preparation.
- Browser developer tools for interface testing.
- Give each tool a purpose, but do not claim Git use if it is not confirmed by repository evidence.

##### 4.3.2 Component Design

Produce the following subsections and diagrams.

###### 4.3.2.1 Contextual Model

Create a Mermaid context diagram showing:

- Ministry/District users.
- Suppliers.
- Agro-dealers.
- Farmers.
- FISP system.
- FAOSTAT.
- Weather providers/ZMD.
- Mapbox or routing service, where used.
- Main exchanges of data such as demand records, forecasts, allocations, dispatches, delivery confirmations, weather data, and route geometry.

###### 4.3.2.2 Use Case Model

Create a Mermaid use-case diagram using Mermaid-compatible syntax or provide an equivalent tabular use-case specification followed by a PlantUML-style diagram. Actors should include:

- Ministry official.
- District officer.
- Supplier.
- Agro-dealer.
- Farmer.
- External weather/data services may be secondary actors.

Use cases must include:

- Login and role-based access.
- Maintain farmer and usage records.
- Generate input demand forecast.
- View weather forecasts and seasonal scenarios.
- Run inventory allocation.
- Review and assign allocations.
- Manage supplier stock and dispatch inputs.
- Plan distribution routes.
- Confirm delivery or report an issue.
- Generate Excel/PDF reports.

Provide a use-case table with ID, actor, preconditions, main flow, alternate flow, and postconditions for the most important workflows. At minimum cover login, forecast generation, allocation, dispatch, and delivery confirmation.

###### 4.3.2.3 Sequence Diagram

Create sequence diagrams in Mermaid for at least:

1. Login and role-based access.
2. Demand forecast generation.
3. Inventory allocation.
4. Route planning and delivery confirmation.

Use correct lifelines such as User, Browser, Django View, Model/ORM, Forecasting module, Allocation module, Logistics module, Database, Weather API, and external routing API where relevant.

###### 4.3.2.4 State Machine Diagram

Create diagrams or state-transition tables for:

- RoutePlan: planned, in progress, completed, cancelled.
- RouteStop: pending, delivered, issue.
- FarmerInputAllocation collection status: awaiting collection, collected.
- SupplierDispatch receipt state or delivery lifecycle.

Use state diagram syntax supported by Mermaid where possible. Include transitions, actors, and triggering events.

###### 4.3.2.5 Activity Diagram

Create Mermaid flowcharts for:

- End-to-end FISP planning and allocation process.
- Farmer delivery and confirmation process.
- Supplier dispatch and dealer receipt process.

Activities should include decision points and error/issue paths.

###### 4.3.2.6 Class Diagram

Create a project-focused Mermaid class diagram based on the implemented Django models. Cover, at minimum:

- Django User.
- Farmer.
- FarmerInputUsage.
- Forecast and NationalInputSeries.
- InventoryAllocation.
- FarmerAllocation.
- DealerInputAllocation.
- Supplier.
- AgroDealer.
- SupplierDispatch.
- DealerStockReceipt.
- RoutePlan.
- RouteStop.
- RouteStopInput.
- SupplierDealerRoute.
- DeliveryConfirmation.
- DailyWeather and SeasonalWeather models.

Show cardinalities and relationships where possible, including ForeignKey, OneToOne, and shared allocation-run or forecast relationships. Also add a short explanation of entity responsibilities and constraints.

#### 4.4 Software Development

Explain implementation pragmatics without turning this section into a source-code listing.

##### 4.4.1 Software Development Tools

Include:

- Python 3.12 and Django 5.1.15.
- Python virtual environment and pip.
- requirements.txt dependency management.
- SQLite DB Browser or Django shell for database operations if used.
- VS Code/PyCharm/other confirmed IDE.
- Django management commands, migrations, and built-in development server.
- pandas, NumPy, statsmodels, scikit-learn, PuLP, geopy, ReportLab, OpenPyXL, PyShp, Shapely, and SciPy where relevant.
- Git/GitHub only if confirmed.

Provide a technology stack table with category, technology, version or package role, and project use.

##### 4.4.2 Component Development

Describe implementation of each major module:

- accounts: Django authentication, profile, stakeholder roles, permissions, and role-based pages.
- farmers: registration/profile, national ID uniqueness, location, crop, farm size, historical input usage, and delivery confirmations.
- forecasting: import and process farmer and FAOSTAT data, generate ARIMA forecasts, store national-series results/backtests, and compare weather scenarios.
- inventory: district allocation, farmer shares, dealer allocations, dispatch records, collection status, and supplier stock.
- logistics: suppliers, agro-dealers, route plans, ordered stops, route inputs, road geometry, and delivery confirmation.
- weather: historical and forecast daily weather, global-model temperatures, seasonal outlooks, and Open-Meteo/SEAS5 retrieval.
- dashboard: stakeholder views, summaries, system navigation, and role-filtered information.
- reports: Excel/PDF report generation.

Also explain:

- Django model-to-table mapping.
- Foreign key integrity and deletion behavior.
- Role-based authorization.
- CSRF protection and Django authentication.
- Data validation and uniqueness constraints.
- Error handling for external API failures and missing configuration.
- How environmental configuration such as `MAPBOX_ACCESS_TOKEN` is handled.
- Key user interfaces and screenshots can be inserted where appropriate.

##### 4.4.3 Evaluation and Testing Techniques

Describe:

- Unit testing.
- Django model and view tests.
- Integration testing across app modules.
- System/end-to-end testing.
- User acceptance testing.
- Positive, negative, and boundary cases.
- Database setup and test isolation.

Explain representative tests that could be written or are evidenced in the project:

- Authentication and role access.
- Duplicate national ID handling.
- Forecast generation with insufficient or sufficient data.
- Allocation total and constraint checks.
- Supplier dispatch and dealer stock receipt.
- Route sequencing and status transitions.
- Delivery confirmation.
- Weather API/cache behaviour.

If actual test execution results are unavailable, mark them as pending and do not claim a pass rate. Provide a test-case table with test ID, component, procedure, expected result, actual result, status, and evidence. The student should later add screenshot or command evidence.

Use commands:

```text
python manage.py test
python manage.py migrate
python manage.py runserver
```

#### 4.5 Deployment

Document the implemented local-development deployment process:

1. Install Python 3.12.
2. Create and activate a virtual environment.
3. Install dependencies from `requirements.txt`.
4. Configure required environment settings.
5. Run migrations.
6. Load farmer and FAOSTAT data using management commands if required.
7. Set stakeholder roles and create demonstration users if required.
8. Start Django using `python manage.py runserver`.
9. Access the application through `http://127.0.0.1:8000`.

Include a deployment architecture diagram, configuration considerations, data initialization, backup, security, monitoring, and recommended production hardening. Clearly label production recommendations as recommendations, not as implemented features. Recommended deployment items may include HTTPS, environment-variable secrets, a production-capable database, static/media file handling, production WSGI server, and periodic database/data backups.

#### 4.6 Summary

Summarize architecture, modules, data flow, implementation tools, testing approach, and deployment. Explain that Chapter Four connects requirements and analysis to a working implementation and bridges to evaluation/chapter discussion that follows.

## Required diagrams and figures

Generate Mermaid source code for every diagram, followed by an accessible plain-language explanation. Also suggest a concise Word caption and figure number for each.

Use this figure plan unless better project evidence supports a different number:

1. Three-layer system architecture.
2. Contextual model.
3. Use case model.
4. Login sequence diagram.
5. Forecast generation sequence diagram.
6. Allocation sequence diagram.
7. Route planning and confirmation sequence diagram.
8. RoutePlan state machine.
9. RouteStop/collection status state machine.
10. FISP planning activity diagram.
11. Delivery confirmation activity diagram.
12. Supplier dispatch activity diagram.
13. Project class diagram.
14. Local deployment architecture.

For each diagram, ensure entities are internally consistent with Django module names, model names, workflow states, and actor roles. Use left-to-right flow where helpful.

## Output requirements

- Produce a comprehensive chapter suitable for Microsoft Word, not a coding tutorial.
- Write continuously in formal academic language.
- Use British English spelling, such as “optimisation”, “centre”, and “programme”, unless technical library names require otherwise.
- Define acronyms on first use, including ARIMA, FISP, ORM, API, UI, JSON, CSRF, FAOSTAT, ZMD, PDF, and SEAS5.
- Support claims with project evidence from the supplied repository and avoid unsupported claims.
- Use full academic paragraphs, tables, and bullet lists where appropriate.
- Add a figure placeholder or Mermaid block before the caption.
- Use tables where tables improve clarity, especially for:
  - System architecture components.
  - Software design tools.
  - Technology stack.
  - Actors and responsibilities.
  - Use-case specifications.
  - State transitions.
  - Component implementation.
  - Test cases.
  - Deployment steps.
- Keep the tone consistent across sections and maintain forward references between Chapter Three requirements and Chapter Four implementation.
- At the end, provide a Word import checklist identifying:
  - All headings.
  - All figure captions.
  - All tables.
  - Any content still marked for confirmation.
  - Any supplied screenshots that should replace placeholders.

## Project-specific example introductory content

The final prose should communicate that the Django system translates historical farmer demand, national input trends, weather information, supply availability, and distribution constraints into an operational planning platform. State that it supports:

- Farmer input usage data management.
- District-level demand forecasting.
- Weather-aware planning scenarios.
- Inventory optimisation and farmer/dealer allocation.
- Supplier dispatch management.
- Route planning and delivery confirmation.
- Role-based reporting.

## Accuracy and evidence check

Before drafting the chapter, inspect the project repository for:

- Django app names and URL routing.
- Model fields and relationships.
- Role names and authorization decorators.
- Forecast, allocation, and logistics view flows.
- Installed packages in `requirements.txt`.
- Management commands that import or generate data.
- Existing Django test modules.
- Actual deployment instructions in `README.md`.

If the repository files conflict with any statement below, follow the repository evidence rather than the statement.

## Final deliverables

1. A complete **Chapter Four** in Markdown with numbered headings and Word-ready tables.
2. Mermaid source for every diagram.
3. Suggested figure and table captions.
4. A concise list of unverified or missing project facts.
5. Instructions for converting Mermaid diagrams into images and inserting them into Word.
