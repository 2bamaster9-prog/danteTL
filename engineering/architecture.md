# Current architecture

This document owns cross-module contracts. Read the affected sections; code/tests own exact thresholds,
prompts and implementation details. See [building](building.md) and [verification](verification.md).

## Package layout

The distribution, Python package and CLI are `dantetl`; app-specific environment variables use
`DANTETL_*`. `DanteTL` is the display name. There are no aliases for previous names or module paths.

| Package | Owns |
| --- | --- |
| `application` | Commands, snapshots, preferences and coordination of capture, models, setup and shutdown |
| `translation` | Workers, scheduling, routing, publication; `backends`, `cloud`, `models` and `dialogue` hold their specific integrations |
| `ocr` | Recognition, scan planning, text tracking and visual retention |
| `languages` | Source-language selection, word boundaries and linguistic evidence for game text |
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
Controls and notices reuse the published OCR and translation state for the current refresh.
Resetting the scene releases its OCR snapshot, including the source image, as soon as capture stops.
`TranslationCoordinator` owns a `ModelLifecycle` through composition. Lifecycle state is private;
commands change it and immutable snapshots expose it. Assignment/readiness revisions can be read
without polling workers. Prepared-worker handoff pairs the worker with the model it loaded; a later
selection cannot relabel that resource. `ModelLifecycle` gates route activation, consent, probing and
shutdown. The coordinator tracks availability for each assigned model. Revoking one connection
withdraws its recipe on the next reconciliation even when another assignment is ready.
The routed owner retains unchanged workers during committed
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
Registration, relocation and removal hold the registry lock from the initial read through replacement.

Consent/review replies carry monotonic tokens. Decline/failure preserves committed assignments;
stale replies cannot adopt new proposals. Setup has three bounded lanes: models/imports, runtime,
and guide. Import probes wait for both translator and classifier cleanup. The skippable guide offers
downloadable bundles, not imported GGUF registrations; pending selection survives delayed discovery.
Hiding Settings never cancels an operation implicitly; app close cancels/drains all owners.
Shutdown waits for actual resource release and owner exit, not just a published result/failure.
Preferences and hardware work drain and hotkeys release before restart; failed restart resumes services.
Close and restart release the published scene immediately. Draining workers cannot republish its
frames or observations. A persistently invalid capture clears its scene once per loss of validity.

## UI, identity and coordinates

The public app name is DanteTL.
The interface locale is a separate preference from game source and translation target.
Changing the interface language replaces the app-owned Qt catalogs and updates text on existing widgets. Capture, model workers and editable values keep their state. English is the fallback. Mark app-authored copy
with `tr` and static metadata with `mark`, then translate that metadata for display.
Keep IDs, OCR samples, user content and inference prompts independent of the interface locale.
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
Users can set a sampling target or select Unlimited to accept each native callback.
At a numeric target, the rate guard admits slightly early callbacks in their scheduled slot.
Unlimited disables both pacing limits. Both modes replace the latest frame in one mailbox,
and OCR keeps its independent request cadence and coverage policy.
Capture copies packed BGRA rows from the mapped client area. The owned frame excludes row
padding and window chrome and remains valid after the native callback returns.

The overlay is nonactivating/input-transparent; hide on focus loss, minimize, stop, source failure or
size mismatch. Border edits reopen only the same native source while retaining processing owners and
sequence. Screen-capture inclusion changes overlay affinity only; report failure and restore settings.
Raw game capture must exclude our overlay. Affinity is not a universal recording/security guarantee.

English labels have lightly rounded borders, measured text padding and a translucent text shadow.
Windows rounds each native backdrop where the compositor supports the small-corner preference.
Experimental backdrop blur uses one click-through native surface per placed English label, up to
the live placement limit. English paints immediately with its regular background while new native
surfaces appear over successive event-loop turns. Retired surfaces hide and can be reused until
the overlay hides or blur is disabled. Surfaces share the overlay's recording preference.
Native setup failures use the configured background opacity.

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
Between OCR passes, a painted block can hide when every current member loses its glyph pattern.
A vacant line can hide on the first detailed capture if its backing or surrounding area changes
and native color edges confirm the space is clear. Other vacant lines require three distinct captures
spanning at least 160 ms. For a textured replacement, compare separate stroke patches across the old
line with positional tolerance. Strong surrounding change corroborates the loss immediately.
An isolated replacement needs a second capture with the same new pattern. Weak or surviving glyph
evidence defers to OCR. The publication and track survive so returning glyphs can
restore the same English on the next capture. Retirement requires a covered OCR miss
with corroborating pattern loss, or repeated covered misses across distinct captures. On a static
source, a single miss can settle only with strong pattern loss on that exact capture. Matching pixels
or a surviving stroke pattern at least as recent as a miss preserve the track. Positive OCR edits
still use their own confirmation rules. Coarse thumbnails screen changes; compressed long/vertical lines need overlapping,
aspect-preserving glyph-scale tiles before they can be declared unchanged. Reference pixels have
per-line and aggregate budgets. Exhausted or ambiguous fine evidence allows ordinary OCR confirmation;
it must not freeze a confident old reading. Fine comparison checks a new source-matched OCR review
and verifies suspected clearing of a compressed line.
Fine evidence may confirm unchanged glyphs despite a changed coarse thumbnail. Uniformly colored
rows with complete character locations can also use a foreground-color projection to reject neutral
background glints. Every letter/digit and reliable punctuation must contain that color; mixed text
falls back to grayscale. Local stroke-strength comparisons tolerate subpixel color fringes while
still rejecting numeric edits. Corrections may have two pixels of character-box jitter; sample only
inside accepted geometry. Optional color references share the pixel budget and cannot displace basic
references in the same observation. Beside such rows, small neutral glints are not growth; colored
additions and substantial strokes in another color still unlock OCR. Continuation checks cover the
nearby line end rather than extending into a distant column.
Visual failure visibly falls back to ordinary OCR. New translations wait for visual examination of their
OCR source; existing valid English is independent of readiness.
If optional crop evidence fails, matching can still accept the OCR result. A matching failure
acknowledges that observation once and requests a new full scan, preserving accepted text.

Partial OCR has explicit coverage; unscanned tracks are not misses. Pending areas union while pixels
are replaced. Retain per-line probe source sequences, whole-line closure and single coordinate offsets.
Within 120 ms the idle OCR worker can admit up to four requested areas if each additional
batch includes a disjoint area. Fully overlapping or full-frame demand waits on the worker
deadline, including when capture stops producing frames. The latest
pending image and accumulated coverage still require acknowledgement of the previous result.
An artificial-edge detection discards the provisional crops. An optimized plan retries the original
demand directly. An edge in the original crops triggers one full-frame fallback.
Independent full-discovery deadlines cannot be delayed
by typewriter activity elsewhere. `ScanPlanner` evaluates partitions of at most four areas using provider
costs and bounded geometry/confidence hints. Unknown/weak/small/vertical cases retain the baseline.
Changed plans need savings and glyph/coverage safeguards. Preservation requires a one-to-one matching
covering expected lines, using geometry/orientation/confidence without old-text equality. One oversized
detection cannot prove several lines survived. If expected lines are not preserved, discard
the result and scan original demand on the same frame, temporarily reverting to baseline. Full discovery
stays full. Publish only final raw output/actual coverage; reset hints with generation/provider/size.

Empty small crops may receive one background-padding retry without magnifying glyphs. Severed-glyph
recovery requires unambiguous adjacent detections and connecting ink; accept only strong complete
characters and preservation of unrelated lines. Otherwise keep the raw original. At most one extra
pass; subtract padding from both box types. CUDA recognition pads to batch four then slices actual
outputs; dummy detections never publish.

For unusually wide horizontal lines, retry recognition in overlapping pieces from the original
pixels. Join pieces where adjacent characters agree in text and position. Keep the original read
if any join is uncertain, the result is shorter, or previously observed glyph positions lose
coverage. Recovered text and character boxes belong to one original detection. Bound the extra
work per line and per scan.

On a single regional request the OCR worker can read an edited character directly from a
previously detected horizontal line. It compares every pixel of the requested area with the
previous covered OCR source, requires an isolated change within one character, and verifies
the new reading and confidence. Readers without character boxes use this only for numeric
fields. A successful read reports just its sampled line as coverage. Uncertain results,
changed surroundings, growth and subsequent reads after a direct read use the detector.

Tracking is deterministic and bounded (128 tracks, 512 candidate regions). Existing matches precede
new admission; truncated input cannot vote for absence. Spatially gated bipartite components use optimal
assignment with explicit unmatched costs, stable IDs and canonical tie ordering. Distant identical labels
cannot match on text alone. Candidate scores use normalized bit-parallel LCS/Indel with per-source masks
reused only within that matching pass. Bounded edit distance identifies nearby spelling variants;
short choices, numerical changes and typewriter growth have separate confirmation rules.
Confidence belongs to live content, not a screen-position cache.

The visual worker prepares immutable crop digests and geometric/text match scores for the exact OCR
source and an immutable snapshot of prior track identities, text and observed bounds. Results carry
source sequence/time/geometry and are discarded after worker invalidation. `LiveSession` rejects stale
matching state before reconciliation; assignment, confirmation, retention and acknowledgement remain
serialized on the application owner. No pixel hashing or text-pair scoring runs on Qt. Direct policy
replays can calculate scores inline. Preparation caches only one bounded result, including on visual
pattern-analysis failure. At most 1,024 proposed crops are hashed, each capped at 65,536 pixels; the
application consumes digests under the original one-million-pixel observation budget in the original
query order. Unused crop proposals cannot spend missed-track retention evidence.

Observed and committed text/geometry are separate. Worker delay, skipped frames and repeated polls are
not absence evidence. Bounded crop digests retain text through same-pixel misses; changed pixels alone
never remove text. Negative OCR needs coverage and elapsed evidence. Source-time settling works on static
WGC frames. New content/reset cannot inherit confidence. Accepted unchanged glyphs retain identity,
geometry and English. For a matched line with a minor spelling or bracket difference, only a
better OCR score can advance the reading. Repeated weaker or unscored variants cannot win by
waiting. Strong visual loss of the old pattern on the OCR source allows a similar new line to
start its own confidence baseline. Larger disagreements on visually unchanged glyphs have a
bounded low-confidence review.
A very weak divergent reading at an established label needs another matching OCR observation
before it can resize or replace the label. A quiet image cannot confirm its spelling.
`EnglishPresentation` owns the painted scene. Each publication keeps its exact translated source
and follows its live member bounds through edits. Automatic splits and merges swap together when
the replacement translations for their shared members are ready. Independent boxes can update
immediately. Retired members, model changes, source resets and explicit grouping changes clear
the affected publications. A visually concealed publication can return for the same live content.
When its track IDs acquire different text, only a ready translation can restore English there.

Tracker evidence has independent optional records for pending text, pending geometry, crop presence
and completed absence. Each record owns its associated counts, time or source bounds; clearing a
candidate clears that evidence together. Accepted display and confidence review state survive pending
edits. Partial scans affect only covered tracks; delayed confirmation still validates each track's
own source sequence and reading. These records do not change confirmation or retirement policy.

## Translation, grouping and layout

Each source selection has an immutable language policy. The catalog in
`languages.selection` registers Japanese and the 34 sources listed for Paddle’s PP-OCRv5 Latin recognizer. OCR evidence preparation, tracking, dialogue
grouping, translation prompts and cache keys use that selection. Blocks carry it so reconstructed
text, dialogue history and publication use the same word boundaries and script checks. The base
policy accepts alphabetic text and preserves word spaces. The 34 Latin sources use
`PaddleOCRLanguage` for inline quoted terms and closing quotes misread as apostrophes.
A source with additional text rules can register a subclass in `LATIN_SOURCES` and inherit
the same OCR model selection. Japanese supplies script and punctuation
cues, OCR cleanup, and evidence for quoted speech, equipment text and speaker names. The grouper
combines that evidence with paragraph position, row geometry and competing choices. The reader and
grouper use the same list syntax, with different evidence thresholds for possible and marked choices.
Pixel measurements, ambiguity checks, settling and request limits belong to the shared pipeline.
Changing the source clears dialogue history, translation demand, tracks and visual evidence.
If the same recognizer and device can serve the new language, capture and OCR continue on their
existing workers with a new evidence generation. Both pickers ask for confirmation when active
capture must restart to change OCR model or device. Capture then resumes only on its original
window. An idle or stopping capture stays idle. Model inventory discards previous-source scans.
The translation route reconciles each assignment against the new inventory. Compatible local
backends switch their prompt and cache identity on the inference thread between calls, retaining
their loaded weights. Incompatible lanes release their workers. The selected source determines
both the setup bundle and the OCR factory.
Japanese uses bundled MeikiOCR. The other registered sources share one bundled pair
of PP-OCRv5 mobile ONNX graphs. The Latin reader uses the pinned model's CTC vocabulary and a 2 GiB
CUDA arena limit. The detector keeps its 512 MiB limit. Regional scans receive the full client's
dimensions so Paddle detects at the same scale across scans. Its recognition crops include context
around each line. Paddle reads overlapping fragments on a common baseline together to avoid decoding
the same edge glyph twice. Tracking receives tighter horizontal text boxes and recognition confidence, with
stronger evidence required for isolated short labels that resemble icons. Automatic NVIDIA fallback
reruns the entire observation on CPU and reports it. Output language is a separate saved
preference, with English as the default. Each translation batch freezes the target for its prompt,
cache hash and published result. Changing it clears pending translations and dialogue context while
retaining OCR and loaded models. A completed reader entry keeps its original target even if the same
line remains on screen during a switch. Speaker translations must match the entry's target. Regional
variants have distinct prompt instructions and cache keys. PLaMo accepts only its documented PFML3
output codes. Explicit cloud profile tests capture the selected output language when submitted.
The Translation card and Appearance settings edit the same preference. Before capture, both project
documented target restrictions from enabled model assignments. An explicit Gemma switch uses the
existing assignment and preparation flow, preserving compatible assignments and category toggles.

`DialogueGrouper` forms bounded stable-line blocks with font-relative alignment/spacing and unambiguous
continuity. Keep speakers, choices, vertical text and unrelated columns separate. When ordinary
grouping finds no successor, a long unfinished row can pair with one tightly centered, shorter
sentence ending. A split word or a quoted term followed by a copula supplies the continuation
evidence. A short centered final word can also close a quotation embedded in a space-separated label.
This pair ends at its second row.
A sentence can end on a full-width row within a paragraph. A shortened sentence-ending row followed
by a full-width row can separate paragraphs within an established column. A trailing dash remains
continuation. Prose evidence may occur after the opening row. Quoted wraps tolerate hanging
marks/indentation and damaged brackets after a
typographic dash. A long hyphen run before an opening bracket can introduce a quote when a unique
aligned prose row follows. For an omitted dash, the matching worker checks a bounded strip of the
OCR source at the detector or recurring column margin for a thin, text-colored horizontal stroke.
The grouper uses the recovered edge only for that opening and continuation. A supported quote
ends at its outer closing bracket, keeping a button directly below it separate. Requests and
display retain the committed OCR text, member identities and ink bounds. Keep gap/font/ambiguity checks
intact. A quoted term followed by more words can continue an unfinished row on the established column pitch.
Paragraphs have no separate line-count cap. Work is bounded by the scene's track limit and the
backend's 512-character source budget. Short inline
labels start independent items and allow aligned/hanging continuations; bare choices stay separate. Compact
percentage endings can complete established unfinished prose or a line that explicitly introduces
a value. A colon immediately before a percentage can represent a misread plus in a wrapped
Japanese clause. In a column of wrapped prose, two successive row centers predict the
position of the next row. When two wide lines continue unfinished prose on that pitch and margin,
their ink heights can vary if both are consistent with the preceding body row.
The predicted spacing also supports shorter percentage glyphs and noisy operators at
the body margin. The same spacing can support a hanging labelled opening even when the
final value is unreadable. Group using that evidence and keep the exact OCR text in the request.
Before grouping paragraphs, reconstruct split horizontal rows in reading order. Close fragments
need an unambiguous baseline and support from neighboring prose or a previously confirmed intact
row with matching text, position and a surviving track ID. Recurring column margins and choice
markers separate neighbors. Use reconstructed geometry for layout and retain the original fragments
for readiness, request identity and publication.
The dialogue graph links mutually nearest rows by pitch, overlap, alignment and relative width.
It can replace blocks fully covered by a path when Japanese prose supports the new grouping.
Item markers, short endings and changes in lettering can stop a passage before a button.
A short second row can complete a prose passage when it contains a Japanese comma (`、`)
and ends in an ellipsis (`…`).
Repeated section headings and highlighted effect sentences followed by an activation condition
support independent instructions, including in a two-row crop. The OCR matching worker samples
lettering on the source image. Tracking retains compact samples for the corresponding reading
and location across partial scans. Grouping also works with geometry and text alone.
Ordinary pending OCR cannot repartition committed blocks. Pending growth can reserve a continuation
but cannot become translation source before commitment. Readiness uses source time; short labels
avoid dialogue delays. Group sizing uses individual line heights, not whole paragraph height.

Requests identify combined text and every member's ID/source/revision. Moving a box cannot retranslate;
geometry is not cache identity. Validate all members at publication/rendering. Splits/edits/removal/reset
reject stale replies. Keep full English in inspector/clipboard on overlay overflow. `EnglishPlacement`
uses bounded source-anchored candidates/spatial neighbors to place changed labels around existing
ones. Unchanged labels keep their placement within the same viewport and font settings. Qt receives
one scene per update and invalidates the old and new painted rectangles of changed English labels.
Impossible crowding may still overlap.

`TranslationPlan` assigns short and long text independently. Categories are structural/length-based,
not semantic dialogue. Missing models/connections never switch provider or billing route. Unchanged
requests stay pinned to their route. Switches revoke live/frozen English and drain before loading.
Adopt the exact prepared worker; same model in both categories shares one owner. Different local models
may coexist and consume additional RAM/VRAM.

`TranslationSession` owns backend loading/inference/unloading and SQLite. `TranslationSchedule` owns
bounded desired/retained work, exact source/context deduplication, cache-first lookup, serial dialogue
and fair waiting order. Outstanding sources reuse their hashed keys and cache answers. Newly admitted
sources are checked even at deferred inference capacity. On a scheduling pass, another SQLite
connection's commit invalidates remembered misses; the owner's own writes update them directly.
Revisions join the tail. The owner cancels an active cloud call when its exact source and frozen
context have no remaining desired or retained box. A retained box can keep an existing call alive
through readiness changes. Only ready boxes initiate inference or receive newly published answers.
Diagnostics report the age of the oldest active translation (including cloud admission waits) and
count obsolete calls cancelled within the active workers. Futures only wake the owner.
Revalidate after cache I/O and before dispatch/publication.
Known `RequestRejected` failures are bounded to exact request/revision/context; fatal failures stop that
translator while capture/OCR continue. Backend generation also scopes retained English.

Cache keys include weights/tokenizers, runtime, languages, decoding, adapter and frozen context; future
glossaries must extend identity. Serialize SQLite WAL/schema initialization, keeping connections on owners.
Memory hits participate in bounded, batched disk-recency updates, flushed on writes and close. Recency
across owners is approximate until flushing; capacity accounting and eviction are transactional. Evict
only the indexed oldest excess rows, without scanning an offset on every write. Keep the O(1) memory LRU.
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

Cloud discovery reports unreadable account records and API credentials and disables their dependent
profiles. Healthy connections remain usable. Cloud model, connection and API credential changes
share a per-catalog interprocess lock from the initial read through commit or rollback.

Cloud use needs explicit configuration/route selection. Send bounded recognized text/context and optional
game hint, never frames. Editing/testing does not commit routing. Validate complete answers and bounded
streams; preserve per-backend concurrency/attempt/request budgets/deadlines without billing fallback.
Auth exchange/refresh/discovery/rotation waits carry cancellation; successful rotation persists even if
later discovery fails. `CloudServices` owns this work independently of widgets. Model removal retains
connections; Forget/sign-out are explicit. Catalog failure preserves saved data and never selects a model.
Draft Save commits; Cancel discards edits. Credentials never enter prompts, ordinary JSON, logs or fixtures.
Usage is per saved model for the current app run, shared across backend recreation, translation and
classification. The selected model's label updates independently of configuration revisions. Cache
hits reserve no requests. A bounded FIFO admission queue paces shared dispatch across backend owners;
cancelled or expired waits consume no request allowance or future slot. Count requests at dispatch,
including retries and calls cancelled after dispatch. Token totals count only provider-reported usage
and are not billing totals.

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
Bundle verified MeikiOCR and PaddleOCR assets/notices, CPU ONNX/llama and the app wheel, never translation
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
