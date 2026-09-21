# Yathreb POS

Yathreb POS is a lightweight, local-first inventory, billing, customer-account and tailoring application built for Yathreb Fabrics & Tailors. It runs on the shop’s Windows computer, stores operational data in one local SQLite database, and serves the management interface through a browser.

The source has progressed from its original inventory-only foundation to schema version 5, covering day-to-day counter sales, tailoring orders, customer measurements, Tailor assignments, payments, receipts and reporting. The final verified baseline contains 131 automated tests.

## Current status

The current source provides a working operational foundation for one clothing and tailoring shop:

- schema version 5 with explicit initialization and migration controls;
- one authoritative database on the main shop computer;
- product inventory, billing, tailoring, customers, payments and reports;
- browser-printable 80 mm bill and payment receipts;
- a separate read-only Tailor View for a phone on the trusted shop LAN;
- non-overwriting, integrity-checked backup and restore commands;
- 131 automated tests covering the current foundation.

The application is intentionally local and lightweight. It has no cloud database, Node.js build, Docker service, microservice layer or separate database server.

## Development journey

The project was delivered incrementally so that each stage preserved earlier data and behavior:

1. **Inventory foundation** — explicit database initialization, owner authentication, the Product catalogue, fixed-precision stock movements, Current Stock and movement history.
2. **Catalogue and stock usability** — parent-scoped cascading selectors, inline catalogue creation, position-preserving forms, exact-variant stock entry and Product/Brand totals.
3. **Billing and sales** — default and bill-time prices, multi-line bills, discounts, payments at sale time, negative-stock visibility, immutable sale snapshots and 80 mm receipts.
4. **Management and reporting** — task-focused Dashboard, Sales History, daily and monthly Pakistan-time reports, searchable bills and guarded deletion of unused catalogue records.
5. **Customers and tailoring** — customer identities, normalized mobile search, measurement revisions, stitching-rate revisions, product-only, tailoring-only and combined bills.
6. **Customer accounts and later payments** — derived balances, bill-specific payments, immutable `PAY-######` records and printable payment acknowledgements.
7. **Tailor operations** — Tailor setup, optional assignment while billing, later assignment or reassignment per finalized garment, and schema-v4-to-v5 migration.
8. **Final UI and deployment** — contextual Billing feedback, preserved page position, single customer-facing BILL identity, compact navigation, full regression verification and transfer to the shop PC.

The historical requirements and decision log remain in `Clothing-Stitching-Project-Record.md`. The concise current behavior is maintained in `CURRENT-PROJECT-STATE.md`.

## Technology

- Python 3.13
- Flask 3.1.3
- Waitress 3.0.2
- SQLite from the Python standard library
- Server-rendered Jinja HTML
- Self-hosted CSS and vanilla JavaScript
- Windows 10 as the recorded production platform

## Operating model

The main shop computer runs one Waitress service and owns one database file on its local disk. The management browser normally connects through:

```text
http://127.0.0.1:8080
```

An optional second terminal or Tailor phone may connect to the same service through one specific private IPv4 address while both devices are on the trusted shop network.

Important rules:

- Keep the working SQLite database on the main computer’s local disk.
- Never place `inventory.sqlite3` on a shared network drive.
- Never run separate operational databases on multiple terminals.
- Never expose the service through public router port forwarding.
- Application startup never initializes, clears, reseeds or migrates a database automatically.

## Main functionality

### Dashboard and navigation

- Task-oriented Dashboard with New Sale as the primary action.
- Direct access to Billing, Orders / Collection, Customers, Current Stock, Add Stock and Sales.
- Secondary Setup group for Catalogue, Measurements, Stitching Rates and Tailors.
- Responsive mobile navigation and active-page states.

### Catalogue and inventory

The seven seeded Product definitions are:

| Product | Required hierarchy | Unit status |
| --- | --- | --- |
| Fabric | Product → Brand → Article → Colour | Metres confirmed |
| Chappal / Peshawari Chappal | Product → Brand → Colour → Size | Pairs proposed; owner confirmation required |
| Shawl | Product → Brand → Colour | Pieces proposed; owner confirmation required |
| Wallet | Product → Brand → Colour | Pieces proposed; owner confirmation required |
| Studs | Product → Brand → Colour | Pairs confirmed |
| Waistcoat | Product → Brand → Colour → Size | Pieces proposed; owner confirmation required |
| Coat | Product → Brand → Colour → Size | Pieces proposed; owner confirmation required |

Catalogue behavior:

- Products, Brands, Articles, Colours and Sizes use stable integer identities.
- Every child belongs to its immediate parent; cross-parent combinations are rejected.
- Normalized names are unique within the same immediate parent and may repeat under different parents.
- Labels may be renamed without moving stock or rewriting saved history.
- Unused leaf records can be deleted only after explicit confirmation.
- The seven seeded Product definitions cannot be deleted.
- Proposed pair/piece units must be explicitly confirmed before stock is entered.

Inventory behavior:

- Opening and incoming stock are stored as append-only movements.
- Exact Product variants are validated against the complete parent chain.
- Fabric supports quantities to three decimal places; pair and piece units require whole numbers.
- Current balances are derived from stock movements.
- Current Stock provides Product/Brand summaries, exact-variant filtering and movement history.
- Submission keys and content digests prevent duplicate stock writes.
- Sales may make stock negative; the shortage remains visible and later incoming stock corrects the balance normally.

### Billing and sales

Billing supports:

- product-only sales;
- tailoring-only sales;
- combined product and stitching sales;
- multiple Product and tailoring lines on one bill;
- exact-variant default selling prices;
- editable bill-time prices that do not change the saved default;
- one fixed PKR discount;
- amount paid at finalization and a derived remaining balance;
- anonymous fully-paid product-only bills;
- required existing Customers for tailoring or outstanding balances;
- automatic linking of one current-bill Fabric line to tailoring;
- explicit cloth selection when several Fabric lines are available;
- Customer-provided cloth and eligible Fabric from an earlier Customer bill;
- visible negative-stock warnings without blocking a sale.

Each finalized bill receives one customer-facing `BILL-########` number. Product and tailoring lines, labels, quantities, prices, discounts, totals and stock movements are saved atomically and remain immutable. The server recalculates all totals and protects finalization against duplicate submissions.

The internal `TAIL-######` identity remains available in Orders / Collection but is not printed as a second customer-facing transaction number.

### Customers, measurements and stitching rates

- Sequential `CUST-######` Customer identities.
- Search by Customer number, name or normalized primary/alternate mobile.
- Editable contact details without changing Customer identity.
- Duplicate normalized primary mobiles are blocked by default.
- Derived account totals and outstanding balances.
- Append-only measurement revisions.

The seven standard measurement templates are:

1. Pakistani Waistcoat
2. Three-Piece Waistcoat
3. Coat
4. Sherwani
5. Pant
6. Shalwar Kameez
7. Shirt

`Other / Custom Item` supports a custom description and flexible named measurements. It is not an eighth standard template.

Standard tailoring requires the Customer’s latest matching measurements and a configured current stitching rate. Stitching rates are append-only PKR revisions. Custom items use a manual stitching price. Finalized garments retain immutable measurement and rate snapshots.

### Tailoring orders and Tailor assignment

- Orders / Collection lists finalized tailoring orders.
- Search by BILL number, TAIL number or Customer identity.
- Order detail shows Customer, promised date, cloth source, measurements, bill values and current balance.
- Tailors are maintained in a small Setup page and can be made inactive without changing old records.
- Each garment line may be assigned while billing or later from Order Detail.
- A Tailor may be reassigned or cleared.
- One assignment applies to every piece in that line; garments going to different Tailors should use separate bill lines.
- Financial values, bill lines and measurement snapshots remain immutable.

The schema defines Received, In Progress, Ready and Delivered statuses. A complete operational status-transition workflow is not yet implemented.

### Customer accounts and payments

- Customer accounts combine product-only, tailoring-only and combined bills.
- Total billed, total paid and current outstanding are derived from immutable transactions.
- Later payments apply to one explicit outstanding Customer bill.
- Payments receive sequential `PAY-######` identities.
- Duplicate payment retries are idempotent.
- Overpayment is rejected.
- Later payments do not rewrite the original bill, its initial paid amount, receipt snapshots or stock movements.
- Successful payments produce an 80 mm printable acknowledgement.

### Sales, reports and printing

- Sales History searches by bill number, Customer name or mobile.
- Daily reports use Pakistan Standard Time and default to the current Pakistan date.
- Monthly reports default to the current Pakistan month.
- Reports show bill counts and saved subtotal, discount, paid and remaining values.
- Finalized bills and payment acknowledgements are printable in an 80 mm browser layout.
- Printing and reprinting never create another sale or deduct stock.

The current implementation uses the browser print dialog. Silent printing and printer-specific automation are not included.

### Read-only Tailor View

A separate Tailor View is available at:

```text
/tailor
```

It:

- uses a separate numeric PIN instead of the management owner login;
- accepts a configured PIN of 4–12 digits;
- searches Customers by ID, name or mobile;
- shows only each Customer’s current saved measurements, selected styles and notes;
- cannot open management pages;
- cannot create or edit Customers, measurements, bills or payments.

Configure the PIN for the current Windows user before starting the service:

```powershell
[Environment]::SetEnvironmentVariable(
    "YATHREB_TAILOR_PIN",
    "CHOOSE-A-PRIVATE-4-TO-12-DIGIT-PIN",
    "User"
)

$env:YATHREB_TAILOR_PIN = [Environment]::GetEnvironmentVariable(
    "YATHREB_TAILOR_PIN",
    "User"
)
```

Do not commit the real PIN to source control.

The current Tailor View is a local browser application. Automatic discovery across changing Wi-Fi networks and a native Android wrapper are future work.

## Data and transaction guarantees

- Money is stored as integer PKR paisa.
- Quantities are stored as integer thousandths.
- Line totals are rounded half-up to the nearest paisa.
- Foreign keys and database triggers enforce critical relationships.
- Writes use serialized transactions with a busy timeout.
- SQLite WAL mode supports the application service’s concurrent browser requests.
- Stock and financial retries use request identities and content digests.
- Finalized bills, item snapshots, payments and stock movements are immutable.
- Billing drafts are untrusted input and are fully revalidated at finalization.
- Application startup refuses a missing, unsupported or incorrectly identified database.
- Backups and restores are checked before being accepted.

## Security controls

- One authenticated owner account.
- Scrypt password hashing.
- CSRF validation for POST requests.
- Strict session cookies and session invalidation.
- Login throttling and a global login guard.
- Trusted-host validation.
- Request-size and form-part limits.
- `Cache-Control: no-store`.
- Content Security Policy, clickjacking protection, MIME sniffing protection and same-origin referrer policy.
- Separate restricted Tailor session.
- Local/private-LAN binding only.

Staff roles and granular permissions are not yet implemented.

## Source layout

```text
manage.py                         Setup, schema check, migration, backup, restore and service commands
requirements.txt                  Flask and Waitress versions
shop/__init__.py                  Application factory, authentication boundary and security headers
shop/auth.py                      Owner login/logout and CSRF handling
shop/db.py                        Explicit SQLite lifecycle and schema identity checks
shop/inventory.py                 Catalogue, stock, sales, Customers, tailoring, Tailors and payments
shop/web.py                       Management and Tailor View routes
shop/migrations/001_initial.sql   Full schema-v4 foundation and seeded Products
shop/migrations/002_tailors.sql   Explicit schema-v4 to schema-v5 Tailor migration
shop/templates/                   Server-rendered management, receipt and Tailor View pages
shop/static/app.css               Responsive screen and 80 mm print styling
shop/static/app.js                Cascading selectors, dialogs, billing draft behavior and navigation
tests/                            Model, web, security, reporting, recovery and regression tests
CURRENT-PROJECT-STATE.md          Concise current implementation record
Clothing-Stitching-Project-Record.md  Historical requirements and decision record
```

Operational data directories, virtual environments, backups, restore checks and SQLite files are excluded from Git.

## Windows installation

Open PowerShell in the project directory. The recorded development and shop deployments use paths similar to:

```text
C:\Users\<user>\Yathreb-Safeer\Inventory
```

Check Python:

```powershell
py -3.13 --version
```

Create the local virtual environment and install dependencies:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Expected direct dependencies:

```text
Flask==3.1.3
waitress==3.0.2
```

## Database lifecycle

Examples below use `data-v4` as the operational directory.

### Create a fresh database

Run this once only when no database exists:

```powershell
.\.venv\Scripts\python.exe .\manage.py --data-dir .\data-v4 init
```

Initialization prompts for one owner username and a 12–128-character password. It creates schema version 5, the seven Product definitions and no sample Brands, stock, Customers, stitching rates or Tailors.

Initialization refuses to overwrite any existing database.

### Check an existing database

```powershell
.\.venv\Scripts\python.exe .\manage.py --data-dir .\data-v4 check
```

A valid current database reports:

- SQLite integrity: `ok`
- foreign keys: `ok`
- schema version: `5`
- Product hierarchy: `ok`
- sales, Customer, measurement, tailoring, Tailor-assignment and payment foundation: `ok`

### Upgrade a verified schema-v4 database

Use this only for an existing schema-v4 database that has not already been upgraded. The command creates and validates a mandatory recovery backup before applying the Tailor schema:

```powershell
$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$upgradeBackup = ".\backups\data-v4-before-tailors-$backupStamp.sqlite3"

.\.venv\Scripts\python.exe .\manage.py `
    --data-dir .\data-v4 `
    upgrade-v5 `
    --backup-to $upgradeBackup
```

Never run `upgrade-v5` on a schema-v5 database.

### Reset the owner password

```powershell
.\.venv\Scripts\python.exe .\manage.py --data-dir .\data-v4 reset-password
```

The password change invalidates existing management sessions.

## Run the application

Local management access:

```powershell
.\.venv\Scripts\python.exe .\manage.py `
    --data-dir .\data-v4 `
    serve --host 127.0.0.1 --port 8080
```

Open:

```text
http://127.0.0.1:8080
```

Press `Ctrl+C` to stop the foreground service.

### Trusted private-LAN access

Find the main computer’s current private IPv4 address:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -like '10.*' -or
        $_.IPAddress -like '172.*' -or
        $_.IPAddress -like '192.168.*'
    } |
    Select-Object InterfaceAlias, IPAddress
```

Start the service on one specific private address:

```powershell
$shopHostAddress = '192.168.1.25'

.\.venv\Scripts\python.exe .\manage.py `
    --data-dir .\data-v4 `
    serve --host $shopHostAddress --port 8080
```

Management URL:

```text
http://192.168.1.25:8080
```

Tailor View URL:

```text
http://192.168.1.25:8080/tailor
```

Replace the example with the address currently assigned to the shop PC. Both devices must be on the same trusted network. Windows Firewall must permit the private-network connection. Do not use a public address or router port forwarding.

## Automated verification

The current test suite creates temporary databases and does not write to `data-v4`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Current expected result:

```text
Ran 131 tests
OK
```

The final production baseline was user-verified on Windows with all 131 tests passing, followed by successful schema-v5 integrity and browser QC checks.

## Backup and recovery

Back up to a separate physical device when possible. Treat every backup as private business data.

Create a timestamped, non-overwriting, integrity-checked backup:

```powershell
$shopBackupRoot = 'E:\Yathreb-POS-Backups'
$shopBackupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$shopBackupFile = Join-Path $shopBackupRoot "inventory-$shopBackupStamp.sqlite3"

.\.venv\Scripts\python.exe .\manage.py `
    --data-dir .\data-v4 `
    backup --to $shopBackupFile
```

The backup command uses SQLite’s online backup API, includes committed WAL data, checks the resulting database and refuses to overwrite an existing filename.

Test restoration into a new directory:

```powershell
$restoreDirectory = ".\restore-check-$shopBackupStamp"

.\.venv\Scripts\python.exe .\manage.py `
    --data-dir $restoreDirectory `
    restore --from $shopBackupFile

.\.venv\Scripts\python.exe .\manage.py `
    --data-dir $restoreDirectory `
    check
```

Restore never overwrites the working directory. It rotates the restored session secret and invalidates sessions from the backed-up database.

A restored copy can be served separately for inspection:

```powershell
.\.venv\Scripts\python.exe .\manage.py `
    --data-dir $restoreDirectory `
    serve --host 127.0.0.1 --port 8081
```

## Safe source updates

Source code and operational data have different lifecycles. Updating Git source must never replace `data-v4`.

A typical source-only update is:

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
git status
```

Before any deployment update:

1. stop the running service;
2. create an integrity-checked backup;
3. preserve the previous source installation;
4. update or replace source files;
5. retain the authoritative `data-v4`;
6. verify dependencies;
7. run the full test suite;
8. run the database check;
9. start the service and complete browser QC.

Do not commit `.venv`, SQLite files, backups, real PINs or other operational credentials.

## Recommended operating checklist

### Before first real use

- Confirm the final pair/piece unit for every Product still marked proposed.
- Add the real Brand/Article/Colour/Size hierarchy.
- Configure required standard stitching rates.
- Add active Tailors.
- Verify the thermal printer and 80 mm paper settings.
- Configure the Tailor View PIN only if the LAN view will be used.
- Create and restore-test the first clean production backup.

### Daily

- Confirm the application opens from the main shop computer.
- Use the management pages only against the authoritative shop-PC database.
- Review any negative stock shown after sales.
- Create a dated backup at the agreed daily closing time.

### Periodically

- Copy verified backups to a separate physical device.
- Test restoration into a new directory.
- Check disk space and Windows updates.
- Reconfirm printer and private-LAN access after network changes.

## Deliberate limitations and open work

The current foundation does not yet implement:

- returns, refunds, exchanges, cancellations or bill editing;
- damage, wastage and authorized stock-adjustment workflows;
- supplier, purchase-cost, profit, roll or dye-batch records;
- payment methods, payment allocation notes or categories;
- staff roles, granular permissions or a full audit log;
- automatic tailoring status transitions and delivery completion rules;
- Tailor assignment history;
- cumulative/overall reporting beyond the current Sales History, daily and monthly reports;
- silent printer control;
- automatic backup scheduling and retention policy;
- automatic LAN discovery or a native Android Tailor app;
- cloud synchronization or public remote access.

Important business decisions also remain open for price-change authorization, non-Pakistan mobile normalization, shared-family mobile handling, final non-fabric units, operational backup targets and formal return/refund policy.

## Production readiness boundary

The deployed application is a verified local operational foundation for Yathreb’s current inventory, billing, tailoring, Customer-account and payment workflows. It should not be described as covering the deliberate limitations above until those policies and features are designed, implemented and tested.

The shop PC remains the source of truth. Preserve its operational database, maintain verified backups, and test every future source update against a copy before applying it to live operations.
