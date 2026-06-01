---
applyTo: "ui/*.html,ui/*.js,ui/*.css"
description: "Use when modifying internal file:// pages (Agenda/NewTab/Video/Image/Passwords), shared settings sync, or cross-page UI behavior."
---

# Internal UI Pages Rules

## Scope
- Applies to internal app pages under [ui/](ui/).
- Priority flows:
  - Agenda hub: [ui/agenda.html](ui/agenda.html), [ui/agenda.js](ui/agenda.js)
  - New tab launcher: [ui/newtab.html](ui/newtab.html)
  - Password manager page: [ui/passwords.html](ui/passwords.html), [ui/passwords.js](ui/passwords.js)

## Rules
- Preserve existing visual language and behavior unless change request says otherwise.
- Keep shared settings keys consistent across pages and bridge reads/writes.
- Avoid duplicating state logic; prefer existing helper/state functions in each module.
- For cross-page features, verify both source and destination page behavior.

## Integration Notes
- Internal pages run via `file://` and rely on QWebChannel objects.
- Do not assume browser APIs that require server context unless already used in the project.

## Validation
- Open each affected page from the app and verify:
  - No broken tab/view activation.
  - No missing bridge object errors.
  - State persists and reloads as expected.
