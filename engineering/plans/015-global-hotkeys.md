# Slice 15 — Configurable global hotkeys

Requested: show/hide the overlay and start/stop capture without leaving the game.

Implemented defaults are **Ctrl+Alt+F8** (overlay), **Ctrl+Alt+F9** (capture), and
**Ctrl+Alt+F10** (hold to show original). Settings → Hotkeys
offers modifier/key selectors, explicit Apply, Disabled, information buttons and active/conflict
feedback. Dropdowns avoid the conflict between recording a chord and an existing global binding
consuming it. Support Ctrl/Alt with optional Shift, letters, digits and F1–F11; exclude Windows keys,
F12, unmodified keys and layout-dependent punctuation. Defaults use function keys to avoid AltGr
letter combinations. No new dependency, daemon, polling thread or game integration is required.

Overlay visibility changes the existing switch without resetting capture, tracks or translations.
Capture reuses the existing Start/Stop lifecycle and validates HWND/PID before starting. The user's
follow-up adds **Capture the focused window**, enabled by default for the capture shortcut only.
It resolves the eligible foreground window on that explicit action, updates the picker, and starts
it even if the old window list was empty. Reject our own windows, shell/desktop, tools, cloaked,
minimized, closed and otherwise unusable targets. Focus/identity races never fall back to another
source. The manual Start button uses the selection. The hotkey always stops an existing session.
Modal prompts, shutdown and stopping cannot start
competing work. Main control tooltips show active keys; unavailable startup bindings have an
actionable warning outside Advanced. Shortcuts do not bring the app to the foreground.

Show-original is a transient presentation mask, not a setting toggle. Hide the overlay immediately
on hold, keep updating all processing state, and render current valid English on release. Never
snapshot old translations or force saved switches back on. Cancel on focus loss, stop, rebinding,
disable, modal entry or close. RegisterHotKey reports presses only; a precise 16 ms timer checks only
the held chord's key states and stops after release. No keyboard hook or idle polling is added.
Discard delayed key-down notifications whose chord is already up. Release of any chord key ends it.

Successful changes persist with existing preferences. Drafts and failed replacements never replace
committed values. A failed startup registration remains configured for retry. Disabled is an empty
string, distinct from absent older preference fields (which receive defaults). Another instance or
app can reserve a shortcut; users can retry Apply after closing it or choose another combination.

Acceptance: background/minimized operation, autorepeat suppression, atomic conflict recovery,
cross-action duplicates, disable/rebind and stale queued messages, old-preference migration,
persistence, selected-source identity, capture stop/start, modal/close guards, runtime release and
restart-failure reacquisition. Native evidence uses only an owned foreground demo in another process.
Results and platform limitations are in [verification](../verification.md).
