# 022: Session ownership and recoverable translation rejection

The live pipeline now has enough ordering policy to justify a coordinator without waiting for a
second UI consumer. `LiveSession` owns capture/OCR/visual lifetimes, accepted observations, tracking,
grouping, source acknowledgement and English publication. Commands and immutable scene values keep
Qt presentation separate. Model preparation, consent and runtime restart remain application lifecycle
concerns. Replay tests supply worker snapshots and explicit time, without constructing a window.

Prepared and committed runtimes are independent pointers. Each environment's own fingerprinted
receipt validates selection and rollback; repairing a hardware profile only advances its prepared
pointer. Containment and current dependency checks still apply to either pointer.

`OwnedProcess` owns process creation as well as termination. It uses CPython's Windows CreateProcess
bridge to retain the primary thread handle, creates suspended with an explicit stdio handle list,
assigns a non-breakaway kill-on-close job, then resumes. Assignment/resume failures terminate and
drain owned processes. Successful restart disables kill-on-close only after acknowledgement and
selection commit. This also covers model import probes; no interpreter user code runs before job
assignment. Native creation stays at this single Windows/CPython boundary.

Recognizers explicitly close native resources on their worker before completion. OCR and translation
`finished` additionally require thread termination. Shutdown does not infer completion from an empty
queue or a published state alone.

Backends declare batch size and a typed optional context capability. `RequestRejected` covers input
limits and unusable model answers, not loading/device failures. Rejected batches split once into at
most four individual inputs. Valid answers continue publishing; rejected requests expose diagnostics
and do not enter the cache/history. A 256-entry failure map includes exact request/revision and frozen
context, and resets with session/backend generation. Real content/context changes can request work
again; unchanged rejected work cannot spin. Fatal native errors still stop and close the worker.

Windows CI runs locked CPU development dependencies and the existing model-free checks. Interactive
capture, packaged runtime restart and actual GPU inference remain explicit local acceptance checks.
