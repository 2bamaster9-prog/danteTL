# 014 — Settings and inspection are views, not processing state

The user approved the compact main window and separate Settings after reviewing the proposal.
Everyday controls stay on the main window; setup, appearance and recognition belong in a single
nonmodal Settings window. Advanced is collapsed initially. Essential failures remain visible.

Settings exposes Appearance, Recognition, Models, Acceleration and Hotkeys as peer tabs. There
is no nested Models/runtime tab bar. Setup links select their page by identity, and Acceleration
creates its existing view lazily on first visit. Navigating away never replaces or stops its worker.

`settings_window` owns the configuration widgets and embeds the existing model/runtime views.
Their workers continue when Settings hides; an explicit choice permits background operation or
cancels it. App shutdown still cancels and drains all owned work before restart or destruction.
Device and rate are sampled when capture starts, so editing Settings never replaces an active OCR
worker. Model arrival mid-session uses that captured device choice, not a pending setting.

Inspection formerly doubled as accepted OCR state: pausing it invalidated work and cleared tracks.
`ui` now retains the accepted OCR result independently. `inspection` keeps a bounded latest pair
and, when paused, one frozen displayed pair. Hidden inspection skips image conversion and table
construction. Resume uses the newest exact source/result pair. Neither visibility nor pause changes
scheduling, acknowledgement, grouping, generation, translation publication or overlay retention.
Source resize/minimize/stop still clears frozen imagery. Turning translation off leaves the game
unobscured unless the explicit raw-box/debug diagnostic is enabled.

`preferences` owns validated typed settings and coalesced atomic writes outside the GUI thread.
It stores no window handles, arbitrary model paths or transient debug/inspection state. The stable
Gemma ID survives CUDA/Vulkan changes; a backend is remembered only after loading succeeds (or
explicit No translation). Startup never prepares a model implicitly. Unknown individual values
fall back to defaults; corrupt/newer files are preserved, with a visible session-only warning.

Native Qt checkbox semantics provide keyboard/accessibility behavior beneath the custom switch
paint. Focusable information buttons expose the same explanation on hover, focus or click. These
controls add no animation or scheduling to the game overlay. CPU/GPU runtime separation, local
inference, consent, restart acknowledgement and the original coordinate contract remain unchanged.

Follow-up: ordinary controls use a bounded top-left column; maximization expands only available
space, not control spacing. Native tests exercise both Advanced states while maximized. Visible
symbol/text/color badges distinguish missing/downloaded weights and missing runtimes. Startup
hardware/package inspection runs once on a worker, without downloads; warnings do not imply that
vendor detection validates a driver or model. AMD CPU OCR remains intentional.

Model-specific persistent caches were already separated. Display retention now also has an explicit
worker/backend-generation scope, and accepted switches clear frozen inspector English. Keeping an
old snapshot's translation after changing its selected model was misleading. The inspected Japanese
frame can remain frozen; its revoked English cannot. This exception to pause does not reset OCR.
