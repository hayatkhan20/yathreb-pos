# Current Project State

This is the concise briefing for routine work. `Clothing-Stitching-Project-Record.md` remains the historical archive.

## Architecture and stack

- Local browser application using Python 3.13, Flask 3.1.3, Waitress 3.0.2, standard-library SQLite, server-rendered HTML/CSS, and small self-hosted vanilla JavaScript enhancements.
- No Node.js build, Docker, microservices, separate database server, or external frontend assets.
- The main shop computer runs one service and stores one SQLite database on its local disk. Its browser uses `127.0.0.1`; an optional second terminal connects to the same service over the trusted private LAN.
- Never create independent terminal databases or place the SQLite database on a shared network drive.

## Confirmed Product hierarchy and units

| Product | Required hierarchy | Unit status |
| --- | --- | --- |
| Fabric | Product → Brand → Article → Colour | Metres confirmed |
| Chappal / Peshawari Chappal | Product → Brand → Colour → Size | Pairs proposed; owner confirmation required |
| Shawl | Product → Brand → Colour | Pieces proposed; owner confirmation required |
| Wallet | Product → Brand → Colour | Pieces proposed; owner confirmation required |
| Studs | Product → Brand → Colour | Pairs confirmed; quantity 1 is one pair |
| Waistcoat | Product → Brand → Colour → Size | Pieces proposed; owner confirmation required |
| Coat | Product → Brand → Colour → Size | Pieces proposed; owner confirmation required |

- Use `Product` throughout the application and documentation.
- Every child belongs to one immediate parent. Articles, colours, and sizes are parent-scoped, not global.
- Duplicate normalized names are rejected within the same immediate parent and allowed under different parents.
- Occasional non-fabric design differences use distinct brand records such as Hayat Alpha and Hayat Beta; there is no extra design/model level.

## Critical database and security invariants

- Stable integer IDs preserve balances and relationships when labels are renamed.
- Exact stock variants require one valid complete parent chain. Application validation, foreign keys, uniqueness constraints, and database triggers enforce ownership.
- Quantities use integer thousandths. Metres support three decimal places; pair and piece quantities are whole numbers.
- Current stock is derived from append-only movements. Each movement stores its unit, UTC timestamp, user, optional note, request identity, and historical label snapshot.
- Stock writes use serialized transactions. Request keys and content digests prevent duplicate submissions and reject changed replays.
- Money uses integer PKR paisa. Sale quantities use the same integer thousandths as stock; each line total is rounded half-up to the nearest paisa after multiplying quantity by unit price.
- Finalizing a sale saves its header, immutable item snapshots, and one matching negative stock movement per item in one serialized transaction. Request keys and content digests make retries idempotent.
- Sales never check or clamp the recorded balance. A sale may make an exact variant negative, and later incoming movements correct that balance through the normal sum.
- Finalized sale headers, item labels, quantities, prices, totals, and linked stock movements are immutable. Printing or reprinting must never create a sale or deduct stock.
- Schema version 4 stores authoritative Customer records with sequential `CUST-######` identities. Primary and alternate mobiles have searchable digit-normalized forms; duplicate primary numbers are blocked by default, while an explicit service flag permits a future shared-family-number decision.
- Each Customer has one measurement-profile container with append-only revisions. The seven standard templates are Pakistani Waistcoat, Three-Piece Waistcoat, Coat, Sherwani, Pant, Shalwar Kameez and Shirt; Other / Custom Item remains flexible and is not an eighth standard template. Numeric values use integer thousandths of an inch, checkbox styles use booleans, and tailoring items copy immutable measurements, styles and notes.
- Standard tailoring uses the latest configured append-only PKR-paisa stitching-rate revision and cannot be finalized without one or overridden per order. The rate table is initially empty. Other / Custom Item accepts a manual stitching price. Finalized items retain the selected rate identity and amount.
- Combined bill finalization saves product sale items/movements, an optional multi-item tailoring order, measurement snapshots and one finalized BILL atomically. Tailoring-only bills create no inventory movement. Tailoring or an outstanding balance requires an authoritative Customer.
- Tailoring statuses are limited to Received, In Progress, Ready and Delivered. Status is the only mutable tailoring-order field; items, charges and measurement snapshots remain immutable.
- Later bill payments are immutable `PAY-######` records with retry protection. They apply to one Customer-owned bill, never rewrite its original paid amount or balance, cannot exceed the derived outstanding amount, and never create inventory movements or new sales.
- Billing drafts are browser input and remain untrusted. Final submission revalidates the exact variants, quantities and PKR inputs, recalculates every line and total, and redirects to the saved bill after atomic finalization.
- Catalogue deletion is permanent only for an unused leaf record. The service checks children and exact-variant references inside a serialized transaction; restrictive foreign keys remain the final safeguard. It never cascades into inventory or sales, and the seven seeded Product definitions cannot be deleted.
- Sales search and report ranges use parameterized queries. Daily and monthly reports group finalized UTC timestamps by Pakistan Standard Time (UTC+05:00), using local midnight as the calendar-day boundary.
- SQLite uses foreign keys, WAL mode, a busy timeout, and local-disk storage. Initialization refuses overwrite, and application startup never creates or migrates a database implicitly.
- Business pages require an authenticated owner session. Passwords are hashed; POST requests require CSRF validation. Host validation, session invalidation, login throttling, request limits, no-store responses, and security headers remain enabled.
- Backup and restore operations are non-overwriting and integrity-checked. Operational backup destination, schedule, retention, and recovery targets remain unresolved.

## Completed functionality

- Explicit database initialization and integrity/schema checking.
- Owner sign-in/sign-out, password reset, and session invalidation.
- Successful sign-in opens a task-oriented Dashboard while Current Stock remains available at `/`. The Dashboard gives New Sale clear priority, followed by daily customer/order/payment shortcuts, stock actions, and a secondary Records and Setup section using the existing safe routes.
- Product catalogue management with add, rename, and guarded deletion operations for Products, Brands, Articles, Colours, and Sizes while preserving parent ownership. Open Product appears first; Product-level management is the final, collapsed section.
- Explicit confirmation of proposed pair/piece units before stock entry.
- Catalogue hierarchy dropdowns follow each Product's parent-scoped structure and navigate immediately when JavaScript works; Open buttons remain as the server fallback. Each child dropdown offers “+ Add new…”, new records become the selected value, and the next applicable level appears. The selected chain and relevant page position remain intact after open, add, rename, and validation responses.
- Positive opening and incoming stock entry for valid exact variants, with duplicate-submission protection. Add Stock hierarchy choices cascade automatically, allow Products and each relevant child level to be added in one reusable popup, reveal the entry fields only after a complete valid chain, preserve the form after validation errors, and retain Catalogue/Open selection fallbacks without JavaScript.
- Current Stock with parent-scoped cascading filters, one final Apply filters action, refresh-persistent selections, product-by-product totals, and a server-rendered no-JavaScript fallback.
- Product-specific current totals and exact-variant movement history with rename-safe snapshots.
- Phase 2A backend sales and billing foundation: one or many exact variants per PKR bill, current default prices per variant with bill-time overrides, fixed bill discount, no tax, and server-derived totals. A fully paid product-only bill may remain anonymous; an outstanding balance requires an existing Customer record.
- Unique `BILL-########` numbers and UTC timestamps, immutable sale-time hierarchy/price snapshots, atomic negative sale movements, duplicate-submission protection, and deliberately visible negative stock balances.
- Schema version 4 (`measurement-templates-rates-v4`) fails explicitly against incompatible schema-version-3 databases so they can be preserved and recreated separately.
- Phase 3A/3A.1 backend foundation: sequential Customers, searchable normalized mobiles, seven confirmed revisioned measurement templates plus flexible Other / Custom Item, append-only default stitching rates, sequential multi-item tailoring orders, combined product/service bills, separate later payments and derived customer balances.
- The original product-only finalization remains compatible. Billing now uses the atomic combined service for product-only, tailoring-only, or combined product-and-stitching bills; later-payment collection remains service-only.
- Billing has one combined cart, BILL number, discount, initial payment and remaining balance. A guided sale-type selector shows the relevant Product and tailoring entry sections for Products only, Products + stitching, or Stitching only when JavaScript is available, while the complete server fallback remains available without JavaScript. It retains automatic parent-scoped Product selection, price overrides and negative-stock handling. Customer search shows live ID/name/mobile suggestions; an inline dialog creates and automatically selects a validated Customer without leaving Billing or losing the current draft. The existing server search and standalone Customers page remain as fallbacks.
- Billing isolates Product and tailoring actions so tailoring fields never trigger Product-quantity validation. Product additions show a top confirmation and compact current-bill summary while retaining the complete bill table. Current-bill Fabric is linked automatically when exactly one eligible Fabric line exists, requires an explicit choice when several exist, and keeps Customer-provided or eligible earlier-bill Fabric available as alternate sources.
- Standard tailoring draft lines use the selected Customer's latest matching measurements and current configured rate. Custom lines use an exact matching custom measurement description and manual price. Shop cloth links reference a current-bill Fabric line or an earlier finalized Fabric line owned by that Customer without deducting stock again; Customer-provided cloth has no product link or movement.
- Exact-variant default-price editing is available from Billing. A bill-time override remains confined to that immutable sale snapshot.
- Read-only Sales History and finalized bill pages show combined bill totals. The browser-printable 80mm receipt includes product and tailoring lines, Customer and tailoring identities, cloth source and promised date while keeping measurement detail off the customer receipt.
- Authenticated navigation prioritizes daily counter work in this order: Dashboard, Billing, Orders / Collection, Customers, Current Stock, Add Stock and Sales. Catalogue, Measurements and Stitching Rates remain available in a secondary Setup group, followed by Logout. Customer records and balances/payments remain separate pages reached through clear tabs within the Customers area; active states and the collapsible mobile menu are preserved.
- Phase 3B1 customer screens list and search Customer ID, name or normalized mobile, add and edit contact records without changing generated identity, show derived outstanding balance, and link to measurements. Duplicate normalized primary mobiles remain blocked by default.
- Measurement screens render the seven authoritative templates, decimal-inch fields, Boolean style checkboxes and notes from backend definitions. Billing can add or update the selected Customer's matching garment measurements in an inline dialog without losing the current bill; saved values become current and refresh matching draft tailoring lines. The standalone page remains available as a fallback, retains read-only history, and keeps Other / Custom Item descriptions and flexible named measurements separate.
- Stitching Rates shows every standard garment as configured or Not configured, appends validated PKR rate revisions, and displays effective history. Other / Custom Item remains manually priced at tailoring-order creation.
- Tailoring Orders lists and searches finalized orders by BILL number, TAIL number or Customer identity, filters the controlled status, and shows the current outstanding balance after later payments. Order detail keeps original bill values distinct from current outstanding and provides direct bill, customer-account and Receive payment actions. Cloth sources and immutable measurement snapshots remain visible; status changes remain unavailable.
- Customer accounts show total billed, total paid and current outstanding across product-only, tailoring-only and combined bills, while keeping the bill's remaining-at-finalization value distinct. Customer Balances searches by Customer identity and can show outstanding-only or all accounts.
- Later payments are recorded against one explicit outstanding Customer bill through the atomic payment service. Successful submissions redirect to an immutable printable `PAY-######` 80mm acknowledgement; Customer and bill pages show payment history and current derived balances without changing the historical sale receipt.
- Sales History supports one case-insensitive search for bill number, customer name, or mobile, with a Clear action. Daily and monthly finalized-sales reports default to the current Pakistan date/month, accept another valid period, total bill count and all recorded bill amounts, and link each listed bill to its receipt.
- Integrity check, non-overwriting backup/restore, local service, and optional private-LAN service commands.
- One hundred twenty-two automated test methods are present in source. Test execution remains the user's responsibility.
- Tailoring status updates, payment-method allocation, refunds, returns, bill/payment cancellation or editing, and cumulative reporting are not implemented; this remains an incremental POS foundation.

## Unresolved business decisions

- Final pair/piece units for Chappal, Shawl, Wallet, Waistcoat, and Coat.
- Price-change authorization and price history beyond immutable sale snapshots.
- Customer mobile matching for non-Pakistan numbers and whether shared family numbers should be routinely enabled; the service currently normalizes common Pakistan prefixes and requires an explicit shared-number override.
- Tailoring status-transition permissions, worker assignment, delivery completion details, and whether promised dates may ever be omitted. Schema 4 requires a promised date and permits controlled status changes without inventing transition rules.
- Initial PKR stitching-rate amounts for all seven standard garments; schema 4 deliberately seeds none and blocks standard tailoring until each required rate is configured.
- Payment methods and allocation, and payment notes/categories.
- Returns, refunds, exchanges, cancellations, corrections, damage, and adjustment authorization.
- Supplier, purchase-cost and profit records; roll or dye-batch tracking, cutting increments, wastage, and leftovers.
- Thermal printer model, operating-system print settings, and any silent-print requirement. Receipt printing currently uses the browser print dialog.
- Cumulative reporting and any future non-midnight business-day cut-off. Daily/monthly reports currently use Pakistan calendar periods; discounts are shown as their saved fixed bill amounts.
- Staff roles, permissions, audit policy, automatic service startup, LAN address/firewall setup, and operational backup policy.

## Standard user-run verification

Working directory: `C:\Users\hanif\Desktop\Yathreb-Safeer\Inventory`

```powershell
Set-Location 'C:\Users\hanif\Desktop\Yathreb-Safeer\Inventory'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected result: 124 tests run and the final result is `OK`. Codex must report this as unverified until the user supplies the output.
