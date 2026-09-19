# Start the inventory foundation

The first source milestone now contains a persistent catalogue and positive stock-entry foundation. It is not the completed POS: sales, prices, payments, receipts, and sales reports have not been implemented.

## Continue here

1. Read `README.md` for the stack, data guarantees, exact Windows setup commands, trial workflow, optional second-terminal setup, and backup/restore procedure.
2. Keep `AGENTS.md` at the project root; it governs later source milestones.
3. Keep `Clothing-Stitching-Project-Record.md` as the continuous confirmed-requirements and decision record.
4. Run and verify the foundation with disposable trial data before initializing operational shop data.

## How we continue

- Run the commands in `README.md` yourself after reviewing them.
- Share the exact terminal error/output when something fails, along with what command you ran. Avoid sending credentials or personal customer records.
- Ask Codex to fix the existing files and continue from the current record.
- Use the same project folder and preserve its database/backups when updating source.

The remaining pricing, payment, return, printer and other business-policy questions are already recorded. They do not need to be repeatedly re-entered or silently filled with invented requirements.

## Current handoff status

- Requirements record: revision 0.7.
- Confirmed development boundary: Codex writes source; the user installs and runs.
- Application source: parent-scoped Product catalogue, cascading Current Stock filters, position-preserving catalogue management, stock entry, stock overview, stock history, owner access, and recovery commands are present.
- Database continuity: revision 0.7 has no schema change; reuse a corrected Product-hierarchy trial database that passes `manage.py check`.
- Sales/POS completion: not reached; later business workflows remain open.
- Dependencies installed, database initialized, application started, or runtime checks performed by Codex: none.
