"""Desktop startup, selected runtime handoff and internal helper dispatch."""

import ctypes
import os
import runpy
import sys
import time
import traceback

from dantejp.paths import state_root


def main() -> None:
    if sys.argv[1:2] == ["--module"]:
        module = sys.argv[2]
        if module != "dantejp" and not module.startswith("dantejp."):
            raise ValueError("Only DanteJP modules may be launched by this entry point.")
        sys.argv = [module, *sys.argv[3:]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return

    from dantejp.runtime.restart import RuntimeRestart
    from dantejp.runtime.setup import selected_runtime

    state = state_root()
    force_cpu = "--cpu" in sys.argv[1:]
    if force_cpu:
        sys.argv.remove("--cpu")
    if not force_cpu:
        if target := selected_runtime(state):
            try:
                restart = RuntimeRestart(state, target)
                while not restart.poll():
                    time.sleep(0.1)
                return
            except (OSError, RuntimeError, ValueError) as error:
                os.environ["DANTEJP_STARTUP_NOTICE"] = (
                    f"The selected runtime could not start. Using CPU fallback. {error}"
                )
        elif (state / "data/runtime.json").is_file():
            os.environ["DANTEJP_STARTUP_NOTICE"] = (
                "The saved runtime is unavailable for this app version. Using CPU fallback. "
                "Open Settings → Acceleration to set it up again."
            )
    from dantejp.bootstrap import main as app_main

    app_main()


def run() -> None:
    helper = sys.argv[1:2] == ["--module"]
    try:
        main()
    except Exception:
        log = state_root() / "logs/startup-error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
        if not helper:
            ctypes.windll.user32.MessageBoxW(
                None, f"DanteJP could not start. Details were saved to:\n{log}", "DanteJP", 0x10
            )
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
