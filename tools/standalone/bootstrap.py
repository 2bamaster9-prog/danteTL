"""Entry point shared by the native launcher and explicitly selected managed runtimes."""

import ctypes
import os
import runpy
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
# Managed GPU Python also needs an app-local MSVC runtime before importing ONNX/CTranslate2.
# Use this interpreter's PySide wheel, never DLLs from a different runtime or system PATH.
_native_libraries: object = None


def main() -> None:
    global _native_libraries
    _native_libraries = os.add_dll_directory(str(Path(sys.prefix) / "Lib/site-packages/PySide6"))
    from jp_overlay.paths import state_root

    state = state_root()
    state.mkdir(parents=True, exist_ok=True)
    if sys.argv[1:2] == ["--module"]:
        module = sys.argv[2]
        if module != "jp_overlay" and not module.startswith("jp_overlay."):
            raise ValueError("Only DanteJP modules may be launched by this entry point.")
        sys.argv = [module, *sys.argv[3:]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return

    from jp_overlay.runtime_restart import RuntimeRestart
    from jp_overlay.runtime_setup import selected_runtime

    if target := selected_runtime(state):
        try:
            restart = RuntimeRestart(state, target)
            while not restart.poll():
                time.sleep(0.1)
            return
        except (OSError, RuntimeError, ValueError) as error:
            os.environ["JP_OVERLAY_STARTUP_NOTICE"] = (
                f"The selected runtime could not start. Using the bundled CPU runtime. {error}"
            )
    elif (state / "data/runtime.json").is_file():
        os.environ["JP_OVERLAY_STARTUP_NOTICE"] = (
            "The saved runtime is unavailable for this app version. Using the bundled CPU "
            "runtime. Open Settings → Acceleration to set it up again."
        )
    from jp_overlay.app import main as app_main

    app_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        from jp_overlay.paths import state_root

        log = state_root() / "logs/startup-error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
        ctypes.windll.user32.MessageBoxW(
            None, f"DanteJP could not start. Details were saved to:\n{log}", "DanteJP", 0x10
        )
        raise SystemExit(1) from None
