# Clothing and Stitching Shop — Codex Instructions

## Start every task

1. Read this file and `CURRENT-PROJECT-STATE.md`.
2. Treat the user's latest correction as authoritative.
3. Inspect only the files directly relevant to the requested change and their related tests.
4. Read `Clothing-Stitching-Project-Record.md` only when the task depends on an older decision or the current-state file is unclear. It is the historical archive, not the routine task briefing.

## Working rules

- Keep every change limited to the requested issue. Preserve the existing structure and unrelated behavior.
- Do not perform broad repository searches, web searches, or delegation unless they are required to complete the specific request.
- Write or update focused tests when behavior changes. Preserve established behavior through those tests, and let the user run the full regression suite.
- The user performs dependency installation, database initialization or migration, tests, builds, server startup, browser execution, printing, deployment, and computer or network configuration. Provide exact Windows PowerShell commands when requested; do not claim they passed without user output.
- Do not overwrite databases, modify trial or operational data, fabricate lockfiles, publish code, or introduce credentials.
- Keep the application lightweight and retain one authoritative service and database on the main shop computer. An optional second terminal connects to that service.
- Keep unresolved sales, payment, receipt, return, tax, and reporting rules unresolved until the user confirms them. Do not describe the current inventory foundation as the completed POS.

## Records and handoff

- Update `CURRENT-PROJECT-STATE.md` only when current behavior, architecture, critical invariants, confirmed requirements, or unresolved decisions change.
- Update `Clothing-Stitching-Project-Record.md` only at major milestones or when historical decision tracking is specifically required.
- Give concise completion reports covering changed files, completed behavior, relevant limitations, unverified user-run checks, and requested commands.
