# 015 — Native global shortcuts reuse existing actions

Use Windows RegisterHotKey with MOD_NOREPEAT and a Qt native event filter. This handles keys while
the app is minimized or a game is foreground without hooks, injection, input polling or new packages.
Accept both Qt Windows message routes: thread messages may be routed through Qt's internal message
window. Validate registration ID and modifier/key payload before dispatching on the GUI thread.

The service owns at most two active registrations. Rebinding acquires the new shortcut before
releasing the previous one; duplicate or OS conflicts preserve the working binding. IDs are never
reused within the service lifetime, so queued messages from removed bindings cannot trigger another
action. Registration IDs stay inside the documented application range; exhaustion requests restart.
Release both before launching a replacement runtime; reacquire configured values on failed restart.
Application quit also releases them defensively. Old-process release is essential to avoid the
replacement app seeing its own predecessor as a competing shortcut owner.

Keep service, Windows/Qt boundary, and settings editor separate. Preferences store validated strings;
the editor stores drafts separately from committed values. Explicit Apply is appropriate because
registration can fail. Modifier/key dropdowns allow editing even when global keys would consume a
recorded chord. Fields are keyboard accessible and explanations available on hover/focus/click.

Global actions call existing UI controls. Visibility does not invalidate processing; capture honors
disabled/stopping/closing states and verifies the selected HWND/PID. Modal dialogs suppress actions.
No window activation, new capture source or extra model preparation is implicit in a shortcut.

Primary references:

- [RegisterHotKey and reserved keys](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey)
- [Qt native Windows event routes](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QAbstractNativeEventFilter.html)
