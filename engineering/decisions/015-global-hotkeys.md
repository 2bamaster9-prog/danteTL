# 015 — Native global shortcuts reuse existing actions

Use Windows RegisterHotKey with MOD_NOREPEAT and a Qt native event filter. This handles keys while
the app is minimized or a game is foreground without hooks, injection, idle polling or new packages.
Accept both Qt Windows message routes: thread messages may be routed through Qt's internal message
window. Validate registration ID and modifier/key payload before dispatching on the GUI thread.

The service owns at most three active registrations. Rebinding acquires the new shortcut before
releasing the previous one; duplicate or OS conflicts preserve the working binding. IDs are never
reused within the service lifetime, so queued messages from removed bindings cannot trigger another
action. Registration IDs stay inside the documented application range; exhaustion requests restart.
Release all before launching a replacement runtime; reacquire configured values on failed restart.
Application quit also releases them defensively. Old-process release is essential to avoid the
replacement app seeing its own predecessor as a competing shortcut owner.

Keep service, Windows/Qt boundary, and settings editor separate. Preferences store validated strings;
the editor stores drafts separately from committed values. Explicit Apply is appropriate because
registration can fail. Modifier/key dropdowns allow editing even when global keys would consume a
recorded chord. Fields are keyboard accessible and explanations available on hover/focus/click.

Global actions reuse existing UI controls. The user's follow-up authorizes foreground selection
when the capture hotkey starts a session; a saved option disables it. Resolve only that exact
eligible HWND/PID and reject focus/identity races. Share window eligibility with the picker, exclude
our windows and shell/desktop, and never fall back to an earlier source. Manual Start uses the picker;
an active session always stops regardless of focus. Modal/stop/close guards remain enforced.

Show-original keeps a separate transient mask in UI coordination. It suppresses presentation only,
without modifying stored switches, workers or accepted English. Release re-evaluates current valid
presentation immediately, respecting any changes made during the hold. Focus loss, stop, modal entry,
successful rebind/disable and shutdown cancel it. Failed rebind preserves the working held shortcut.
Because RegisterHotKey has no key-up notification, WindowsHotkeyEvents checks the held chord via
GetAsyncKeyState's high bit every 16 ms, only while held. A zero/unavailable key state ends the hold;
ignore the unreliable low bit. Reject press notifications already released by the time Qt handles
them. This small bounded release check avoids a permanent keyboard hook or idle keyboard scan.

Primary references:

- [RegisterHotKey and reserved keys](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey)
- [Qt native Windows event routes](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QAbstractNativeEventFilter.html)
- [Current physical key state](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate)
- [Foreground window](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getforegroundwindow)
