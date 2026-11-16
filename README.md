# DanteJP

A Windows game translation overlay with local OCR and optional cloud translation.

Capture a game window, recognize Japanese with MeikiOCR, translate stable
text locally with Sugoi V4, Gemma 4 E2B/E4B, Qwen3.5 4B or PLaMo 3 Translate, and draw English in an aligned
click-through overlay.
The inspector keeps raw Japanese, bounding boxes, and English together for review.

## Run

For the standalone Windows x64 release, extract **DanteJP-windows-x64.zip** and double-click
**DanteJP.exe**. Keep `_internal` beside the EXE. No Python installation, terminal, setup script or
administrator rights are needed. This is a portable folder in a ZIP, not an installer or a single-file
EXE. **MeikiOCR is included**, so Japanese text recognition works immediately on CPU without
downloading a model. Translation models, OCR repairs, settings, caches and optional runtimes go to
**`%LOCALAPPDATA%\DanteJP`**, shared across
app updates. Extract updates into a new folder after closing the app; your downloads stay in AppData.
Before uninstalling, use **Forget key** / **Sign out** for any saved cloud connections. Then delete
the app folder; delete its AppData folder only if you also want to remove your data. Deleting folders
does not remove API keys from Windows Credential Manager or revoke access at a provider.

First launch opens a skippable **Setup assistant**: choose a translation model, review the detected
GPU recommendation (or keep CPU), then confirm the downloads. Nothing downloads before you choose
**Download and set up**. It offers restart after runtime setup and retains separate first-use
preparation consent. Reopen it with **Settings → Setup assistant…** while capture is stopped.
Existing installations with OCR and a translation model already downloaded skip the welcome.

You can also use **Settings → Models** directly. MeikiOCR shows **Included with app**; its three
pinned ONNX files total 46 MB before compression. **Verify / repair** checks them and restores
damaged/missing files into AppData, reusing valid bundled files before downloading anything.
Models opens with **Local translation** and recommends **Gemma 4 E2B**. Use the **Model type**
menu to open **Text recognition (OCR)** separately. MeikiOCR reads Japanese text from images;
it does not translate. Its **Included with app** badge means no download is needed.
Saved translator choices are preserved. Compact ratings show dialogue, game terminology, speed
and memory tradeoffs; CPU/GPU support is separate from the installed-runtime badge. These are
qualitative judgments from local tests and player feedback, not benchmark scores.

| Model | Download | Intended tradeoff |
| --- | --- | --- |
| Gemma 4 E2B | 3.35 GB | Recommended balance of game terminology, quality and speed. |
| Gemma 4 E4B | 5.15 GB | Higher-resource recommendation; good game terminology, with more memory needed. |
| PLaMo 3 Translate 2B | 1.81 GB | Fast dialogue alternative; unreliable game stats/terms in player testing. |
| PLaMo 3 Translate 0.8B | 0.57 GB | Smallest LLM and very fast; weaker wording and unreliable game terminology. |
| Qwen3.5 4B | 2.74 GB | Optional alternative with useful results, but substantially slower in this app. |
| Sugoi V4 | 1.11 GB | Lowest resource use and fast CPU-only translation; recurring meaning changes and no conversational prompt context. |

These are download sizes, **not RAM/VRAM requirements**; inference needs additional working memory.
Quality depends on the text and no general Japanese-game translation ranking is established.
Gemma's E4B name denotes effective parameters, not a four-gigabyte memory limit.
The standalone CPU engine supports all offered models without GPU setup. Optional NVIDIA
CUDA or Vulkan acceleration improves responsiveness. CPU translation can be slower and is labelled.
The optional **Acceleration** tab installs GPU support for compatible engines, independently of
model selection. If an older/source environment lacks the engine, downloaded models stay visible as
**runtime setup needed**; choose CPU or GPU in setup. You can turn **Translation overlay** off at any time.
Capture works even with no models; English appears only after selecting a translator.
Downloads show byte progress, support cancellation, and check pinned SHA-256 hashes before files
become usable. Retry keeps verified files; an interrupted individual file restarts. Processing works
offline after setup when using local translation. Source checkouts still use **Run DanteJP.cmd** and project-local models/data;
those developer launchers require Python to bootstrap uv. The standalone release bundles its own
private CPU runtime, including llama.cpp, and dependency installer. GPU setup manages any additional Python privately in AppData.

## Dialogue history

Dialogue history is **experimental and disabled by default**. Enable it in **Settings → Experimental**
to show the **Dialogue history** button beside Settings, then choose a classifier in the reader.
Dialogue and speaker detection can be inaccurate. Your opt-in is remembered; disabling it hides
the reader and stops collection and classifier work.

The reader shows the last 20 completed dialogue turns in Japanese and English, newest first, and
keeps collecting while closed. **Clear** empties it; starting a new capture starts a fresh history.
The transcript is not saved to disk or added to model context. It reuses existing translations;
model-based classification makes separate requests and cloud classifiers use your plan/API allowance.
The copy icon beside each Japanese or English paragraph copies its plain text and briefly shows a
checkmark. Speaker headings are not included.

Detection favors lower-screen dialogue with a nearby speaker label or clearly centered, isolated
subtitles without a speaker. Names appear when OCR
confidence is high enough; otherwise it shows **Unknown speaker**. If the current routing also
translates the speaker label, it appears as **(translated name) Japanese name**. Menu/stat layouts
and ambiguous paragraphs are skipped. Unusual layouts can still be missed; a description laid out
exactly like a subtitle may be mistaken for dialogue. Grouping alone does not establish conversation.

## Optional cloud translation

In **Settings → Models → Model type → Cloud translation**, the list shows your configured models,
connections and credential status. Choose **Add cloud model…** or select a row and **Edit…**.
The editor keeps changes as a draft until **Save**; **Cancel** discards model/key edits.
**Advanced** reveals request limits. **Test connection** explicitly sends a sample without saving
the draft, and may consume plan usage or incur API charges. A **Key saved** badge does not mean
the connection has been tested. Sign-in/out and Forget key are immediate shared-connection actions.

**Refresh models** retrieves the provider's current list using your entered or saved key, without
sending a translation. Lists are cached per saved connection for offline use; failed refreshes keep
the previous list and never switch your selected model. Suggested choices remain available before
the first refresh. Newly discovered models can use **Test connection** to check compatibility;
being listed does not guarantee support for DanteJP's request format. Known presets keep their settings.

Available connections:

- **ChatGPT plan:** use **Continue with ChatGPT**, approve plan access, then choose from your
  account's model catalog. This uses OpenAI's public sign-in preview and depends on account eligibility.
  To test with included allowance only, disable credit use for DanteJP under **Manage ChatGPT usage**.
  DanteJP never purchases credits or falls back to an API key. Exhausted/unavailable plan usage
  leaves existing translations visible and reports the problem.
- **OpenAI / DeepSeek API key:** save your own key. These use the provider's separate API billing;
  an API key does not draw from ChatGPT Pro usage. Any eligible activated API-credit grant applies
  according to OpenAI's billing rules.
- **Gemini API key:** use a Google AI Studio API key. Suggested choices: Gemini 3.5 Flash-Lite,
  3.8 Flash and 4 Hydrogen. Requests use the API project's quota/billing.
- **Claude API key:** use a workspace-scoped Claude Console API key. Suggested choices: Claude Haiku 5.5
  and Sonnet 5.5. These use Claude API billing. Gemini and Claude chat subscriptions are not
  connected by these API-key options.

Start with Flash-Lite or Haiku when comparing response times, then try the other models for quality.
These are provider positioning and configuration choices, not DanteJP game-translation benchmarks.
All five use low/minimal reasoning settings and the same game hint and bounded dialogue context.

The main window separates **Game & overlay** from **Translation**, side by side on wide windows
and stacked on smaller ones. The simple model picker lists local and saved cloud models together.
**Advanced routing** replaces it with one model picker each for **Short labels** and **Long text &
dialogue**. Either category can be switched off in either view. Changing views preserves assignments.
Two different local models are supported, with a memory warning; assigning the same model to both
categories loads it once. Long text includes grouped paragraphs and single lines over 40 characters,
so it includes descriptions as well as speech. Cloud-only translation needs no downloaded translator
or GPU runtime. The game name defaults to the selected window title; turn off **Use window title**
to enter your own terminology hint. Only recognized text and at most two recent dialogue turns are
sent; screenshots and OCR stay on the PC. Saving a connection alone does not enable cloud requests.

Cloud replies use the existing text cache and scene validity checks. Partial streamed answers are
never painted. Slow cloud work does not block the other assigned model or ready cache hits. Each
cloud model permits at most two independent requests, while its dialogue stays ordered. Configure request
rate and per-app-run attempt limits in Models; these are request limits, not dollar spending caps.
Authentication is included in the request timeout and is cancelled and drained when switching
models or closing the app. You can save up to 16 cloud models. Provider connections are remembered
across models and app restarts. Choose a saved **Connection**
when adding another model; leave the key field blank to reuse it. Replacing a connection's key
updates every model using it. Removing a model keeps its connection; **Forget key** removes the
saved API key separately. It does not revoke the key at the provider. ChatGPT models reuse the
selected signed-in account; **Sign out** disconnects it.

API keys use Windows Credential Manager; ChatGPT tokens use user-bound Windows DPAPI encryption
in AppData. Credentials are excluded from ordinary configuration and app logs. This protects stored
secrets, not against malware running as your Windows user or an administrator. See the
[credential boundary](engineering/architecture.md#cloud-and-credential-boundary) for storage and limits.

Cloud verification currently uses simulated provider responses, real loopback callbacks and Windows
credential protection. Real-account eligibility, billing and translation quality require user testing.
See OpenAI's [sign-in documentation](https://developers.openai.com/siwc/token-sharing-open-source)
and [API-credit benefit](https://help.openai.com/en/articles/20001626-api-credits-benefit-for-eligible-chatgpt-subscriptions).

**Downloaded model but no English / no Automatic OCR?** Model files and GPU runtimes are separate.
Open **Settings → Acceleration**. The app detects graphics cards and recommends a runtime;
you can choose manually. **Install runtime** downloads pinned dependencies into a separate local
environment, shows stage progress, and checks native libraries. **Restart now** stops capture,
waits for current work, and opens the new runtime. **Use on next launch** keeps this session running.
Both **DanteJP.exe** and the source **Run DanteJP.cmd** remember the choice. No separate GPU setup scripts are needed.
The Models tab distinguishes downloaded files from runtime readiness and shows their folder.
It reuses your downloads; reinstalling or redownloading model weights is unnecessary. The CPU
launcher intentionally uses the CPU OCR environment; it does not inherit packages from the GPU one.

The **NVIDIA GPU — CUDA** option accelerates supported OCR and translation engines using shared CUDA 13 libraries. Its pinned
NVIDIA/ONNX downloads total about **1.29 GB**, down from 2.26 GB; other app dependencies and model
weights are additional. OCR stays GPU-accelerated. After updating from the older package, open
Acceleration and install the new runtime once, then restart. Existing model downloads are reused;
the old runtime is retained until you choose to remove it.
The **GPU — Vulkan** option accelerates supported translation engines and keeps **CPU OCR**. It does not install experimental DirectML:
that provider produced incorrect Meiki results on the development machine. Vulkan setup and inference
were checked on the RTX 5080; a discrete Radeon still needs testing. **CPU** provides MeikiOCR, Sugoi and llama.cpp for all offered language models.
Runtime libraries can be shared by compatible future models; installing them does not add models.
No system CUDA toolkit or server is needed. Graphics drivers must already support the chosen runtime;
setup never installs or updates drivers. Hardware detection is a recommendation, not a compatibility
guarantee. Multi-GPU users can override it.

Runtime installation shows the setup stage and a second bar for the **current file**, with downloaded
MB and a percentage when its size is known. Unknown-size downloads show received bytes; the private
Python installer and native checks use activity indicators when byte progress is unavailable.
Verified wheels are cached in `.runtime-downloads` for retry/reuse; an interrupted file restarts.
Cancel/failure keeps the running environment and model files. A failed install
can be retried; **Verify / repair runtime** checks an existing install and creates a separate replacement
if needed. A failed restart leaves the old app available. CPU fallback remains accessible through
**Run DanteJP.cmd --cpu** (or `DanteJP.exe --cpu`). Replaced runtimes are retained in `.runtimes` for recovery, so repeated
repairs can consume extra disk space. All processing after setup stays local.

Library checks do not load models. The first OCR GPU load can take about a minute to compile kernels;
its loading status stays visible. Gemma has the preparation flow below. A bounded cache under
`data/cuda-cache` is reused; driver/kernel changes may require another warm-up. Legacy setup scripts
remain available for development but are not required by the in-app acceleration flow.

Selecting an unprepared language model asks **Prepare now?** Choosing No restores the previous model
or an unselected model. Yes shows a responsive progress dialog while checking weights and running a
short test translation on the selected device. It uses an indeterminate bar because the runtime cannot report a reliable percentage. The
prepared worker stays loaded for capture. Preparation receipts are local to the machine/runtime;
driver changes can still require warm-up, shown as loading. Nothing downloads during preparation.

Gemma, Qwen and PLaMo keep at most **two recent dialogue exchanges / 512 characters** within their
2,048-token allocation. Only one likely dialogue panel owns history; short menu labels remain
independent. History expires after 30 seconds, prolonged panel absence, panel relocation, broad
scene changes, or session reset. It is a conservative heuristic, not a speaker/name glossary.
Context is part of cache identity, so unrelated conversations cannot reuse contextual answers.
Settings → Models also offers **PLaMo 3 Translate 2B** (1.81 GB) and **0.8B** (0.57 GB),
Japanese–English specialists. These are download sizes, not total working memory. Both run on CPU,
CUDA or Vulkan. PLaMo uses the PLaMo Community License; review the linked model-card terms for
commercial use. If an older installation says Engine update required, install a runtime in
Acceleration and restart; no model redownload is needed. The standalone includes the updated CPU
engine. The small local comparison is documented in `engineering/benchmarks`.

The offered Gemma/Qwen weights are Apache-2.0; Sugoi retains its separate licensing. See
[model/runtime contracts](engineering/architecture.md#models-downloads-and-native-runtimes) for setup and compatibility limits.

**Settings → Models → Import GGUF…** adds a local single-file chat model by reference, without
copying it or downloading anything. Choose a file, optionally name it, then **Test compatibility**.
The app checks the file, temporarily unloads the current translator, and tests menu/dialogue samples
in a cancellable child process using the installed CPU, CUDA or Vulkan engine. Capture continues;
translation resumes with the previous selection afterward. Review the sample English and timings,
then **Add model**. Select the imported model on the main screen to use it.

Automatic format uses Gemma 4's native prompt, PLaMo Translate's PFML3 format, or the embedded GGUF chat template. Explicit ChatML
and Llama 3 formats are available for models whose documentation requires them. Passing the test
confirms local execution, not translation quality. Split files, embedding/projector-only models,
and TranslateGemma's specialized input format are not supported in this first version. Translation
remains Japanese → English. Imported models receive the same bounded dialogue history as Gemma;
menu labels stay independent. Built-in Gemma/Sugoi prompts are kept separate from imported-model formatting.

Registrations live in `data/imported-models.json` under the app's writable state (AppData in the
standalone app). If a file moves, use **Locate file…**; changed contents need a new import/test.
**Remove from list** never deletes your model file. Each model/profile has a separate translation
cache identity. Only one language model is loaded at a time.

Releases use **PyInstaller** for the Windows app and **uv/Hatchling** for standard Python wheel
and source distributions. With uv 0.13.8 installed, the local and GitHub Actions build command is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build.ps1 -DownloadOcr
```

`-DownloadOcr` explicitly prepares the three pinned OCR assets. Omit it when those files already
exist; use `-Offline` when all dependencies/assets are cached. The build uses an isolated
`.venv-build`, locked dependencies and CPython 3.12.16. It does not change your development or GPU
environments. Send **`dist/DanteJP-windows-x64.zip`**; wheel, source archive and SHA-256 sidecars
are also produced. Translation weights, personal data and optional GPU runtimes are excluded.
The EXE remains unsigned. See [building and verification](engineering/building.md).

The **Windows distributions** workflow runs the same command, fast checks and an offline OCR
check of the relocated EXE. It uploads artifacts on version tags, manual runs and build-related
pull requests. Desktop capture/GPU acceptance still runs locally.

Alternatively, with uv installed:

```powershell
uv sync --locked
uv run python tools/setup_models.py
uv run python tools/setup_models.py --translation
uv run jp-overlay
```

The app is now named **DanteJP**. Existing installations can keep their current project folder,
models, settings, caches and installed runtimes; launch with **Run DanteJP.cmd** after updating.
The internal Python package (`jp_overlay`), CLI alias (`jp-overlay`) and `JP_OVERLAY_*` environment
variables retain their original names for compatibility. New logs are in
`%LOCALAPPDATA%/DanteJP/logs`; existing logs in the old folder are left intact.

For native language-model setup, close source app instances and use `tools/setup.ps1`
(CPU), `tools/setup.ps1 -Gpu` (CUDA) or `tools/setup.ps1 -Amd` (experimental AMD development profile).
These use uv's locked dependency groups. CUDA/Vulkan install complete upstream wheels; CPU builds
the upstream source package and requires C++ Build Tools on the developer machine. Standalone
players need no compiler: the release includes its finished CPU wheel. Source-checkout in-app CPU
setup uses the wheel prepared by `tools/build.ps1 -CpuWheelOnly`. In-app Acceleration always creates
a separate environment. Keep the appropriate group enabled when syncing (`llm-cpu`, `gemma`, or
`gemma-vulkan`); a plain sync selects only the default groups.
Install model weights explicitly through Settings → Models. The `.cmd` launchers use the installed
environment directly. Keep CPU and GPU OCR dependency groups in their separate environments.

Choose a window and select **Start capture**, then switch to the game. OCR and translation load in
the background. **Translation overlay** is enabled by default; translated regions cover the original
text with a translucent background. Regions awaiting translation leave the original text visible.

The main window contains the game picker, Start/Stop, **Show game overlay**, **Translation overlay**, **Show border**,
and the model selector. **Settings…** opens a separate window; **Inspection and diagnostics** expands
the inspector and detailed diagnostics. Setup errors and model loading remain visible when collapsed.
At the bottom, **Capture & Stability**, **Text Recognition**, and **Translation** separate live
timings and work counts. Hover a label for its meaning. **Last batch** shows cached versus newly
translated sources; **Model call** remains the most recent actual inference time. These are
stage measurements, not a summed capture-to-English delay. Pausing inspection keeps them live.
The main controls stay together at the top left, with a bounded width even when maximized. Inspection
uses the extra space without changing the window's maximized state.
Model dropdowns have sections for local models, ChatGPT plan models, and each cloud API provider.
Headings are not selectable. Use **Translation overlay** or the text-category switches to turn
translation off; model choices stay remembered. Empty/unavailable selections show a placeholder
instead of automatically choosing another model.

Global shortcuts work while the game has focus or DanteJP is minimized:

| Shortcut | Action |
| --- | --- |
| **Ctrl+Alt+F8** | Show / hide the game overlay; capture and translation continue |
| **Ctrl+Alt+F9** | Start capture of the focused window, or stop the current capture |
| **Hold Ctrl+Alt+F10** | Show original text while held; release to restore the overlay |

Change either under **Settings → Hotkeys**: choose modifiers and a key, then **Apply**. Choose
**Disabled** to turn that shortcut off. Successful changes are saved; a conflict leaves the previous
shortcut active and explains what happened. Close another DanteJP instance if it owns the same
keys. **Capture the focused window**, enabled by default in Hotkeys, selects your focused game when
starting through the shortcut. Turn it off to use the existing selection. The main Start button
always uses the selected window. During capture the hotkey always stops that session, regardless
of focus; it never switches an active session to another game. Desktop, DanteJP and unusable
windows are rejected with a status message, without falling back to the old selection.

Hold-to-show-original hides the overlay without changing its saved switches, restarting workers,
or clearing translations. Releasing any part of the chord restores current valid English immediately;
an intentionally hidden overlay stays hidden. Focus loss, stop, rebinding and shutdown cancel the
hold. Toggle shortcuts do not repeat while held. Shortcuts pause during modal
prompts and shutdown; capture also waits for an earlier stop to finish. Games that reserve keys or
intercept system input may require a different combination. There are no keyboard hooks or injection
into the game; only native Windows shortcut registration.

Amber banners identify missing OCR/translation downloads, no selected translator, or unused GPU
acceleration, with a direct setup/settings action. A green **✓ Downloaded** badge and checkmarks in
the Models list identify files already present. Gemma can show both **Downloaded** and **Acceleration
setup required**: weights and runtime readiness are separate. GPU advice uses a one-time background
hardware/package check; detection alone is not a promise of driver/model compatibility. CPU remains
the normal OCR choice for the AMD runtime.

- **Settings → Appearance** contains stabilization (on by default), background opacity, and text size.
  **Automatic text size** estimates the source height and wraps English with limited shrinking.
  Turn it off to set a fixed size in physical pixels. Opacity changes apply immediately.
- **Settings → Recognition → OCR device** selects available NVIDIA/DirectML acceleration with CPU
  fallback, or CPU only. Device and capture-rate edits apply **next time capture starts**; current
  capture continues uninterrupted. Inspection reports the actual provider and any fallback reason.
  **Capture rate** ranges from two to twelve samples/second and defaults to eight. These captures
  feed cheap visual checks; they do not each trigger OCR. Increasing capture rate improves visual
  response but increases frame-copy/analysis cost and cannot make a busy OCR model faster.
- **Sugoi V4 · Fast CPU** is the default. **Wider search** uses the same weights with more decoding
  candidates; it can take longer and is not guaranteed to improve every sentence. Switching safely
  unloads the previous backend before loading the selected one.
  Accepting a model switch immediately clears the old displayed English, including paused inspector
  translations. Current text is translated by the new model; late replies from the old model cannot
  replace it. Each model keeps its own cache, so switching back can reuse its previous translations.
- **Gemma 4 E2B · NVIDIA/Vulkan GPU** uses an instruction-tuned LLM. It can produce more natural
  UI labels and dialogue, but quality still needs review in the actual game. Each completed label
  publishes immediately; the source-specific cache remains separate from Sugoi.
- **Inspection and diagnostics → Debug overlay** adds amber cells for significant visual changes and cyan dashed outlines for
  the **last completed OCR scan**. The panel shows OCR/translation times, queue waits, active call
  age, cache/model counts, and dialogue settling/reveal holds. Cyan coverage can remain after the
  scene changes: read its result age. Debug does not change scheduling or save game text/images.
- Translations are reused from a bounded memory cache and local SQLite database. Moving a box
  does not retranslate its text. Brief OCR jitter keeps the last committed English until a real
  change is confirmed; changed/removed text rejects late results.
- For small OCR variations in nearly the same position, the tracker remembers the highest-confidence
  reading. Weaker/equal alternatives keep its text and box unchanged; a confirmed stronger reading
  becomes the new preference. Numbers, short labels, and typewriter growth use normal confirmation.
  A consistently changed alternative can still replace the old reading after about 1.25 seconds.
- Turn **Translation overlay** off to unload translation and leave the game unobscured. To inspect
  numbered game boxes, explicitly enable **Inspection and diagnostics → Show OCR boxes**. **Stabilize game boxes**
  in Settings can then be toggled for comparison. English always uses stable tracks.
- **Settings → Recognition → Group dialogue lines**, on by default, joins likely wrapped dialogue and descriptions before translation
  and draws one English box. Disable it if unrelated lines group together. Short speaker names,
  marked choices, and separate columns remain separate under the conservative rules.
  Short sentence endings and split OCR fragments inside an established paragraph are included.
  Internal sentence punctuation helps reserve a group before the final line arrives.
- Revealing dialogue waits for its text to settle before new translation work is scheduled. Likely
  continuation lines join while they are still appearing, avoiding a second grouping delay at the
  end. Existing, revision-valid English remains visible while readiness changes. A long pause in
  unfinished text can still look like completion; this is a timing heuristic.
- Visual checks watch known text and the space where dialogue can continue. Small stroke additions
  can hold an obsolete partial translation before OCR recognizes the new line. A revealed paragraph
  may contain multiple sentences; a period alone no longer splits a paragraph that was growing.
- Closing a menu can hide its English after two visual checks find its text pattern gone, even
  while OCR is busy. Identity/cache entries stay available until OCR confirms absence; strong fresh
  visual absence plus one negative OCR pass can free old display slots promptly. Brightness shifts
  and hover color inversions are tolerated. Ambiguous cases keep the slower OCR evidence rules.
- Tracking uses recognized-character bounds so a detector box expanding over an icon does not
  automatically resize English. Isolated weak edge glyphs beside strong Japanese text can be
  excluded. Raw OCR remains unchanged in the inspector for comparison.

Settings save automatically in `data/preferences.json`. A successful model choice is remembered
without loading it at startup; first-use preparation still requires consent. Info buttons explain
each setting on hover, keyboard focus or click. Closing Settings during setup offers background
continuation or cancellation; closing the app always cancels/drains setup before exiting.

The **Inspection and diagnostics** panel displays the exact analyzed frame, numbered line boxes, raw OCR, and matching English:

- Select a text row to highlight its box and see physical coordinates/orientation.
- Use **Pause inspection** to freeze the frame and both languages while capture and translation continue. Resume picks up
  the newest frame. Minimize, resize, or stopping clears the review so stale imagery is not retained.
  Switching translation models also revokes frozen English; the inspected Japanese/frame stays frozen.
- Use **Character boxes** and **Fit / 100% / 200%** zoom to examine small text; scroll when zoomed.
- **Copy Japanese / Copy English** copies the selected row, or all rows when none is selected.
  Hover a row for full text. English that cannot fit the overlay ends with an ellipsis; the full
  translation stays available in the table.
- Group continuations display **↳ Group #ID**. Hover an English cell to see the cleaned/grouped
  Japanese source actually translated. Copy English from any member copies the whole translation;
  copying all rows includes each group once.
- Confidence is the mean recognized-character score, not a probability of sentence correctness.
- The overlay may briefly lag; use the frame-matched preview when checking OCR accuracy.
  Hiding or pausing the inspector leaves the live game overlay and tracking intact. Collapsed
  inspection skips image conversion and table updates, retaining only the latest matching pair.
- Small shifts retain the existing box; repeated text/size changes are confirmed before updating.
  Processing delays do not erase boxes. Unchanged crop pixels preserve text through OCR misses;
  otherwise removal requires repeated negative observations. Raw OCR stays visible in the inspector.
- IDs persist through OCR reordering and match between the inspector and game. They reset to new
  identities after resize, minimize, or capture restart. Unrecognized text has no ID.

**Inspection and diagnostics → Open demo window** provides Japanese text and an animated target without needing a game. CPU
inference uses two threads per engine; optional GPU acceleration applies to OCR and Gemma, while
Sugoi stays on CPU. OCR timing and
capture-to-start delay, current-pass time, and skipped waiting frames are shown separately from
capture frequency. Hover the OCR status for recent average inference time. Frames are replaced
rather than queued when busy; processing one frame never starts overlapping OCR jobs.
The visual worker also keeps only its newest waiting job. Changed/settled regions prompt cropped
OCR; a full discovery scan runs about every three seconds. Crops include padding and whole known
lines. Broad changes or cut-off detections use a full scan. Waiting scan areas merge on the newest
frame so busy workers cannot lose a changed region.
Accepted regions also gate later OCR results: unchanged glyph patterns retain the same Japanese
source, English and geometry, even when a later pass misses or misreads them. Readings below 90%
OCR confidence get three review attempts; only a score improvement greater than one percentage
point can win. The previous English stays visible until the corrected translation is ready.
Real local changes unlock normal updates. The inspector always keeps the raw model output.

Unscanned regions keep their accepted translations and do not count as missing text. Dialogue
grouping uses the whole tracked scene; a scan elsewhere cannot restart a line's confirmation wait.
The inspector shows only the current scan's real detections, not old rows carried onto a new frame.

Status identifies full/area scans, unchanged regions held, visual-check time, and captures skipped.
This is not a guarantee that
every animation can be ignored. Visual failure is reported and falls back to ordinary OCR.

Use windowed or borderless fullscreen. The overlay hides when the target loses focus, minimizes,
or closes. Stop capture before changing sources. **Show border** controls the yellow Windows capture
indicator and is saved between launches. It can change during capture without resetting OCR or
translations; Windows policy or another recorder may still require the border.
For screenshots, videos and screen sharing with translations, capture the **display/entire screen**
(for example, OBS Display Capture). Game-only or window-only sources may omit the separate overlay.
**Include in screen capture** in Game & overlay defaults on. Turn it off to exclude the overlay
from capture apps that respect Windows' display-affinity setting. The choice is saved and applies
immediately; its own OCR still captures only the game window either way.
This app does not inject into games, request administrator access, or save screenshots automatically.

## Development

```powershell
uv sync --locked
uv run python tools/check.py
uv run python tools/verify_ocr.py --output artifacts/ocr
uv run python tools/verify_ocr.py --dense --output artifacts/dense-ocr
uv run python tools/verify_translation.py
uv run python tools/verify_windows.py
uv run python tools/verify_ocr_windows.py --translation --dialogue
uv run python tools/verify_ocr_windows.py --translation --dialogue --ocr-delay-ms 900
uv run python tools/verify_ocr_windows.py --translation --dialogue --typewriter
uv run python tools/verify_ocr_windows.py --translation --dialogue --typewriter --transitions --ocr-delay-ms 900
```

After GPU setup, use `.venv-gpu\Scripts\python.exe` directly for the same checks, adding
`--device cuda` to OCR checks. This strict verification mode fails rather than silently passing on
CPU. Plain `uv run` uses the default CPU environment; do not install both ONNX Runtime distributions
into one environment because they share package files.

The replay check renders an original Japanese fixture and blocks network connections during model
loading/inference. Only its synthetic output is saved. The two Windows checks open temporary test
windows on an unlocked desktop. See [verification](engineering/verification.md).

Read the [engineering guide](engineering/README.md) for current contracts and checks. Capture and
OCR run locally; explicit downloads and selected cloud translators use a network connection.

Source checkouts keep models in ignored `models/meiki` and `models/sugoi-v4`; set `JP_OVERLAY_MODEL_DIR` or
`JP_OVERLAY_SUGOI_DIR` to use other directories. English cache entries persist in ignored
`data/translations.sqlite3`; close the app before removing that cache if you want a fresh evaluation.
Use uv/the bundled setup: it resolves the two upstream OpenCV dependency names to a single `cv2`
installation. No model weights or captured game screenshots belong in Git.

The pinned Sugoi repository supplies [research-use, noncommercial model terms](https://huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2/blob/71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b/LICENSE).
Setup preserves that license with the weights. Translation weights remain separate downloads;
private use does not automatically resolve the model's use restrictions.

## Current limits

Japanese OCR quality still needs representative game evaluation, especially tiny 4K HUD text,
furigana, long lines, dense menus, and vertical text. Other visible languages may be detected but
are not the accuracy target. The inspector shows recognition errors as returned. Exclusive fullscreen,
protected windows, HDR color fidelity, and untested game/anti-cheat combinations are not guaranteed.
Mixed-DPI monitor behavior has automated coordinate coverage but requires real hardware verification.
Windows 10 is not the initial validation target. The portable Windows x64 release uses the same
application and processing code as the source checkout.

Tracking uses position/text heuristics, not semantic understanding or optical flow. Crossing labels,
major layout changes, and multiline splits/merges can create new identities. A disappeared region
may linger briefly; real-game stabilization thresholds still need feedback. OCR continues sampling
to discover changes even when the displayed overlay remains unchanged.
Absence confirmation is a heuristic, not certainty. Slow inference delays discovery and removal;
a stuck worker retains its last state until recovery, failure, or a session reset. Foreground-stroke
checks retain unchanged labels over dim animated backgrounds; ambiguous/weak templates still use
OCR confirmation and can behave less reliably.

Dialogue grouping uses alignment, spacing, size, and punctuation; it does not identify actual game
panel boundaries. Punctuation-free, centered, or unusual dialogue may stay separate, and similar
menu layouts can still be ambiguous. Context-capable models can also use bounded recent dialogue;
there is no glossary. Icon filtering is conservative and cannot identify every high-confidence or overlapping
icon. Names and short labels can translate awkwardly. English boxes may expand over neighboring
dense UI; collision-aware layout remains future work. Vertical source text stays ungrouped and
renders as horizontal English. Toggle English off/on to retry a visible backend failure.

Visual checks add evidence, not semantic certainty. A flash, occlusion, low-contrast/tiny text, or
unusual background can still delay or temporarily mask a box. Periodic full OCR catches uncertain
changes; small changes use regional inference with full-scan fallback. An already-running model call cannot
be canceled, so very slow OCR still delays new English even when old boxes hide promptly.
