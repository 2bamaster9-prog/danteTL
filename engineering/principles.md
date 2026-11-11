# Engineering principles

## Module design

Prefer a simple public interface owning substantial cohesive behavior. Split by responsibility,
state ownership, and change boundaries. Small functions are useful when they clarify an idea;
neither file count nor line count measures design quality. Explain invariants and reasons in
docstrings and comments. Avoid forwarding-only layers, generic event buses, and speculative plugins.

## Python conventions

Use typed dataclasses for value objects, explicit constructor dependencies, and Protocol only for
actual substitution boundaries. Assemble dependencies in the application entry point. Favor
standard-library facilities when sufficient. Isolate untyped third-party and Win32 interactions.
Use Ruff formatting, Pyright, pytest, a src layout, pyproject.toml, and a checked-in uv.lock.

## Concurrency and resources

Qt widgets belong to the GUI thread. Each background service owns its mutable state. Exchange
immutable snapshots or owned image buffers; do not retain native borrowed frame memory. Bound
queues and storage, prefer current work over obsolete frames, and define startup/shutdown behavior.
Keep expensive waits and processing out of UI callbacks. Surface native failures without guessing
another capture source. Close resources explicitly.

## Testing and changes

Test user-visible behavior and important invariants. Use real SQLite for persistence tests and
controlled clocks/results for replay tests. Isolate real-model and live-desktop checks from fast
tests. Add regression cases for meaningful bugs, not one assertion for each line of implementation.
Run relevant checks once changes settle, and repeat when further changes affect them. Keep design
decisions and their current consequences alongside the code.
