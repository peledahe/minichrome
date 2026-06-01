---
applyTo: "main.py,ui/*.js,ui/*.html"
description: "Use when changing QWebChannel bridges, @pyqtSlot signatures, py/pw API calls, or Python-JS integration bugs."
---

# Python Bridge Rules

## Scope
- Applies to bridge contracts between Python and frontend pages.
- Main bridge source: [main.py](main.py).
- Main consumers: [ui/agenda.js](ui/agenda.js), [ui/passwords.js](ui/passwords.js), [ui/videoplayer.js](ui/videoplayer.js), [ui/imageplayer.js](ui/imageplayer.js).

## Rules
- Keep bridge contracts backward-compatible when possible.
- If JS calls `py.*` or `pw.*`, ensure matching `@pyqtSlot` exists and parameter order/type remains aligned.
- Keep password CRUD and policy logic in `pw` bridge; do not move those methods into `py`.
- When adding a new bridge method, update both sides in one change set (Python + caller JS).

## Change Checklist
- Confirm exposed object name is correct (`py` vs `pw`).
- Confirm all affected pages bind QWebChannel before calling methods.
- Confirm success/failure paths notify the UI and refresh state if needed.

## Validation
- Run: `python -m py_compile main.py`.
- Manually open the affected internal page and verify bridge calls execute without console errors.
