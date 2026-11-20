"""Maintain DanteTL's Qt Linguist catalogs. Network use requires the translate command."""

import argparse
import ast
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import Formatter

from dantetl.i18n import INTERFACE_LANGUAGES

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/dantetl"
TRANSLATIONS = ROOT / "translations"
PACKAGED = SOURCE / "ui/locales"
MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"
# These native controls are used even for locales without a Qt base catalog.
NATIVE_LABELS = {
    "QPlatformTheme": ("OK", "Save", "&Yes", "&No", "Cancel", "Close"),
    "QLineEdit": ("&Undo", "&Redo", "Cu&t", "&Copy", "&Paste", "Delete", "Select All"),
}


def sources() -> list[str]:
    messages = {label.replace("&", "") for labels in NATIVE_LABELS.values() for label in labels}
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"tr", "mark", "CatalogText"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                messages.add(node.args[0].value)
    return sorted(messages)


def read_catalog(code: str) -> dict[str, str]:
    path = TRANSLATIONS / f"{code}.ts"
    if not path.exists():
        return {}
    return {
        message.findtext("source", ""): message.findtext("translation", "")
        for message in ET.parse(path).findall("./context[name='DanteTL']/message")
    }


def write_catalog(code: str, entries: dict[str, str]) -> None:
    root = ET.Element("TS", version="2.1", language=code.replace("-", "_"), sourcelanguage="en")
    context = ET.SubElement(root, "context")
    ET.SubElement(context, "name").text = "DanteTL"
    for source, target in sorted(entries.items()):
        message = ET.SubElement(context, "message")
        ET.SubElement(message, "source").text = source
        ET.SubElement(
            message, "translation", {} if target else {"type": "unfinished"}
        ).text = target
    for name, labels in NATIVE_LABELS.items():
        context = ET.SubElement(root, "context")
        ET.SubElement(context, "name").text = name
        for label in labels:
            message = ET.SubElement(context, "message")
            ET.SubElement(message, "source").text = label
            ET.SubElement(message, "translation").text = entries.get(label.replace("&", ""), "")
    ET.indent(root)
    TRANSLATIONS.mkdir(exist_ok=True)
    path = TRANSLATIONS / f"{code}.ts"
    temporary = path.with_suffix(".tmp")
    ET.ElementTree(root).write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)


def tokens(message: str) -> Counter[str]:
    fields = [
        f"{{{name}!{conversion}:{spec}}}"
        for _, name, spec, conversion in Formatter().parse(message)
        if name is not None
    ]
    literals = re.findall(
        r"%p%|%[vm]|%[A-Z_]+%|DANTETL_[A-Z_]+|https?://[^\s]+|\*\.gguf|</?[^<>]+>|\n",
        message,
    )
    return Counter(fields + literals)


def valid(source: str, target: str) -> bool:
    try:
        return bool(target.strip()) and tokens(source) == tokens(target)
    except ValueError:
        return False


def generate_batch(key: str, code: str, batch: list[str]) -> dict[str, str]:
    prompt = (
        f"Translate DanteTL desktop UI messages for the target locale {code}. "
        "Return a JSON object with exactly the provided numeric keys and translated strings. "
        "Use concise, natural game-localization software terminology. Translate "
        "every message. "
        "Preserve {placeholders} with their format specifiers, HTML tags, %p%, %v, %m, filters, "
        "line breaks, identifiers, brand/model names and symbols. Keep leading/trailing spaces for "
        "fragments. Never add commentary."
    )
    messages = {str(i): text for i, text in enumerate(batch)}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(messages, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "max_tokens": 8192,
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    request.add_unredirected_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    values = json.loads(result["choices"][0]["message"]["content"])
    if not isinstance(values, dict):
        raise ValueError("Expected a translation object")
    accepted = {}
    for index, source in messages.items():
        target = values.get(index)
        if isinstance(target, str):
            prefix = source[: len(source) - len(source.lstrip())]
            suffix = source[len(source.rstrip()) :]
            target = prefix + target.strip() + suffix
            if valid(source, target):
                accepted[source] = target
    return accepted


def translate(code: str, messages: list[str], key: str) -> None:
    entries = read_catalog(code)
    entries = {source: entries.get(source, "") for source in messages}
    missing = [source for source, target in entries.items() if not valid(source, target)]
    for size in (32, 8, 1):
        if not missing:
            break
        for offset in range(0, len(missing), size):
            batch = missing[offset : offset + size]
            for attempt in range(3):
                try:
                    entries.update(generate_batch(key, code, batch))
                    break
                except urllib.error.HTTPError as error:
                    if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                        raise
                except (TimeoutError, urllib.error.URLError, ValueError):
                    if attempt == 2:
                        break
                time.sleep(2**attempt)
            write_catalog(code, entries)
        missing = [source for source, target in entries.items() if not valid(source, target)]
    if missing:
        raise ValueError(f"{code}: {len(missing)} untranslated or invalid messages")
    print(f"{code}: {len(entries)} translations", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("extract", "translate", "compile", "check"))
    parser.add_argument("languages", nargs="*", help="Locale codes (default: all app catalogs)")
    args = parser.parse_args()
    codes = args.languages or [c for c in INTERFACE_LANGUAGES if c != "en"]
    if any(c not in INTERFACE_LANGUAGES or c == "en" for c in codes):
        parser.error("Unknown translation locale")
    messages = sources()
    if args.action == "extract":
        for code in codes:
            existing = read_catalog(code)
            write_catalog(code, {s: existing.get(s, "") for s in messages})
        print(f"{len(messages)} English messages")
        return
    if args.action == "translate":
        key = os.environ.get("DEEPSEEK_API_KEY") or getpass.getpass("DeepSeek API key: ")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda code: translate(code, messages, key), codes))
        return
    for code in codes:
        catalog = read_catalog(code)
        if set(catalog) != set(messages) or not all(valid(s, t) for s, t in catalog.items()):
            raise SystemExit(f"{code}: incomplete or stale catalog")
        if args.action == "compile":
            PACKAGED.mkdir(exist_ok=True)
            executable = shutil.which("pyside6-lrelease", path=str(Path(sys.executable).parent))
            if not executable:
                raise SystemExit("pyside6-lrelease is required")
            subprocess.run(
                [executable, str(TRANSLATIONS / f"{code}.ts"), "-qm", str(PACKAGED / f"{code}.qm")],
                check=True,
            )
        else:
            from PySide6.QtCore import QTranslator

            compiled = QTranslator()
            loaded = compiled.load(str(PACKAGED / f"{code}.qm"))
            app_strings_match = all(
                compiled.translate("DanteTL", source) == target
                for source, target in catalog.items()
            )
            native_strings_match = all(
                compiled.translate(context, label) == catalog[label.replace("&", "")]
                for context, labels in NATIVE_LABELS.items()
                for label in labels
            )
            if not (loaded and app_strings_match and native_strings_match):
                raise SystemExit(f"{code}: run compile to update the packaged catalog")


if __name__ == "__main__":
    main()
