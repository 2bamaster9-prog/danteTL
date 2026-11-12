# Slice twelve — Model management, AMD package, and recent dialogue

Implemented:

- Explicit in-app model catalog/download/repair, progress/cancel, verified atomic files, and a
  dropdown of downloaded translators plus No translation. Missing-runtime entries stay visible
  with setup instructions. Capture works without models.
- First-use Gemma consent, responsive preparation progress, restoration on decline/failure, and
  reuse of the prepared worker. Runtime installation stays separate and explicit.
- Isolated AMD-compatible Vulkan runtime and launchers; CPU OCR by default, experimental checked
  DirectML with visible CPU fallback. Sugoi remains available in every environment.
- Two recent exchanges/512 characters of panel-scoped dialogue context, independent menus, exact
  contextual cache keys, fixed prompt bounds, and session/scene/expiry resets.
- A small source/setup sharing ZIP without weights or personal runtime data.

See [decision](../decisions/012-model-management-and-context.md) for contracts and limitations.

Acceptance: fast checks across CPU/CUDA/AMD environments; actual CUDA and Vulkan translations with
context, native setup with no models/decline/accept/worker reuse/unload, full dialogue/overlay
regressions, dense OCR and visible DirectML fallback, download integrity/cancellation, and package
contents review. Discrete Radeon testing and in-game conversation quality need user/friend feedback.

Verified: 248 tests plus Ruff/Pyright in all three environments; CUDA/Vulkan real-model translation
with blocked sockets; native setup and full dialogue/overlay checks; 900 ms delayed CPU OCR;
dense CUDA OCR and checked DirectML-to-CPU fallback; unchanged-label appearance replay. Native
setup kept the event loop active throughout preparation and reused the loaded worker. One context
sample preserved “Rina” where standalone translation chose “Lina,” adding about 171 ms on CUDA.

The source kit contains a verified hash manifest and all launcher/setup
dependencies. Its unpacked application imports and discovers no installed models, as intended.
No discrete Radeon or general game-performance claim is made. See verification/performance docs
for measurement scope and the DirectML failure boundary.
