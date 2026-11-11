# Desktop foundation

Status: accepted, 2026-11-13.

Use a Python desktop process with PySide6 Essentials, Windows Graphics Capture, and explicit Win32
window identity and geometry helpers. Select by HWND and owning process ID, never a substring of
a title. Capture runs outside the UI thread, delivering a single replaceable frame snapshot.

Use physical desktop pixels at the capture/Windows boundary. Crop WGC frames to the client area
using observed capture bounds. Reject geometry that cannot be reconciled rather than scale a
misaligned image. Place the native overlay window in physical pixels and convert local drawing
coordinates using its actual device pixel ratio.

The overlay is input-transparent, nonactivating, and excluded from supported capture APIs. It is
shown only while the selected target is foreground. Windowed and borderless fullscreen are the
initial supported presentation modes. Capture selection does not authorize process injection.

Use a memory cache plus SQLite for future translations. Redis and native game hooks are deferred.
Model inference, OCR, automatic font estimation, and translation caching are not milestone one.

Keep the first dependency set small. PySide6 Essentials avoids unrelated Qt addon modules. Pin
resolved dependencies in uv.lock. Provide setup and launch scripts without global package changes.
