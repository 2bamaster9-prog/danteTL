# Slice 15 — Configurable global hotkeys

Requested: show/hide the overlay and start/stop capture without leaving the game.

Implemented defaults are **Ctrl+Alt+F8** (overlay) and **Ctrl+Alt+F9** (capture). Settings → Hotkeys
offers modifier/key selectors, explicit Apply, Disabled, information buttons and active/conflict
feedback. Dropdowns avoid the conflict between recording a chord and an existing global binding
consuming it. Support Ctrl/Alt with optional Shift, letters, digits and F1–F11; exclude Windows keys,
F12, unmodified keys and layout-dependent punctuation. Defaults use function keys to avoid AltGr
letter combinations. No new dependency, daemon, polling thread or game integration is required.

Overlay visibility changes the existing switch without resetting capture, tracks or translations.
Capture reuses the existing Start/Stop lifecycle and validates selected HWND/PID before starting.
No target is selected from foreground activity. Modal prompts, shutdown and stopping cannot start
competing work. Main control tooltips show active keys; unavailable startup bindings have an
actionable warning outside Advanced. Shortcuts do not bring the app to the foreground.

Successful changes persist with existing preferences. Drafts and failed replacements never replace
committed values. A failed startup registration remains configured for retry. Disabled is an empty
string, distinct from absent older preference fields (which receive defaults). Another instance or
app can reserve a shortcut; users can retry Apply after closing it or choose another combination.

Acceptance: background/minimized operation, autorepeat suppression, atomic conflict recovery,
cross-action duplicates, disable/rebind and stale queued messages, old-preference migration,
persistence, selected-source identity, capture stop/start, modal/close guards, runtime release and
restart-failure reacquisition. Native evidence uses only an owned foreground demo in another process.
Results and platform limitations are in [verification](../verification.md).
