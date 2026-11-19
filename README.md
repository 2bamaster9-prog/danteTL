# DanteJP

DanteJP reads Japanese text from a selected Windows game and displays translations in a click-through
overlay. Choose from 18 output languages in **Translation → Output language** or **Settings →
Appearance**, including Portuguese (Portugal), Portuguese (Brazil), Korean, and both Chinese scripts.
If an assigned model lacks the selected language, the warning beside the selector offers a switch
to Gemma or opens its setup page. Text recognition (OCR) runs on your PC. Translation can
use a local model or a supported cloud provider.

## Get started

For Windows x64. Windows 11 is the current validation target; use windowed or borderless fullscreen.

1. Extract **DanteJP-windows-x64.zip** and open **DanteJP.exe**. Keep the `_internal` folder beside
   the EXE. The standalone app needs no separate Python installation.
2. Follow the **Setup assistant** to choose and download a local translator, or skip it and
   configure a cloud model under **Settings → Models**. Downloads require your confirmation.
3. Select your translator in the main window, choose the game window, and click **Start capture**.
   Return to the game to see the overlay. Models load in the background; first use may ask you to
   prepare a local model before continuing.

**MeikiOCR is included** in the standalone app and works on CPU immediately. Translation weights
are separate downloads. Reopen **Settings → Setup assistant…** with capture stopped, or manage
models directly in **Settings → Models**.

## Choose a translator

Use one model for everything, or enable **Advanced routing** to assign different models to
**Short labels** and **Long text & dialogue**. You can mix local and cloud models or turn either
category off. Two local models can use substantially more memory.

### Local models

Start with **Gemma 4 E2B**. These are practical recommendations from testing and player feedback;
quality and speed vary by game and hardware.

| Model | Approx. download | Recommendation / tradeoff |
| --- | --- | --- |
| **Gemma 4 E2B** | 3.35 GB | Recommended balance of game terminology, quality and speed. |
| **Gemma 4 E4B** | 5.15 GB | Higher-resource alternative with good game terminology; needs more memory. |
| PLaMo 3 Translate 2B | 1.81 GB | Fast dialogue alternative; less reliable for game stats and terminology. |
| PLaMo 3 Translate 0.8B | 0.57 GB | Small, fast option; weaker wording and game terminology. |
| Qwen3.5 4B | 2.74 GB | Useful alternative, but substantially slower in this app's tests. |

Download sizes are **not RAM/VRAM requirements**: leave additional memory for inference and the
game. Model downloads have their own license terms.

CPU support is included in the standalone app. **Settings → Acceleration** offers optional NVIDIA
CUDA acceleration for supported OCR/translation engines, or Vulkan acceleration for translation
with CPU OCR. Follow setup's restart prompt when installing a runtime. GPU compatibility depends
on your hardware and drivers; downloaded weights alone do not mean GPU support is installed.
Local translation works offline after setup.

### Cloud models

Cloud translation needs an internet connection and a configured provider connection, but no local
translation weights or GPU setup.

| Provider | Recommended model |
| --- | --- |
| ChatGPT / OpenAI | [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| Gemini | [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) |
| DeepSeek | [DeepSeek Flash](https://api-docs.deepseek.com/quick_start/pricing/) |
| Claude | [Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/overview) |

These recommendations are **as of writing, 17 November 2026**. Models may have been updated or
replaced since; choose a current equivalent in the same speed/cost tier. They are starting points,
not a guarantee of translation quality. Use **Refresh models** to see your provider's current list.

In **Settings → Models**, set **Model type** to **Cloud translation**, then choose **Add cloud
model…**. Sign in with ChatGPT or enter the provider's API key, choose a model, and save. Select the
saved model in the main window to use it. **Test connection** sends a sample request and may use
paid allowance.

ChatGPT sign-in depends on your account's access and available models. API-key connections use
separate API billing, not your chat subscription. Cloud requests consume provider allowance and
may incur charges; DanteJP's request limits are not spending caps.

Screenshots and OCR stay on your PC. Cloud translation sends recognized text, the game-name hint,
and limited recent dialogue context to the selected provider.

## Everyday controls

| Default shortcut | Action |
| --- | --- |
| **Ctrl+Alt+F8** | Show or hide the overlay while processing continues. |
| **Ctrl+Alt+F9** | Start capture of the focused window, or stop the current capture. |
| **Hold Ctrl+Alt+F10** | Show the original text until released. |

Change shortcuts in **Settings → Hotkeys**. The main **Start capture** button uses the selected
window; the capture shortcut uses the focused window by default.

- **Settings → Appearance** adjusts text size and background opacity.
- **Settings → Experimental → Blur behind translated text** tries a clear Windows backdrop behind
  each translation, including labels in dense menus.
- **Inspection and diagnostics** shows the recognized Japanese and full translations.
  Pause it to review or copy text while the game overlay continues updating.
- **Settings → Experimental → Dialogue history** enables the optional reader. It is **off by
  default**. Once enabled, open **Dialogue** beside the Settings gear to read recent turns.
  DanteJP remembers your opt-in. The reader can still misidentify dialogue or speakers. Cloud
  classifiers make additional requests using your provider allowance.
- To record or share the translated view, use display/entire-screen capture; game-only capture
  may omit the separate overlay. Keep **Include in screen capture** enabled.

## Updates and limitations

Close the app and extract an update into a new folder. Standalone models, settings, caches and
optional runtimes live in **`%LOCALAPPDATA%\DanteJP`** and are reused across updates. Compatible
runtimes do not need setup again for an app-only update. If GPU startup fails, launch
`DanteJP.exe --cpu` to use the bundled CPU environment.

Tiny text, unusual fonts, names, dialogue choices and dense layouts can produce recognition or
translation errors. Check the inspector when a result looks wrong. Exclusive fullscreen, protected windows, HDR and individual game or
anti-cheat compatibility are not guaranteed.

## From source and contributing

For a source checkout, **Run DanteJP.cmd** sets up and launches the app. Initial setup needs uv
(or Python to bootstrap it) and C++ Build Tools for the CPU language-model engine. Source runs
keep models and data in the project folder and do not bundle OCR weights; use the setup assistant
to download them.

The Python package and CLI are both `dantejp` (`python -m dantejp` or `uv run dantejp` after setup).

See the [engineering guide](engineering/README.md) for development guidance,
[verification](engineering/verification.md) for checks, and [building](engineering/building.md)
for dependencies, standalone builds and GitHub releases.
