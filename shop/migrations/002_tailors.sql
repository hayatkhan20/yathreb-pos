-- Explicit schema 4 to 5 upgrade: Tailor records and current garment assignment.
CREATE TABLE tailors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 80),
    name_key TEXT NOT NULL UNIQUE,
    mobile TEXT NOT NULL DEFAULT '' CHECK (length(mobile) <= 40),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE tailoring_item_assignments (
    tailoring_item_id INTEGER PRIMARY KEY REFERENCES tailoring_items(id) ON DELETE RESTRICT,
    tailor_id INTEGER NOT NULL REFERENCES tailors(id) ON DELETE RESTRICT,
    assigned_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assigned_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX tailoring_item_assignments_tailor
    ON tailoring_item_assignments (tailor_id, tailoring_item_id);

UPDATE settings
SET value = 'tailor-assignments-v5'
WHERE key = 'schema_identity';
PRAGMA user_version = 5;
