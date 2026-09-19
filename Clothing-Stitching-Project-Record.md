# Clothing and Stitching Brand — Continuous Project Record

Revision: 0.7 — Cascading filters and catalogue position

Status: The catalogue and positive stock-entry foundation now uses the confirmed Product terminology and parent-scoped hierarchy in source, with automatically cascading Current Stock choices and position-preserving catalogue management. This source change does not alter the schema, so a corrected Product-hierarchy trial database can be reused. The user retains dependency installation, tests, local execution and verification. This milestone is not the completed POS; sales, payments, receipts and sales reports have not been implemented.

## 1. Working agreement

- Preserve the earlier planning-first agreement. The latest user message authorizes moving to code development through Codex with source-writing only; this does not turn unresolved business rules into confirmed requirements.
- Keep this record continuous; carry forward confirmed decisions and unresolved questions.
- Avoid repeatedly asking for information already supplied.
- Separate confirmed user requirements, developer recommendations, and open decisions.
- A recommendation is not an approved requirement or a finalized technical choice.
- Preserve earlier decisions and explain any proposed change that affects them.
- Ease of use is an explicit user priority. Keep workflows and required fields simple; occasional edge cases must not introduce an unwanted product-design hierarchy.
- Codex writes and edits source code, configuration and documentation. The user installs libraries/dependencies, performs setup and runs the app locally, with instructions and troubleshooting guidance from the assistant.
- Do not execute dependency installation, app scaffolding commands that install packages, database setup/migrations, app startup, builds, tests or deployment on the user's behalf under the current code-only workflow. Provide the applicable Windows commands for the user to run instead. Read-only inspection and source review are allowed.
- Do not claim the app ran, a build passed or tests passed unless the corresponding execution actually occurred and its results are available. Distinguish source review from user-run verification.
- Preserve this agreement in the project's AGENTS.md and carry forward progress through the same project record.

## 2. Product boundaries and priority

| Area | Confirmed purpose | Current priority |
| --- | --- | --- |
| Public brand website | A website for the clothing and stitching brand. Exact content and commercial functions are not specified. | Deferred; no website implementation now. |
| Inventory and POS | Manage fabric, footwear, accessories and stocked garments; record sales, print bills, and report sales. Must be usable without the tailoring software. | Phase 1 focus: transition to code-only development through Codex, preserving approved requirements. |
| Tailoring customer management | Store customer details, garment measurements and payment records, including stitching cloth bought elsewhere. Must be usable without inventory/POS. | Future phase; requirements retained below. |

Independence of the two management applications is a confirmed operational requirement. Whether they have separate installations, databases, or a common optional platform remains undecided. A public website must not be confused with the private management interface. E-commerce, checkout, stock synchronization, and customer accounts on the public website are not yet requested.

## 3. Confirmed Phase 1 requirements

| ID | Requirement |
| --- | --- |
| INV-01 | Support multiple brands across the stocked products. Yathreb and Indicote are user-provided examples. |
| INV-02 | For fabric, each brand has articles. Yathreb examples: Dastan, Hayat, and Safeer. Do not assume every other product must use articles. |
| INV-03 | Each fabric article has colour variants. Dastan having ten colours is the user's example, not a fixed system limit. |
| INV-04 | Allow users to add brands, articles and colours. The user additionally confirmed adding/editing products, brands, colours and sizes. Do not hard-code a fixed catalogue. |
| INV-05 | Record inventory and add incoming stock. Detailed purchase and supplier workflows remain open. |
| INV-06 | Sell fabric by measured length in metres. The provided example is four metres of blue Dastan. |
| INV-07 | A sale reduces the stock of the selected brand/article/colour, and the article's aggregate inventory reflects that reduction. Other colour variants are unaffected. |
| INV-08 | Include Chappal / Peshawari Chappal, classified by brand, colour and size. Each brand can offer multiple colours, and each colour multiple sizes. |
| INV-09 | Include shawls, wallets and studs. Each of these products is classified by brand and colour. |
| INV-10 | Include stocked waistcoats and coats, each classified by brand, colour and size. These retail stock records are distinct from future made-to-order stitching records. |
| INV-11 | Each valid colour/size combination has its own stock quantity. Do not pool sizes when recording a sale. |
| INV-12 | For infrequent non-fabric products with different designs but identical colours/sizes, use separate brand entries with distinguishing names, such as Hayat Alpha and Hayat Beta. Do not add an extra design/model level in Phase 1. The existing fabric article level remains required. |
| INV-13 | Count and sell studs in pairs. A quantity of 1 means one pair, and selling it deducts one pair from the selected brand/colour stock. |
| INV-14 | Use Product as the domain term throughout the interface, backend, database schema, routes, tests and current documentation. The earlier term is superseded. |
| INV-15 | Enforce immediate ownership: every brand belongs to one Product; every Fabric article belongs to one brand and every Fabric colour belongs to one article; every non-fabric colour belongs to one brand; every size belongs to one colour. Articles, colours and sizes are not global lists. |
| INV-16 | Allow the same child name under different parents, reject duplicate names under the same immediate parent, and create stock only from a valid complete chain belonging to those same parents. |
| POS-01 | Record sales through a POS/billing workflow. |
| POS-02 | Produce a printable bill/receipt. Printer, paper size, required fields and layout remain open. |
| REP-01 | Provide daily sales, monthly sales and overall/cumulative sales. Exact metrics and reporting cut-off remain open. |
| SCOPE-01 | Phase 1 operates independently of tailoring customer management. |
| UX-01 | Prioritize easy-to-use software. Prefer straightforward inventory entry and billing with only the fields relevant to the chosen Product. Exact screen layouts are still to be agreed. |
| UX-02 | On Current Stock, selecting a Product immediately loads only its brands; selecting each applicable parent immediately loads only its articles, colours or sizes and clears invalid descendants. Applying filters remains one final action for refreshing results, and valid selections survive that refresh. A server-rendered progressive fallback remains available without JavaScript. |
| UX-03 | Catalogue open, add and rename actions retain the selected parent chain and return the user to the relevant Product, Brand, Article, Colour or Size management section. |

### Inventory interpretation

The initial fabric-only interpretation is expanded to Product-specific variants. Fabric uses Product → Brand → Article → Colour. Chappal / Peshawari Chappal, Waistcoat and Coat use Product → Brand → Colour → Size. Shawl, Wallet and Studs use Product → Brand → Colour. The user resolved the non-fabric design distinction in revision 0.3: occasional designs are separate brand entries, such as Hayat Alpha and Hayat Beta, without an additional design/model field.

The ownership chain is a confirmed domain rule, not just an interface filter. A Fabric colour is owned by one article, each other colour is owned by one brand, and a size is owned by one colour. Duplicate normalized names are rejected within the same immediate parent but remain valid under another parent. Stock combinations must pass the entire chain in both application validation and database constraints.

These names represent separate brand records in the software. Their stock and brand-level reporting remain separate unless the user later requests grouping; do not silently infer a parent Hayat brand or add a hidden model hierarchy. This does not change the fabric article structure previously specified.

| Product | User-specified hierarchy within Product | Stock unit status |
| --- | --- | --- |
| Fabric | Brand → Article → Colour | Metres confirmed; fractional increment remains open. |
| Chappal / Peshawari Chappal | Brand → Colour → Size | Pair proposed; not yet confirmed. |
| Shawl | Brand → Colour | Piece proposed; not yet confirmed. |
| Wallet | Brand → Colour | Piece proposed; not yet confirmed. |
| Studs | Brand → Colour | Pairs confirmed. |
| Waistcoat | Brand → Colour → Size | Piece proposed; not yet confirmed. |
| Coat | Brand → Colour → Size | Piece proposed; not yet confirmed. |

Treat Chappal / Peshawari Chappal as the user's current Product label; separate Product entries are not yet requested. Exact Product names can be edited later.

Developer design recommendation consistent with the confirmed simplicity priority: show article for Fabric, size for the specified sized products, and only the applicable fields elsewhere. Do not add a non-fabric model/design selector. Keep Product setup concise, including only the stock unit and applicable fields. Size choices should be appropriate to the Product; footwear sizes must not be automatically imposed on coats.

Totals should be derived from the relevant underlying variants. Aggregation is only meaningful for compatible units: report metres, pairs and pieces separately rather than adding them into a misleading total quantity. Sales value can be aggregated in the agreed currency.

Illustrative example only — these are not actual stock quantities:

| Stock view | Before sale | Change | After sale |
| --- | --- | --- | --- |
| Yathreb / Dastan / Blue | 100 m | -4 m | 96 m |
| All Dastan colours combined | 500 m | -4 m | 496 m |

This total-level model alone does not resolve individual roll availability. If two rolls contain 2 m each, that does not necessarily satisfy one continuous 4 m cut. Roll/batch tracking is an open business requirement.

## 4. Confirmed future tailoring requirements

| ID | Requirement |
| --- | --- |
| TAIL-01 | Maintain identifiable customer profiles; the user prefers mobile numbers for customer identification and lookup. |
| TAIL-02 | Searching the customer's mobile number retrieves their stored measurements and related customer/payment records. |
| TAIL-03 | Store measurements appropriate to garment type, including shalwar kameez, waistcoat, three-piece suit and coat. Exact measurement fields remain undefined. |
| TAIL-04 | Customer profiles and measurements are editable. |
| TAIL-05 | Reuse previous measurements on future stitching work without requiring a new measurement session every time. |
| TAIL-06 | Record amounts paid and remaining. Whether balances are shown per order, customer, or both must be specified. |
| TAIL-07 | Print customer details associated with their record. Exact customer slip/order receipt format remains undefined. |
| TAIL-08 | Accept customer-supplied cloth purchased outside the shop. No fabric sale is required to provide stitching services. |
| TAIL-09 | Tailoring can function without inventory/POS being enabled. |

Developer recommendations for later approval:

- Use a permanent internal customer ID, with mobile number as the primary search field. Phone numbers can change or be shared within a family; phone number uniqueness policy needs a decision.
- Separate the customer's reusable measurement profile from the measurements copied onto each stitching order. Editing a profile should not silently rewrite historical order specifications.
- Preserve individual orders and payment entries instead of keeping only an editable customer-level balance.
- If a future order uses shop-supplied fabric, allow an explicit link to the fabric sale. If it uses outside fabric, do not deduct retail inventory.
- Independence does not inherently require microservices; deployment boundaries should follow the approved operational needs.

## 5. Phase 1 recommendations awaiting approval

These are proposed safeguards and workflow details, not additions already approved by the user.

| ID | Recommendation | Reason |
| --- | --- | --- |
| REC-01 | Support fractional metre quantities using fixed precision; decide the smallest permitted cut. | Fabric sales may not be whole metres. |
| REC-02 | Retain stock movements for opening stock, incoming stock, sales, returns and authorized adjustments. | Explain how a current stock balance was reached. |
| REC-03 | Commit the sale and its stock movement together, and make retried submissions safe against duplication. | Avoid partial or duplicate transactions. |
| REC-04 | Do not alter stock or create another sale when a receipt is printed or reprinted. A failed print must leave a successfully saved sale available for reprinting. | Printing is separate from completing a sale. |
| REC-05 | Prevent selling unavailable stock, including concurrent sales from multiple tills. | Avoid overselling. Any override policy would need explicit approval. |
| REC-06 | Define returns, exchanges, cancellations and damaged-stock handling before launch. | These affect stock and net sales differently; returned cut cloth is not automatically resellable. |
| REC-07 | Save sale-time description, quantity and price on each bill. Archive catalogue items used in history instead of deleting their history. | Later catalogue/price changes should not rewrite old bills. |
| REC-08 | Use unique bill numbers, searchable bill history and controlled corrections. | Support reliable lookup and audit. |
| REC-09 | Establish staff permissions and an audit record of sensitive changes. | Protect stock, prices and recorded sales. |
| REC-10 | Provide automated backups outside the only operating computer, plus a tested restore process. | Local operation, cloud hosting and synchronization are not substitutes for recoverable backups. |
| REC-11 | Define sales value, quantities sold by unit, refunds, discounts and money collected separately where applicable. | Metres, pairs and pieces are distinct quantities; sales, cash collection and profit are not interchangeable metrics. |
| REC-12 | Use stable internal identities for products, brands and variants; renaming a colour or size preserves its inventory and history. Define a controlled process for merging or reclassifying used entries. | Catalogue edits must not lose stock, duplicate variants or silently rewrite old bills. |
| REC-13 | Define stock units and quantity precision per Product; suggest pairs for chappal and pieces for shawls, wallets, coats and waistcoats. Studs are already confirmed as pairs. | A mixed inventory cannot apply metre-based quantities to every item. |
| REC-14 | Support bills with multiple products, retaining the Product-appropriate description, colour, size, quantity and unit on each line. | A combined purchase should update each chosen variant independently. |

Low-stock alerts, barcode workflows, profit reporting, supplier accounts, purchases/payables, expenses, stock transfers and export/import formats are potential discussion topics only. They are not confirmed scope. Pricing by metre, by fixed suit cut, or both remains to be agreed.

## 6. Operating setup and architecture direction

Confirmed user input in revision 0.2:

- One shop for now.
- One computer is enough initially; one or two computers may be used. A second computer is not a launch requirement.
- Internet is consistently available at the shop.
- The user prefers using their own computer's storage and local hosting.

Target shop computer confirmed by the user in revision 0.4:

| Component | Confirmed detail |
| --- | --- |
| Computer | HP desktop |
| Processor | Intel Core i5, 4th generation |
| Memory | 8 GB RAM |
| Storage | 256 GB SSD; currently available free space is unknown |
| Display | Samsung 27-inch monitor; resolution is not specified |
| Operating system | Windows 10; edition, build and 32/64-bit system type are not yet specified |
| Network | Wi-Fi adapter; existing shop internet is consistently available |

Developer implications: keep the POS lightweight, favour a simple local service and browser interface, and avoid requiring heavy background services or container tooling without a concrete need. Choose compatible dependency/runtime versions before providing installation commands. Monitor size does not establish screen resolution, and SSD capacity does not establish free space. Do not promise measured performance without user-run testing.

This settles the current hosting preference in favour of local hosting. Internet availability does not obligate cloud hosting. The earlier open shop-count and computer-count questions are answered and should not be asked again without a change in circumstances.

Developer recommendation: a locally hosted browser-based management application with one database and application service on a designated main shop computer. The frontend, backend and operational data live locally. Initially the main computer can be both the server and the billing terminal. An optional second computer connects to that same service over the shop network, using the same stock and sales data. It must not maintain an independent, unsynchronized copy of the inventory.

Install the application server, database and all assets needed for core POS functions at the shop. With that design, internet loss would not stop locally supported checkout; however, the user has not explicitly stated a formal offline acceptance requirement. The host must remain powered and available. Other devices depend on the local network. Internet-based payment authorization, remote viewing and off-site synchronization do not become offline features automatically.

Proposed operational details for later approval: automatic service startup, a stable local network address for a second terminal, authenticated staff access, and backups to a separate device or approved remote destination with a tested restore procedure. No router, firewall or operating-system configuration has been changed.

Cloud hosting is not the current preferred deployment. Revisit only if future remote or multi-location needs justify a proposal the user accepts. Offline sales from a future cloud application would require explicit durable local storage, synchronization, duplicate prevention and stock-conflict policies; a PWA badge or cached screen does not implement these business guarantees.

A desktop wrapper is an optional later choice if the shop requires direct/silent printing or deeper hardware integration. It can reuse web UI code, but packaging as a desktop app does not by itself make cloud-dependent data available offline. No desktop framework has been selected.

Standard browser printing opens the system print dialog. Printer-specific formatting, margins, paper dimensions, cutters and any silent-print path must be verified against the actual printer and operating environment. Do not promise compatibility with an unspecified device.

The public website remains separately deployed and public-facing. Any later connection to shop inventory must be deliberately scoped and secured. Local-only data will not automatically be available remotely or to the public website.

Local hosting is the user's preference. Source milestone 0.5 selects the lightweight local browser architecture described below. Codex has not installed it, created an operating database, started it, configured the network, or deployed it.

### Source milestone implementation decisions, revisions 0.5–0.7

These are developer implementation decisions used to make the confirmed inventory foundation concrete. They do not confirm unresolved business policy:

| Area | Implementation decision | Boundary retained |
| --- | --- | --- |
| Stack | Python 3.13, Flask 3.1.3, Waitress 3.0.2, standard-library SQLite, and server-rendered HTML/CSS. There is no Node.js build, container or separate database server. | The Windows 10 build and 32/64-bit type must still be checked before selecting the matching Python installer. Runtime and performance remain user-run checks. |
| Hosting | One Waitress/Flask service and one SQLite database on a local disk of the main computer. SQLite uses WAL mode, foreign keys, a busy timeout and serialized write transactions. An optional second terminal uses the main service through its private LAN address. | No second database, shared-drive database, public exposure, remote access, firewall change, stable IP or automatic startup is configured. |
| Catalogue identity and ownership | Stable integer IDs represent products, brands, articles, colours, sizes and exact variants. Labels can be renamed without changing relationships. Brands belong to products; Fabric articles belong to brands and their colours belong to articles; other colours belong to brands; sizes belong to colours. Parent identities cannot be moved after creation. An exact variant is created only by explicit stock entry with a valid complete chain. | Merging, deleting, archiving, reparenting and reclassification are not exposed. Non-fabric design/model was not added. |
| Parent-scoped names | Normalized names are unique under their immediate parent: brands per Product, articles per brand, colours per Fabric article or non-fabric brand, and sizes per colour. The same name is allowed under a different parent. | This resolves identity and ownership only; it does not define merging or cleanup policy. |
| Units | Fabric is seeded with confirmed metres and Studs with confirmed pairs. The recorded pair/piece proposals for the other five products are stored separately with no active unit; the interface requires the owner to choose pairs or pieces before entering stock. A newly added non-fabric Product also requires an explicit pair/piece unit. | No proposed unit has been converted into a confirmed user requirement. A confirmed unit is deliberately locked once selected to protect history. |
| Quantity representation | All quantities are integer thousandths. Metres can be represented to three decimal places; pairs and pieces accept whole quantities only. | Three-decimal storage capacity does not approve a minimum fabric cut increment, fixed suit pieces, yards, roll tracking, wastage or leftovers. |
| Initial stock ledger | The interface writes permanent positive `opening` or `incoming` stock movements. Opening stock is accepted only as the first movement for an exact variant; further positive additions use incoming stock. Current quantity is derived from the movement ledger, not stored as an editable balance. | These minimal entry labels do not define suppliers, purchases/payables, corrections, returns, damage, or an approved operational stock-receipt process. Their business fit remains to be verified before launch. |
| Traceability | Every movement stores its exact variant, scaled quantity, unit, UTC timestamp, optional note, user and sale-time-style description snapshot. Catalogue renames therefore change the current display without rewriting prior movement descriptions. | Sales and bill snapshots will be separate later records linked transactionally to their stock movements; their fields and policies remain open. |
| Retry/concurrency safety | Stock writes use `BEGIN IMMEDIATE`. Each submitted form has a unique request key and content digest; an identical retry reuses the saved result, while the same key with changed content is rejected. Variant creation and movement insertion commit together. | Overselling cannot yet occur because sales are not present. The later sale transaction must use the same database authority and add an atomic availability check. |
| Private access | A single owner account, password hashing, CSRF validation, host validation, security headers, request-size limits and a short global failed-login throttle protect the current interface. | This is a technical safeguard, not approval of staff roles, permissions, audit policy or remote access. LAN HTTP should be used only on the trusted shop network. |
| Recovery | Initialization refuses any existing database; startup never creates or migrates data. User-run commands provide integrity checking, non-overwriting online backup and restore into a new directory with session invalidation. | Backup destination, automation, schedule, retention and recovery objectives remain open. |
| Interface | Server-rendered pages open a Product first, then expose only the selected parent's brands, articles, colours and sizes as applicable. Current Stock adds a small self-hosted vanilla JavaScript file that requests authenticated, canonical parent-scoped choices, clears invalid descendants immediately and leaves one final Apply filters action for results. The same GET form progressively loads each level when JavaScript is unavailable. Catalogue forms use stable fragment targets and preserve their parent IDs so open, add, rename and validation responses remain at the relevant management section. No external frontend asset, package or compilation step is required. | Backend ownership validation remains authoritative. Browser behavior, focus/scroll behavior, screen-resolution testing and operational usability require user verification on the shop hardware. |

The source tree and exact Windows commands are documented in `README.md`. No real catalogue examples or stock quantities are seeded; only the seven recorded Product definitions are created during user-run initialization.

## 7. Open decisions

Next catalogue decisions:

1. Confirm the proposed pair/piece units for chappal, shawls, wallets, coats and waistcoats when defining quantities. Fabric in metres and studs in pairs are already confirmed. The milestone interface presents the proposal and requires an explicit choice; no unit has been silently confirmed in source.
2. What size labels/systems are used for chappal, coats and waistcoats? Which colour-size combinations actually exist?

Resolved: non-fabric design distinctions use separate brand names, and studs use pairs. Do not ask these questions again unless the user changes the requirements.

Remaining operating decisions:

- What printer model, connection and paper size will be used? Is a print dialog acceptable?
- Is access from outside the shop required, and is it view-only or does it include editing/selling?
- Confirm the Windows system type/build before selecting installers; the target computer, RAM, SSD, display size, Windows 10 and Wi-Fi adapter are already specified above. Backup and power arrangements remain open.
- Formal offline acceptance criteria can be finalized with the local deployment workflow. Internet is currently consistently available, and local hosting is preferred.

Then clarify inventory and sales behaviour incrementally:

- For fabric, metres only or also fixed-length suit pieces/yards? Non-fabric products are already confirmed above.
- Minimum cut increment; treatment of leftovers, wastage, rolls and dye batches?
- Does the minimal opening-stock/positive-incoming-stock interface match the shop's actual initial count and ongoing receipt workflow? Supplier, purchase, correction and adjustment behaviour remains undefined.
- Prices by article, colour, size or individual variant; buying cost, selling rate, discounts and approval limits?
- Cash only or other payment methods; deposits, credit, split payments and outstanding balances?
- Customer details on retail bills: required or optional?
- Return/exchange and cancellation policy, particularly for cut fabric?
- Required sales summaries, reporting timezone and business-day boundary?
- Roles, edit/delete rights, backup destination and acceptable data-loss/recovery targets?
- Currency, applicable invoicing/tax obligations, interface language and bill language? No tax or legal treatment is assumed.

Do not infer these answers from example brand names or from unrelated project history.

## 8. Decision log and progress

| Revision | Status | Change |
| --- | --- | --- |
| 0.1 | Confirmed user instruction | Planning first; implementation begins only after requirements are finalized and the user authorizes it. |
| 0.1 | Confirmed user requirement | Public brand website plus two independently usable management applications. |
| 0.1 | Confirmed user priority | Inventory/POS is Phase 1; tailoring requirements retained for later. |
| 0.1 | Developer recommendation | Browser-based management app; local/cloud/desktop packaging remains open. |
| 0.2 | Confirmed user requirement | Expand inventory to Chappal / Peshawari Chappal, shawls, wallets, studs, waistcoats and coats, with the Product-specific structures recorded above. |
| 0.2 | Confirmed user requirement | Products, brands, colours and sizes can be added and edited. |
| 0.2 | Confirmed operating setup | One shop; one computer sufficient initially, optional second computer; consistently available internet. |
| 0.2 | Confirmed user preference | Use the user's own computer storage and local hosting. This supersedes the earlier undecided hosting preference. |
| 0.2 | Developer recommendation | Local web POS with one shared database/service and optional second network terminal; stack and installer remain open. |
| 0.3 | Confirmed user decision | Infrequent design distinctions use separate brand entries such as Hayat Alpha and Hayat Beta; no additional non-fabric design/model level in Phase 1. Fabric articles remain. |
| 0.3 | Confirmed user requirement | Studs are counted and sold in pairs. |
| 0.3 | Confirmed user priority | Ease of use and simple workflows take priority. |
| 0.4 | Confirmed user workflow | Proceed towards Codex source-code development. The user performs dependency installation, setup, builds/tests and local execution; the assistant provides instructions and guidance. |
| 0.4 | Confirmed hardware constraint | HP desktop, Intel Core i5 4th generation, 8 GB RAM, 256 GB SSD, Samsung 27-inch monitor, Windows 10 and Wi-Fi adapter. |
| 0.4 | Deliverable | Prepare a Codex handoff with project instructions, the continuous requirements record and a first-task prompt. No application code or runtime setup has been produced in this turn. |
| 0.5 | Confirmed user instruction | Begin and finish the first source-code milestone for project structure, persistent inventory data, catalogue management and stock entry, while leaving unresolved POS business rules open. The user continues to perform all installation and execution. |
| 0.5 | Developer implementation decision | Select Python 3.13 + Flask + Waitress + SQLite with server-rendered HTML/CSS as the minimal local stack. Use one local service/database, with an optional LAN browser terminal using that same service. |
| 0.5 | Developer implementation decision | Represent exact Product-specific variants with stable identities and an append-only fixed-precision movement ledger. Preserve entry-time description snapshots and derive current balances from movements. |
| 0.5 | Developer safeguard | Keep proposed units inactive until explicit owner confirmation; use atomic/idempotent stock writes; refuse database overwrite or implicit creation/migration; provide owner access and non-overwriting backup/restore commands. These safeguards do not approve open business policy. |
| 0.5 | Source milestone deliverable | Added the application factory, schema, database and inventory services, catalogue/stock/history pages, local styling, management commands, user-run data/recovery tests, README and updated start guide. No dependencies, schema, tests or service were executed by Codex. |
| 0.6 | Corrected confirmed requirement | Use Product throughout the domain. Enforce Product → Brand → Article → Colour for Fabric, Product → Brand → Colour for Shawl/Wallet/Studs, and Product → Brand → Colour → Size for Chappal/Waistcoat/Coat. Every child has one immediate parent. |
| 0.6 | Corrected confirmed requirement | Names are unique only under their immediate parent, and stock combinations must use one valid complete chain. Global article, colour and size lists and cross-parent combinations are invalid. |
| 0.6 | Developer implementation decision | Correct the initial schema in place because no operational database exists. Store a schema identity marker so an earlier disposable trial database is rejected clearly; preserve it by renaming its directory before user-run reinitialization. |
| 0.6 | Source correction deliverable | Renamed source and schema terminology, rewired foreign keys and database triggers, added parent-scoped service validation and catalogue navigation, and updated tests and documentation. No database, migration, test, server or application was executed by Codex. |
| 0.7 | Confirmed usability requirement | Current Stock dependent choices update immediately from their selected parent, invalid descendants clear immediately, Apply filters refreshes results once after selection, and a no-JavaScript fallback remains usable. Catalogue open, add and rename actions retain both the selected chain and relevant page position. |
| 0.7 | Developer implementation decision | Use a self-hosted vanilla JavaScript enhancement and an authenticated JSON endpoint backed by the existing canonical hierarchy selector. Use ordinary GET forms and URL fragments as the server-rendered fallback and catalogue position mechanism. No frontend build system or schema change is introduced. |
| 0.7 | Source usability deliverable | Added cascading Current Stock controls, canonical child-choice responses, catalogue management anchors, focused route/template tests and updated operating documentation. No dependency, database, migration, automated test, server, browser or trial-data operation was executed by Codex. |

Completed in source: project structure; explicit schema initialization; stable parent-scoped Product catalogue; confirmed Product metadata; unit-confirmation boundary; positive opening/incoming stock ledger; exact-chain balances; rename-safe history; duplicate-submit and concurrent-write safeguards; owner login; catalogue, stock-entry, stock-overview and history pages; cascading Current Stock choices; position-preserving catalogue management; integrity, password-reset, backup and restore commands; user-run tests and operating documentation. The working record is revision 0.7.

Source review completed by Codex: the existing canonical hierarchy selector was traced through the authenticated child-choice endpoint; each Current Stock dependency path and downstream-clear branch was reviewed in the template and vanilla JavaScript; catalogue GET/POST parent fields, redirect fragments, form-action fragments and scroll targets were matched; and focused route-test source and Windows instructions were reviewed. No Python or JavaScript code, dependency installation, database initialization/schema execution, automated test, application server, browser workflow, backup/restore operation, LAN connection, build, print or deployment was run by Codex. Syntax, template rendering, endpoint behavior, JavaScript execution, no-JavaScript browser behavior, scroll position, runtime, visual, concurrency, hardware and recovery behavior remain unverified until the user runs the documented checks.

Next: the user should follow `README.md` to run the tests and inspect the cascading filters, refresh persistence, no-JavaScript fallback and catalogue position behavior. A trial database that already passes the corrected Product-hierarchy check should be reused; revision 0.7 needs no migration or recreation. User-reported output should be reviewed before operational data is entered or a later milestone begins. Sales, payment, receipt and report decisions remain outside this usability change.

For future updates, edit this same record, increment its revision, and record newly approved decisions. Do not mark unanswered questions or suggestions as confirmed.

## 9. Technical references used for the initial assessment

- [MDN: Window.print()](https://developer.mozilla.org/en-US/docs/Web/API/Window/print) — standard browser printing opens a print dialog.
- [MDN: Offline and background operation](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Offline_and_background_operation) — service-worker caching and background work require deliberate implementation; these mechanisms alone do not define a POS transaction or inventory-conflict policy.
- [Electron: webContents.print()](https://www.electronjs.org/docs/latest/api/web-contents#contentsprintoptions-callback) — example desktop-wrapper printing capability, including a silent option; not a selected stack or a printer compatibility guarantee.
- [Python 3.13: Using Python on Windows](https://docs.python.org/3.13/using/windows.html) — Windows support and installer options used to assess the selected runtime; the matching 32/64-bit installer still depends on the user's system type.
- [Flask installation](https://flask.palletsprojects.com/en/stable/installation/) — Flask 3.1 supports Python 3.9 and newer.
- [Waitress documentation](https://docs.pylonsproject.org/projects/waitress/en/latest/) — the selected lightweight WSGI server supports CPython on Windows under Python 3.9 and newer.
