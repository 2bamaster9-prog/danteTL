# Current architecture

This document owns cross-module contracts. Read the affected sections; code/tests own exact thresholds,
prompts and implementation details. See [building](building.md) and [verification](verification.md).

## Package layout

The distribution, Python package and CLI are `dantejp`; app-specific environment variables use
`DANTEJP_*`. `DanteJP` is the display name. There are no aliases for previous names or module paths.

| Package | Owns |
| --- | --- |
| `application` | Commands, snapshots, preferences and coordination of capture, models, setup and shutdown |
| `translation` | Workers, scheduling, routing, publication; `backends`, `cloud`, `models` and `dialogue` hold their specific integrations |
| `ocr` | Recognition, scan planning, text tracking and visual retention |
| `capture` | Native window identity, geometry and capture |
| `ui` | Qt views, controls, layout and desktop event delivery |
| `runtime` | Shared model assets, native library selection, downloads, contained processes and isolated runtime installation |

The root contains shared physical-coordinate values, resource paths, worker wakeups and application
entry/assembly modules. Package initializers do not import or re-export implementations. Consumers
import the module that owns each API. Import Linter checks whole application/processing packages for
Qt/view dependencies, all views for backend/service dependencies, and runtime services for UI coupling.
Shared asset validation belongs in `runtime.assets`; OCR owns only its pinned model definitions.

## Application ownership

| Owner | Responsibility |
| --- | --- |
| `composition` | Construct services, dependencies and desktop adapter |
| `ApplicationSession` | Serialize commands/completions; coordinate capture, setup, translation and shutdown |
| `CaptureLifecycle` | Freeze device/rate choices, validate capture targets/geometry, and gate capture teardown |
| `TranslationCoordinator` | Resolve selections, model identities, backend recipes and classifier configuration |
| `ModelLifecycle` | Commit assignments; own consent/preparation, route commitment, worker availability and adoption |
| `application.presentation` | Pure scene-reset/status projection; no worker operations |
| `CloudServices` | Backend/account/catalog services and credentials; no widgets |
| `SetupCoordinator` | Download/import, runtime and guide operations, cancellation and probe permits |
| `ModelInventory` | Cached model/runtime discovery and preparation receipts |
| `LiveSession` | Visual/OCR reconciliation and acknowledgement order, scene resets, tracking, grouping, English publication |
| `ShutdownCoordinator` | Cancel/drain owners, flush preferences, release hotkeys, then restart/close |
| `DesktopDriver`, Qt views | Native events, presentation and commands through typed view ports |

Views may retain drafts and last-rendered values, never backend factories, credentials or model policy.
Rendering must not start work or scan files. `ApplicationCommands`, `CloudCommands`, `SetupCommands`
expose commands and immutable snapshots. Import Linter enforces transitive view/service separation;
public ports have strict type checks. Prefer headless explicit-time replays for coordination policy.

`advance` adopts inventory/cloud/setup completions before integrating live owners. Nested Qt events
request a coalesced follow-up, not reentrant coordination. Worker hints wake the same path; a 33 ms
fallback services geometry/lifecycle. Image analysis and native/file work never run on that thread.
Capture polling returns an explicit phase; the application does not infer it from several worker
flags. Translation returns a typed activity (probe, preparation, standby, inactive, switching or
active), with a publication worker only when usable. The application joins probe readiness with
classifier cleanup, and sends current scene requests through `LiveSession` only. Capture teardown
waits for translation before draining OCR/visual owners. Status formatting cannot advance workers.
`TranslationCoordinator` owns a `ModelLifecycle` through composition. Lifecycle state is private;
commands change it and immutable snapshots expose it. Assignment/readiness revisions can be read
without polling workers. Prepared-worker handoff pairs the worker with the model it loaded; a later
selection cannot relabel that resource. `ModelLifecycle` gates route activation, consent, probing and
shutdown. The coordinator resolves per-model identities and recipes; the routed owner retains unchanged workers during committed
assignment changes. It drains replaced workers before starting replacements and coalesces rapid edits
to the latest plan. Unchanged lanes keep processing; retired replies cannot publish. Active plus retiring
owners remain bounded to two. One assignment-plan constructor owns runtime routing; older saved
preferences are decoded only at the input boundary. Identity includes local weights/runtime preparation
or cloud inference settings, limits, game hint and connection/account credential revision. Display names
are presentation only: renaming an active model or editing an unrelated model preserves workers and
published results. Consent/preparation and import probes retain their full-drain safety
boundary. The publication port exposes
update/invalidate/snapshot, without load/stop/routing operations. A separate import contract keeps
status projection independent of worker implementations. Capture Stop intent remains authoritative
while the native owner is still reporting its last running snapshot.
Inventory uses one bounded worker, explicit invalidation and a 30-second fallback scheduled from
completed scan adoption. Invalidation during a scan discards stale results and requests one follow-up.
Unchanged revisions do not rebuild routes/options. Cached badges never authorize native model loading.
Imported-registry discovery has its own failure boundary. A malformed/unreadable registry is preserved
and reported while healthy built-in choices and OCR assets remain available; a later refresh can recover.

Consent/review replies carry monotonic tokens. Decline/failure preserves committed assignments;
stale replies cannot adopt new proposals. Setup has three bounded lanes: models/imports, runtime,
and guide. Import probes wait for both translator and classifier cleanup. The skippable guide offers
downloadable bundles, not imported GGUF registrations; pending selection survives delayed discovery.
Hiding Settings never cancels an operation implicitly; app close cancels/drains all owners.
Shutdown waits for actual resource release and owner exit, not just a published result/failure.
Preferences and hardware work drain and hotkeys release before restart; failed restart resumes services.

## UI, identity and coordinates

The public app name is DanteJP.
Main/Settings/Advanced are views of one live session. Controls remain top-left and width-bounded;
inspection expands without changing maximized state. Simple/advanced routing preserves assignments.
Model selectors share styled nonselectable category headings. Unchanged lists preserve popup focus;
missing selections never choose replacements. Persist validated IDs/values, never HWNDs, pause or debug.
Badges distinguish files-present from engine-available. Device/rate edits apply next capture, including
when models arrive mid-session. Worker-based hardware advice separates detection from verified inference.
Capture status lives in Game & overlay. Its indeterminate loading bar and stage text project actual
capture/OCR/per-model readiness, including a partially loaded route and the first translation. They
remain visible with inspection collapsed and clear on readiness, stop or failure; no estimated
percentage or extra polling is introduced.

Native rectangles use physical pixels, including negative desktop origins; OCR is client-relative.
Enable per-monitor V2 DPI awareness before windows. Validate/crop only dimension-matched containing
frames. Position the overlay in physical coordinates; compensate its device pixel ratio when painting.
Moves may reuse a compatible frame; resize needs a new size-matched source. Capture fixes HWND plus PID
until explicit new selection. Never substitute windows/monitors after failure. Copy borrowed native
pixels before callbacks return; use bounded mailboxes and generations to reject late work.
Static WGC windows need not deliver repeated frames; frame age alone is not failure evidence.

The overlay is nonactivating/input-transparent; hide on focus loss, minimize, stop, source failure or
size mismatch. Border edits reopen only the same native source while retaining processing owners and
sequence. Screen-capture inclusion changes overlay affinity only; report failure and restore settings.
Raw game capture must exclude our overlay. Affinity is not a universal recording/security guarantee.

Shortcuts use RegisterHotKey on Qt; no hooks or idle polling. Only a held show-original chord polls
for release. This transient paint mask clears on focus loss/stop/close without resetting processing.
Rebinding is transactional and rejects stale messages. Only the explicit capture shortcut may choose
an eligible foreground HWND/PID; Start uses the selected target. Both honor modal/shutdown guards.

## OCR, visual evidence and retention

OCR owns imports, loading, inference and cleanup on its worker. Keep one active job, one replaceable
pending frame with coalesced coverage and one unacknowledged result. Native calls are not forcibly
interrupted; `finished` requires owner cleanup/exit. Failure leaves capture available. Raw `OcrResult`
retains its exact frame, text/character bounds, scores, coverage and timing. Never overlay old raw rows
on new pixels. `text_content` derives character-bounded tracking input without changing raw OCR;
only isolated weak edge glyphs beside strong Japanese runs may be filtered, never low confidence globally.

`LiveSession` waits for source-matched visual evidence, reconciles each completed OCR sequence once,
then acknowledges and publishes. The worker cannot overwrite unconsumed observations. Accepted OCR
lives outside inspection. Hidden inspection keeps the latest exact pair without conversion/table work;
pause freezes both displayed languages only. Resume shows the newest pair. Model changes revoke frozen
English; resize/minimize/stop also clear frozen source presentation.

`VisualSession` owns bounded thumbnails, tiles, templates/probes and one pending job, never frame history.
Reversible masking requires strong pattern loss on distinct captures. Retirement also needs completed
negative OCR, matching revision/geometry and visual evidence at least as new as that OCR. Unchanged
pixels override contradictory absence. Brightness/polarity/background motion are not semantic removal.
Visual failure visibly falls back to ordinary OCR. New translations wait for visual examination of their
OCR source; existing valid English is independent of readiness.

Partial OCR has explicit coverage; unscanned tracks are not misses. Pending areas union while pixels
are replaced. Retain per-line probe source sequences, whole-line closure and single coordinate offsets.
Artificial-edge detections trigger full fallback. Independent full-discovery deadlines cannot be delayed
by typewriter activity elsewhere. `ScanPlanner` evaluates partitions of at most four areas using provider
costs and bounded geometry/confidence hints. Unknown/weak/small/vertical cases retain the baseline.
Changed plans need savings and glyph/coverage safeguards. If expected lines are not preserved, discard
the result and scan original demand on the same frame, temporarily reverting to baseline. Full discovery
stays full. Publish only final raw output/actual coverage; reset hints with generation/provider/size.

Empty small crops may receive one background-padding retry without magnifying glyphs. Severed-glyph
recovery requires unambiguous adjacent detections and connecting ink; accept only strong complete
characters and preservation of unrelated lines. Otherwise keep the raw original. At most one extra
pass; subtract padding from both box types. CUDA recognition pads to batch four then slices actual
outputs; dummy detections never publish. Ordinary successful/full scans keep their preprocessing.

Tracking is deterministic and bounded (128 tracks, 512 candidate regions). Existing matches precede
new admission; truncated input cannot vote for absence. Spatially gated bipartite components use optimal
assignment with explicit unmatched costs, stable IDs and canonical tie ordering. Distant identical labels
cannot match on text alone. Cutoff edit distance handles minor variants; approximation never permanently
suppresses real edits. Confidence belongs to live content, not a screen-position cache.

Observed and committed text/geometry are separate. Worker delay, skipped frames and repeated polls are
not absence evidence. Bounded crop digests retain text through same-pixel misses; changed pixels alone
never remove text. Negative OCR needs coverage and elapsed evidence. Source-time settling works on static
WGC frames. New content/reset cannot inherit confidence. Accepted unchanged glyphs retain identity,
geometry and English; below 90% confidence only three strictly improving reviews are allowed without
real local change. Alternating spelling cannot reset this budget or duplicate unchanged detector fragments.
`EnglishPresentation` bridges only explicit same-pixel correction lineage while translating the successor.
Validate every member; edits/regrouping/removal/model changes revoke it. Consensus remains experimental.

Tracker evidence has independent optional records for pending text, pending geometry, crop presence
and completed absence. Each record owns its associated counts, time or source bounds; clearing a
candidate clears that evidence together. Accepted display and confidence review state survive pending
edits. Partial scans affect only covered tracks; delayed confirmation still validates each track's
own source sequence and reading. These records do not change confirmation or retirement policy.

## Translation, grouping and layout

`DialogueGrouper` forms bounded stable-line blocks with font-relative alignment/spacing and unambiguous
continuity. Keep speakers, choices, vertical text and unrelated columns separate. Punctuation alone is
not a hard break; avoid unrestricted proximity clustering. Pending growth can reserve a continuation
but cannot become translation source before commitment. Readiness uses source time; short labels avoid
dialogue delays. Group sizing uses individual line heights, not whole paragraph height.

Requests identify combined text and every member's ID/source/revision. Moving a box cannot retranslate;
geometry is not cache identity. Validate all members at publication/rendering. Splits/edits/removal/reset
reject stale replies. Keep full English in inspector/clipboard on overlay overflow. `EnglishPlacement`
uses bounded source-anchored candidates/spatial neighbors to reduce collisions deterministically; it
never drops translations or changes grouping/work. Impossible crowding may still overlap.

`TranslationPlan` assigns short and long text independently. Categories are structural/length-based,
not semantic dialogue. Missing models/connections never switch provider or billing route. Unchanged
requests stay pinned to their route. Switches revoke live/frozen English and drain before loading.
Adopt the exact prepared worker; same model in both categories shares one owner. Different local models
may coexist and consume additional RAM/VRAM.

`TranslationSession` owns backend loading/inference/unloading and SQLite. `TranslationSchedule` owns
bounded desired/retained work, exact source/context deduplication, cache-first lookup, serial dialogue
and fair waiting order. Revisions join the tail; withdrawn requests leave. Retained-only requests never
initiate inference. Futures only wake the owner. Revalidate after cache I/O and before dispatch/publication.
Known `RequestRejected` failures are bounded to exact request/revision/context; fatal failures stop that
translator while capture/OCR continue. Backend generation also scopes retained English.

Cache keys include weights/tokenizers, runtime, languages, decoding, adapter and frozen context; future
glossaries must extend identity. Serialize SQLite WAL/schema initialization, keeping connections on owners.
Disk failure preserves files and falls back visibly to bounded memory. English caches are not encrypted;
source text appears only through hashed keys. No routine logging/saving of frames or recognized text.
`DialogueMemory` is two turns/512 characters for one unambiguous panel, separate from the reader. Freeze
and hash context per request; only valid published English seeds it. Menus remain independent; reset on
scene/session/layout/age. Turn identity follows exact members/growth/correction lineage, not similar words
or reused position.

## Experimental dialogue reader

Settings → Experimental → Dialogue history defaults off and remembers opt-in. Off hides the reader/button
and stops collection/classification. Opening/closing it never alters translation. Its separate selector
offers prepared instruction models, configured cloud models and explicit layout-only mode; never silently
select, download or prepare a model. Text-only semantic judgments remain fallible.

`DialogueHistory` observes ready exact-current blocks/English. `PanelLayout` supplies bounded nearby text
and relative layout: stacked name/title metadata, headed dialogue and response groups/single options.
No screenshots, transcript, game-specific rules or additional name translation. Speakers require current
OCR confidence. Headers are metadata; choices cannot borrow a neighboring panel's speaker. New evidence
may retract only an exact still-live false entry, never rewrite older turns.

`ClassifierSession` has one owner/call, at most 128 candidates and bounded exact-input outcome caching,
including invalid replies. FIFO waiting survives unchanged observations. Identity includes body/speaker/
relevant panel text and structure, not coordinates, IDs, detector order or timestamps. Unchanged panels
are not reclassified. Cached scene analysis still advances readiness/time. Withdrawn active calls may
cache but cannot publish without current demand. Uncertain/failed model answers never fall back to
layout admission. Choice exclusions last only for live content/panel; no permanent text blacklist.

Translation never awaits classification. Disable/switch/stop/reset/shutdown cancels and drains its owner;
import probes wait for it too. Native loading/prefill may finish before cancel. Separate local models
consume resources; cloud checks share selected-profile limits. The reader holds at most 20 bounded turns
in memory, newest first with scroll anchoring and exact copy controls. Clear suppresses unchanged current
turns; growth/corrections update a turn, new capture clears history. Reader history never enters prompts.

## Cloud and credential boundary

Cloud use needs explicit configuration/route selection. Send bounded recognized text/context and optional
game hint, never frames. Editing/testing does not commit routing. Validate complete answers and bounded
streams; preserve per-backend concurrency/attempt/request budgets/deadlines without billing fallback.
Auth exchange/refresh/discovery/rotation waits carry cancellation; successful rotation persists even if
later discovery fails. `CloudServices` owns this work independently of widgets. Model removal retains
connections; Forget/sign-out are explicit. Catalog failure preserves saved data and never selects a model.
Draft Save commits; Cancel discards edits. Credentials never enter prompts, ordinary JSON, logs or fixtures.
Usage is per saved model for the current app run, shared across backend recreation, translation and
classification. The selected model's label updates independently of configuration revisions. Cache
hits reserve no requests; token totals count only provider-reported usage and are not billing totals.

API keys use Windows Credential Manager; OAuth uses user-bound DPAPI/account-bound encrypted envelopes.
OAuth uses the system browser, exclusive random loopback port, PKCE S256, state/nonce and validated
issuer/signature/audience/expiry/identity. Rotation is atomic under an account lock; temporary failure
preserves tokens. Logout clears local tokens even if remote revocation fails and reports the distinction.
Native credential buffers are wiped; Python copy zeroization is not guaranteed. Provider HTTPS verifies
certificates, disables redirects and ignores proxy environment; OAuth loopback is the local HTTP exception.
OS protection is a Windows-user boundary, not an application sandbox. Same-user programs, malware,
administrators and memory dumps are outside it. Forget does not revoke provider API keys; request limits
are not monetary limits. Automated tests use disposable fake credentials and transports, never paid calls.

## Models, downloads and native runtimes

Missing models do not stop capture. Inference never downloads; setup is explicit, with pinned hashes/sizes,
byte progress and atomic publication. Valid files survive retry/cancel; bundled repairs use writable state.
Both installers share `download_transport`: one contained child per transfer, parent-enforced 30-minute
deadline across DNS/connection/headers/body and cancellation polling at 100 ms. Terminate/drain before
partial cleanup. Socket inactivity alone is insufficient. Parent validation precedes atomic replacement.
Bundled restoration and verified cache reuse stay offline without a downloader child.

`OwnedProcess` creates suspended, assigns its Windows job, then resumes. Never launch uncontained.
Cancellation/deadlines drain descendants; output is bounded. Windowed download helpers attach their
inherited output pipe; the application never redirects stdout. `llama_runtime` serializes DLL setup,
import and legacy plugin registration, caching only successful initialization. Failure may retry.
Loading stays on model workers/probes; preserve old fork APIs and current upstream PLaMo support.

CPU/CUDA/Vulkan engines are complete upstream packages; CPU uses upstream PEP 517 build and standard
DLL repair at release time, no player compiler. Never mix CPU/GPU ONNX or different llama wheels.
NVIDIA OCR/Gemma share pinned CUDA 13 runtime/cuBLAS; preserve legacy ONNX 1.26/CUDA 12 loading. Select
DLLs for the actual OCR build, not another model's installation. Strict GPU checks fail on fallback;
automatic OCR reports fallback. Separate compilation from warm inference and keep the bounded CUDA cache.
In-app AMD is Vulkan translation plus CPU OCR. Experimental DirectML retains its numerical compatibility
probe; successful provider initialization is not validation.

Imported GGUFs use a separate bounded adapter/profile and explicit review/register. Inspect/hash on a
worker, test in a contained child after translator/classifier drain. Require actual GPU offload, complete
outputs, supported templates and empty reasoning. Cache identity includes content/profile/template/device/
decoding; recheck files on load. Never delete user-owned model files. Curated models reuse the adapter
without import registration. Preserve built-in prompts and distinct IDs; separate download size from RAM.

## Packaging, updates and persistence

PyInstaller owns the folder release/EXE; uv/Hatchling own wheel/source archives. See [building](building.md).
Bundle only three verified MeikiOCR assets/notices, CPU ONNX/llama and the app wheel, never translation
weights, preferences/caches or development/GPU environments. `resource_root()` is read-only; `state_root()`
is per-user AppData in releases, project-local in source. Optional environments use AppData-managed Python
independent of movable bundle resources. Validate the selected environment's own receipt, not latest-prepared.
Dependency identity compares exact wheel hashes/Python version independently of app version.

App updates install the verified bundled wheel offline without resolution into immutable hash-specific
AppData directories. Lock, probe and atomically publish the pointer. CPU/CUDA/Vulkan share app code while
reusing dependencies. Old running instances/rollback retain old code; never overwrite loaded files.
App preparation failure must not trigger dependency repair. Actual dependency changes need explicit
isolated setup preserving models/selection. Source remains editable; no duplicated source/custom bootstrap.

Setup and launch share `clean_runtime_environment`: clear all inherited `PYTHON*`, `UV_*`, `VIRTUAL_ENV`,
then add intended values. Managed helpers use `-P -s -B -m` with the selected app/resource/state paths.
Frozen helpers dispatch through the EXE's `--module`. Owned external launches temporarily clear the frozen
DLL directory under serialization. Restart waits for new Qt acknowledgement from the actual GUI PID,
not the Windows venv launcher. Normal launch honors saved selection and retains CPU fallback. Never bind
managed runtimes to the bundled interpreter or repair loaded native libraries.
