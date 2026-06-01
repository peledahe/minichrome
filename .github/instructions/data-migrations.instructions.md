---
applyTo: "main.py"
description: "Use when editing SQLite schema, app_config defaults, data dedupe logic, or startup migrations in _db()."
---

# Data Migration Rules

## Scope
- Applies to schema/default/migration code in [main.py](main.py), especially `_db()`.

## Rules
- Use additive, backward-compatible migrations.
- Prefer `CREATE TABLE IF NOT EXISTS` and column guards via `PRAGMA table_info` before `ALTER TABLE`.
- For defaults/config keys, use `INSERT OR IGNORE` to avoid overriding user data.
- Never edit binary DB/cache artifacts directly.
- If dedupe/cleanup is one-time, protect with an explicit app_config flag.

## Safety Checklist
- Existing installations must keep working after migration.
- New installs must receive all required defaults.
- Avoid destructive deletes unless feature explicitly requires them.

## Validation
- Run: `python -m py_compile main.py`.
- Start app once and confirm no startup DB errors.
- Smoke-check impacted features that read/write modified tables or config keys.
