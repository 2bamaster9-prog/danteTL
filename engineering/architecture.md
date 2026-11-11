# Architecture

## Current implementation

`app` assembles the Windows boundary, QApplication, main window, and lazy recognizer factory.
`ui` owns controls and coordination for one capture/OCR session. `inspection` owns the image/text
inspector. `capture` owns asynchronous native capture and shutdown.
`overlay` owns rendering and display placement. `windows` owns Win32 identity, geometry, and
overlay styles. `domain` contains immutable shared values and pure geometry/visibility policy.
`demo` is an optional animated test target.

The domain imports no Qt or Windows code. Capture does not depend on Qt and consumes a small
geometry-source protocol. `recognition` owns the OCR worker, immutable observations, and lifecycle;
it imports no Qt, Win32, or model runtime. `meiki` isolates pinned MeikiOCR/ONNX details. `models`
defines and validates pinned local assets. Later tracking belongs in its own module. The current
single-session coordinator can move out of the UI when the pipeline requires it.

## Coordinates

All rectangles crossing native/capture boundaries use physical pixels. Client and window bounds
are desktop coordinates, including negative monitor origins. Startup requests per-monitor V2 DPI
awareness before creating any windows. Capture checks actual image dimensions against DWM visible
bounds, window bounds, and client bounds. It crops only a matching, containing rectangle; resize
frames whose geometry does not agree are discarded.

The overlay HWND is positioned with SetWindowPos in physical client coordinates. Painting scales
by the inverse of the overlay's current devicePixelRatioF. This avoids incorrectly scaling desktop
origins when monitors have different DPI. A retained frame may follow a window move but cannot be
used to display an overlay after a client-size change until a compatible new frame arrives.

## Ownership and lifecycle

The GUI thread owns all Qt widgets. A Python capture-owner thread creates and stops the native
capture session. The native callback obtains current geometry, throttles copies, crops, and copies
borrowed native memory into owned immutable bytes before returning. It catches exceptions before
crossing the native boundary.

A lock protects one replaceable frame snapshot. The UI polls snapshots and redraws the preview
only when its sequence changes. There is no growing frame queue. Native startup, imports, and
shutdown never run on the GUI thread. Stop requests immediately hide the overlay and clear the
preview; the UI polls completion before allowing another session or finishing application close.

Each session is single-use and tied to HWND plus process ID. Terminal states reject late frame
publication. Failure diagnostics survive cleanup. A new session receives a new mailbox, preventing
old callbacks from modifying its state. Initial capture without a usable frame times out after ten
seconds. An unchanged WGC source need not deliver repeated frames, so frame age alone is not a
failure signal. Window validity, minimize state, focus, and current geometry are checked separately.

## Overlay behavior

Qt and Win32 both mark the overlay as input-transparent and nonactivating. The layered-window
style supports mouse pass-through across processes. WDA_EXCLUDEFROMCAPTURE is required; failure
stops the session with a visible explanation. The overlay is visible only for the selected foreground
window with matching capture dimensions. It hides on focus loss, minimize, stop, or source failure.

The application now draws numbered OCR line boxes, preserving the original game text underneath.
An unchanged captured frame can retain its boxes. For a changing source, boxes older than 750 ms
from capture are hidden, and dimension mismatches always hide them. This bounds diagnostic lag;
it is not text tracking. The original sample mode remains available to the native regression harness.

## OCR ownership and inspection

Each capture session gets one OCR worker and model instance. The worker imports the model runtime,
validates files, and loads all three ONNX sessions off the GUI thread. It processes one frame at a
time with at most one replaceable pending frame and one published result. No inference backlog
accumulates. The CPU provider uses two intra-op threads per session, one inter-op thread, disabled
idle spinning, OpenCV one thread, and recognition batches of four. Models execute sequentially.

Resize, minimize, and pause increment a generation and clear pending/published work. Already-running
native inference finishes, but cannot publish into an invalid generation. Each new capture has a
separate worker. Stop clears the inspector and overlay immediately; the GUI polls both workers'
completion before restarting or closing. A model failure preserves its diagnostic while capture
continues; stop/start retries loading. There is no forced interruption of an ONNX call.

An `OcrResult` retains its exact source frame, text regions, character boxes/scores, inference duration,
and completion time. OCR coordinates are client-relative physical pixels. Meiki performs internal
detector scaling; its outputs already refer to the original input dimensions. The inspector uses
one image transform for both pixels and boxes, including letterboxing and zoom. Recognition is not
filtered to Japanese, so other visible text may also appear. Detector-only boxes survive empty
recognition. Displayed confidence is the mean retained-character score; detection scores are not
exposed by the pinned upstream implementation.

Pause freezes the current image/table and invalidates queued work while capture continues. Resume
resubmits the latest frame. Resize/minimize/stop clear even a frozen inspection to prevent a stale
source from appearing active. No persistent text identities or translation are added in this milestone.

## Runtime data

Images stay in memory. No screenshots are automatically saved. Bounded diagnostic logs live under
`%LOCALAPPDATA%/JPOverlay/logs`, with no normal logging of captured pixels or recognized text.
Dependencies and the launcher environment are project-local when using the bundled setup script.
Models live in ignored `models/meiki` (or `JP_OVERLAY_MODEL_DIR`) and are installed only by explicit
`Setup OCR.cmd` / `tools/setup_models.py`. Repository revisions, lengths, and SHA-256 digests are pinned;
runtime rejects missing/corrupt files without a network fallback. Persistent caches are still future work.
