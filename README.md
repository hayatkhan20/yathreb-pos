# Shop inventory foundation

This milestone provides the persistent catalogue and positive stock-entry foundation for Phase 1. It is not the completed POS: it does not record sales, prices, payments, receipts, returns, or sales reports.

## Stack and operating shape

The application uses Python 3.13, Flask 3.1.3, Waitress 3.0.2, SQLite, server-rendered HTML/CSS, and a small self-hosted vanilla JavaScript enhancement. SQLite is included with Python. There is no Node.js toolchain, frontend compilation, container, or separate database server. This keeps the installation and memory use modest for the recorded Windows 10 shop computer.

The main shop computer owns one local database file and runs one application service. Its browser can connect through `127.0.0.1`. An optional second terminal can connect to that same service over the private shop network; it must not have another copy of the working database. Waitress supports Windows and Python 3.9 or newer, Flask 3.1 supports Python 3.9 or newer, and Python 3.13 supports Windows versions older than Windows 10 as documented by their maintainers:

- [Python 3.13 on Windows](https://docs.python.org/3.13/using/windows.html)
- [Flask installation and supported Python versions](https://flask.palletsprojects.com/en/stable/installation/)
- [Waitress platform support](https://docs.pylonsproject.org/projects/waitress/en/latest/)

The exact Windows 10 build and 32/64-bit system type still need to be checked before choosing the matching Python installer.

## What the source implements

- The seven recorded Product definitions: Fabric, Chappal / Peshawari Chappal, Shawl, Wallet, Studs, Waistcoat, and Coat.
- Fabric as Product → Brand → Article → Colour; sized products as Product → Brand → Colour → Size; the other recorded products as Product → Brand → Colour.
- Parent-scoped ownership throughout: brands belong to products, Fabric articles belong to brands, Fabric colours belong to articles, other colours belong to brands, and sizes belong to colours.
- Duplicate names are rejected within an immediate parent, while the same article, colour, or size name can be used under a different parent.
- Editable Product and catalogue labels with permanent internal IDs. Renaming does not move stock or rewrite saved history.
- A stock variant can be created only from a valid complete chain whose records belong to the same parents.
- Metres for Fabric and pairs for Studs as confirmed units. The proposed pair/piece units for the other seeded products remain unconfirmed and block stock entry until the owner explicitly chooses one.
- Quantities stored as scaled integers, never binary floating point. Metres can be represented to three decimal places; this is storage capacity and does not decide the shop’s minimum cutting increment. Pairs and pieces require whole numbers.
- Permanent positive movements for opening stock and incoming stock. An opening entry is limited to the first movement for an exact combination. Corrections and all sale-related movement types remain for later policy work.
- Transactional exact-variant creation and stock movement saving. A unique form reference makes a repeated identical submission safe and rejects reuse with changed details.
- SQLite foreign keys, validation constraints, a 10-second busy wait, `BEGIN IMMEDIATE` writes, and WAL mode so multiple browser terminals use the same authoritative service safely for this milestone’s stock additions.
- Current Stock choices that cascade immediately within the selected parent chain. JavaScript loads choices from the authenticated service and clears invalid descendants; one Apply filters button refreshes the stock results after selection.
- A server-rendered no-JavaScript fallback that progressively loads the next Current Stock level through the same GET form, plus catalogue anchors that retain the relevant management position after open, add and rename actions.
- A current-stock page with Product-relevant, parent-scoped filters and separate metre, pair, and piece totals.
- An append-only movement-history view that preserves the names and unit recorded at entry time.
- A single owner login, CSRF protection, host validation, conservative request limits, security headers, and a short global login-attempt lock. Staff roles and permissions remain unresolved.
- Explicit initialization, integrity checking, password reset, non-overwriting backup, and restore-to-new-directory commands. Application startup never creates, reseeds, or migrates a database.

## Source layout

```text
manage.py                         Setup, check, backup, restore, and service commands
requirements.txt                  Direct Python dependencies
shop/__init__.py                  Flask application factory and request safeguards
shop/auth.py                      Owner sign-in, sign-out, CSRF, and login throttling
shop/db.py                        SQLite connection and explicit initialization
shop/inventory.py                 Catalogue and stock-ledger operations
shop/web.py                       Server-rendered routes
shop/migrations/001_initial.sql   Initial schema and Product metadata
shop/templates/                   Browser pages
shop/static/app.css               Local responsive styling
shop/static/app.js                Cascading filters and fragment scrolling
tests/                            Data, web behavior, and recovery checks for the user to run
```

The `data`, `trial-data`, timestamped earlier-trial, `restore-check`, and `backups` directories are ignored by Git. No database or dependency lockfile is included.

## Windows setup and verification

Use 64-bit Python when Windows reports a 64-bit operating system; otherwise use the 32-bit Python installer. Install a current Python 3.13 release from Python.org with the Python launcher and `pip`. All commands below use Windows PowerShell and this working directory:

```powershell
Set-Location 'C:\Users\hanif\Desktop\Yathreb-Safeer\Inventory'
```

First inspect the operating system before selecting an installer:

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, OSArchitecture
```

Expected result: a row identifying Windows 10, its build/version, and either a 64-bit or 32-bit architecture. If it does not report Windows 10, stop and review runtime compatibility before installation.

After installing the matching Python 3.13 release, verify the launcher:

```powershell
py -3.13 --version
```

Expected result: `Python 3.13.x`.

Create a project-local virtual environment and install the declared dependencies:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Expected result: `.venv` is created, and pip reports successful installation of Flask 3.1.3, Waitress 3.0.2, and their dependencies. Pip may generate only its normal environment metadata; there is no project lockfile to fabricate.

Run the automated checks. They create temporary databases outside the working data directories and remove them afterward:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected result: 18 tests run and the final line is `OK`. These checks include parent-scoped duplicate rules, rejection of cross-parent stock combinations, canonical dependent-choice responses, server-rendered filter fallback, and catalogue position targets. Share the complete output if any test fails.

### Trial database and browser verification

Revision 0.7 does not change the schema. If the existing disposable trial database was created from the corrected Product hierarchy and the check command below reports Product hierarchy `ok`, reuse it and skip the archive/initialization block. The block is needed only when no trial database exists or the existing one predates the Product hierarchy correction.

The corrected initial schema is intentionally incompatible with a trial database created from the earlier model. Preserve an existing trial directory under a timestamped name, then initialize a new disposable trial database. Initialization prompts for an owner username and a password of 12–128 characters and refuses to overwrite any existing database:

```powershell
$TrialData = Join-Path (Get-Location) 'trial-data'
if (Test-Path -LiteralPath $TrialData) {
    $TrialArchive = Join-Path (Get-Location) ("trial-data-before-product-hierarchy-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
    Move-Item -LiteralPath $TrialData -Destination $TrialArchive
    Write-Host "Previous trial data preserved at $TrialArchive"
}
.\.venv\Scripts\python.exe manage.py --data-dir .\trial-data init
```

Expected result: any earlier `trial-data` directory is preserved beside the project under a timestamped name. A new `trial-data\inventory.sqlite3` is created with seven Product definitions, one owner, and no sample brands or stock.

Check it, then start the local-only service:

```powershell
.\.venv\Scripts\python.exe manage.py --data-dir .\trial-data check
.\.venv\Scripts\python.exe manage.py --data-dir .\trial-data serve
```

Expected check result: SQLite integrity `ok`, foreign keys `ok`, schema version 1, and Product hierarchy `ok`. Expected service result: it prints `http://127.0.0.1:8080` and waits for requests. Leave that PowerShell window open and enter that address in a browser. Press `Ctrl+C` in PowerShell to stop the service.

In the browser, verify these behaviours with trial names and quantities only:

1. Sign in with the trial owner.
2. On Current Stock, select Fabric and confirm its brands appear without Apply filters. Select a brand and article in turn and confirm only that parent’s articles and colours appear. Change an earlier selection and confirm all invalid later selections clear immediately.
3. Repeat with one Brand → Colour Product and one Brand → Colour → Size Product. Use Apply filters once after the desired chain is selected, then refresh and confirm all valid selected values remain selected.
4. Temporarily disable JavaScript in the browser and confirm the same Current Stock GET form can load one level at a time by using Apply filters. Re-enable JavaScript afterward.
5. Open Catalogue; open, add and rename a Product, Brand, Article, Colour and Size as applicable. Confirm each response stays at the relevant management section and preserves its selected parent chain.
6. Confirm one proposed non-fabric unit only if you know the real unit choice, then add its relevant brand/colour/size labels in parent order.
7. Add opening stock to a new exact combination, followed by incoming stock.
8. Confirm Current stock shows the correct exact combination and unit-separated total.
9. Rename one catalogue label and confirm current stock uses the new label while History retains the old label on the earlier movement.
10. Refresh the successful stock submission and confirm it does not add stock again.

Do not enter real shop data into the trial database.

### Operational database

After the checks and trial workflow succeed, initialize the default operational database once:

```powershell
.\.venv\Scripts\python.exe manage.py init
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py serve
```

Expected results: `data\inventory.sqlite3` is created without sample stock, the integrity check reports `ok`, and the service listens only at `http://127.0.0.1:8080`. Subsequent starts use only the `serve` command. Running `init` again refuses to overwrite the database.

To reset a forgotten owner password from the main computer:

```powershell
.\.venv\Scripts\python.exe manage.py reset-password
```

Expected result: after two matching password prompts, the password changes and all existing browser sessions become invalid.

## Optional second terminal

Keep the database on a local disk in the main shop computer. Never put `inventory.sqlite3` on a shared network drive. On the main computer, inspect its private IPv4 addresses:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, IPAddress, PrefixOrigin
```

Choose the address belonging to the shop network in one of the private ranges `10.*`, `172.16.*` through `172.31.*`, or `192.168.*`. Then replace the example below with that exact address:

```powershell
$ShopHostAddress = '192.168.1.25'
.\.venv\Scripts\python.exe manage.py serve --host $ShopHostAddress
```

Expected result: the service prints a URL using that address. The second terminal can enter the same URL in its browser and will use the main computer’s service and database. The command accepts only loopback or a specific private IPv4 address. Private-network firewall permission and a stable address are operating-system/network tasks still to be arranged by the user; do not expose the service through router port forwarding or a public network. The current LAN connection uses ordinary HTTP, so use it only on the trusted shop network.

## Backup and restore check

Back up to a separate physical device when possible. Treat each backup as private business data and restrict who can read or copy it. The example assumes that device is drive `E:`; replace it with the actual approved destination. The backup command uses SQLite’s online backup API, includes committed WAL data, integrity-checks the result, and refuses to overwrite a filename:

```powershell
$ShopBackupRoot = 'E:\Yathreb-Inventory-Backups'
$ShopBackupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ShopBackupFile = Join-Path $ShopBackupRoot "inventory-$ShopBackupStamp.sqlite3"
.\.venv\Scripts\python.exe manage.py backup --to $ShopBackupFile
```

Expected result: one new backup file and a `Backup created and integrity checked` message. Choose a new filename for every backup.

Test restoration into a new, unused directory; restore never overwrites the working database:

```powershell
$ShopRestoreDirectory = ".\restore-check-$ShopBackupStamp"
.\.venv\Scripts\python.exe manage.py --data-dir $ShopRestoreDirectory restore --from $ShopBackupFile
.\.venv\Scripts\python.exe manage.py --data-dir $ShopRestoreDirectory check
.\.venv\Scripts\python.exe manage.py --data-dir $ShopRestoreDirectory serve --port 8081
```

Run the restore commands in the same PowerShell session as the backup commands, or set `$ShopBackupFile` to the exact existing backup path first. Expected results: restore and integrity-check messages, followed by a separate service at `http://127.0.0.1:8081`. Sign in using the credentials stored in the backup and compare important catalogue and stock totals. Stop it with `Ctrl+C`. A real recovery can run from a newly restored directory in the same way, leaving damaged or uncertain files untouched for investigation.

Backup scheduling, destination, retention, recovery-time target, and acceptable data-loss window remain open operating decisions.

## Scope still open

This source intentionally does not decide pricing level, currency, tax treatment, discounts, payment methods or allocation, customer details on bills, credit sales, returns, exchanges, cancellations, damaged stock, adjustment authorization, supplier/purchase records, roll and dye-batch tracking, receipt hardware/layout, sales-report definitions, business-day timezone, staff roles, automatic service startup, or automated backup policy. These decisions belong to later milestones recorded in `Clothing-Stitching-Project-Record.md`.
