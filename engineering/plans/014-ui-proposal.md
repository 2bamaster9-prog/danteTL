# Slice fourteen — Compact main window and separate Settings

Approved and implemented on 2026-11-13. The filename is retained for existing proposal links.
The earlier interactive mockup remains a design reference; application code and these behaviors
describe the delivered slice. No OCR algorithms, model runtimes, or translation prompts changed.

Follow-up feedback: controls now stay top-left in a column capped at 760 logical pixels, including
maximized mode. Advanced uses the remaining space and preserves maximize state. Missing models,
missing selection and unused GPU acceleration have amber action banners; downloaded models have
green check badges/list markers, with separate runtime warnings. A single background hardware check
informs advice without claiming inference compatibility or starting installation.

Accepting a translator switch now clears both painted English and any frozen inspector English.
Presentation retention is additionally scoped to worker/backend generation. Model-specific caches
are preserved, and regression tests cover a late old-model reply, paused review, and switching back
to the first model's cache. No cache-key collision between Sugoi and Gemma was reproduced.

Keep everyday use compact. The window picker, refresh, and Start/Stop capture remain necessary
session controls. Below them show only **Show game overlay**, **Translation overlay**, and the
translation-model selector. Put **Settings…** in the header and **Advanced** in a collapsed disclosure
below. A single plain status line stays visible: Ready, Capturing, Preparing model, or an actionable
error. Essential errors and setup actions must not disappear into Advanced.

Use switches for persistent on/off behavior, ordinary buttons for actions, and a disclosure for
Advanced. The whole switch label should be clickable, keyboard focus visible, and state available
to screen readers. No animated fade of game text is introduced by using switches.

## Main window behavior

- Show game overlay hides/shows game rendering without stopping capture or forgetting state.
- Translation overlay controls English translation/rendering. Turning it off leaves the game
  unobscured; numbered OCR boxes are an explicit Advanced diagnostic.
- The selector lists installed translators and No translation. Downloaded-but-unavailable models
  remain visible with a setup action; never silently disable the entire translation control.
- With no models, show a short inline **Set up models** action. Capture still works. Preparation,
  download, and acceleration status use clear words rather than a generic Ready badge.
- Missing dependencies lead to Settings → Models & runtime; unprepared Gemma asks for consent and
  shows preparation progress. Decline restores the previous model. Restart stops capture and waits
  for active work; the user starts capture again after reopening.

## Separate Settings window

Use one nonmodal window (reopening raises it) with three sections/tabs. Downloads/installations
continue on their existing workers. Closing Settings during an operation should offer **Continue
in background** or **Cancel operation**; app shutdown still drains/cancels before exiting.

| Section | Controls | Defaults and application |
| --- | --- | --- |
| Appearance | Stabilize game boxes; background opacity; automatic text size; manual text size | Stabilization on. Automatic size on; disable the manual field while automatic. Opacity changes live. Retain current stabilization semantics: English always uses stable tracks; this switch governs OCR-box diagnostics. |
| Recognition | Group dialogue lines; OCR device; capture rate | Grouping on. Available GPU with checked fallback where supported; AMD uses CPU OCR. Eight capture samples/s is the current default. Device/rate edits clearly say **Applies next time capture starts**, without interrupting the game. |
| Models & runtime | Installed/downloadable model list; size/status; Download/Cancel/Verify; detected adapters; recommended runtime; Install/Restart | Models and dependencies are separate states. Clear CPU option; manual GPU override. Show actual byte progress for models and stage progress for dependency installation. |

Save ordinary preferences automatically; no Apply/Cancel ceremony for changes that already affect
the live overlay. Keep runtime install and restart as explicit actions. Persist model/profile IDs
only after success, not file paths supplied by a dropdown. Do not persist an HWND as a durable game
identity. `data/preferences.json` stores validated version-one settings. Invalid individual values
use defaults; corrupt/newer files are preserved with a visible warning and session-only changes.
One coalescing writer atomically replaces the file off the GUI thread, and shutdown drains it.

Add a small focusable **info** button by every setting. It should work on hover, keyboard focus,
and click; do not make critical requirements available only on hover. Information copy:

| Setting | Information text |
| --- | --- |
| Stabilize game boxes | Keeps detected boxes steady when OCR jitters. Turn off only to inspect raw OCR boxes. Translation always uses stable tracking. |
| Background opacity | Higher values hide more of the original text. Lower values reveal more of the game behind the translation. |
| Automatic text size | Starts near the original text height, then wraps and shrinks within limits to fit the English. |
| Text size | Fixed English font size in physical pixels. Used only when Automatic text size is off. |
| Group dialogue lines | Translates nearby lines from the same dialogue panel together. Turn off if unrelated text is being joined. |
| OCR device | Chooses the device that reads Japanese text. This is separate from the translation model's GPU. Automatic reports CPU fallback when acceleration cannot be used. |
| Capture rate | How often the app checks the game image for changes. This is not OCR calls per second; higher rates use more resources and cannot speed up a busy OCR worker. |
| Translation model | Chooses a downloaded local translator. Sugoi is compact and CPU friendly; Gemma uses a supported GPU and requires preparation. |
| Runtime | Installs local libraries for your hardware. Does not download model weights or update graphics drivers. |

## Advanced disclosure

Move the entire highlighted area from the user's screenshot here: raw frame/boxes, recognized text
table, source/confidence/English columns, Pause inspection, Character boxes, fit/zoom, Copy Japanese,
Copy English, detailed OCR/translation/capture timings, skipped/held work counts, and technical help.
Also move Debug overlay and Open demo window here. Keep Pause inspection explicit: it freezes the
inspector, not capture or translation. Low confidence is a recognition score, not translation quality.

Default collapsed. Do not format/copy preview frames or rebuild hidden tables merely to paint an
invisible inspector; resume with the newest matching frame/result when expanded. Retain only the
bounded latest inspection pair, preserving the existing source-frame contract. Hiding Advanced must
never change OCR scheduling, grouping, retention, cache behavior, or diagnostics collection.

Acceptance: keyboard and high-DPI layouts, long model/window names, disabled
reason tooltips, no-model and no-runtime onboarding, settings persistence, pending device changes,
background setup, Advanced show/hide without capture or translation disruption, and regression of
overlay alignment/click-through and exact frame/result inspection. Verification and its platform
limits are recorded in [verification](../verification.md). See
[decision 014](../decisions/014-settings-and-inspection.md) for ownership boundaries.
