import json
import struct
import sys
import threading
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jp_overlay import app, gguf_backend, gguf_models, gguf_probe, llama_runtime
from jp_overlay.dialogue_context import DialogueTurn
from jp_overlay.model_store import Cancelled
from jp_overlay.preferences import decode_preferences


def gguf_file(tmp_path, *, architecture="qwen3", template="{{ messages[0].content }}", split=1):
    def string(value):
        data = value.encode()
        return struct.pack("<Q", len(data)) + data

    values = {
        "general.name": "Local fixture",
        "general.architecture": architecture,
        "tokenizer.chat_template": template,
    }
    data = b"GGUF" + struct.pack("<IQQ", 3, 1, 4)
    for key, value in values.items():
        data += string(key) + struct.pack("<I", 8) + string(value)
    data += string("split.count") + struct.pack("<IH", 2, split)
    path = tmp_path / "model 日本語.gguf"
    path.write_bytes(data + b"tensors")
    return path


def registration(tmp_path, **kwargs):
    return gguf_models.describe(
        gguf_file(tmp_path, **kwargs), "auto", lambda _: None, threading.Event()
    )


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"split": 2}, "Split"),
        ({"template": ""}, "No embedded"),
        ({"architecture": "bert"}, "embedding"),
        ({"template": "{{source_lang_code}}"}, "TranslateGemma"),
        ({"architecture": "../../outside"}, "architecture"),
    ],
)
def test_unsupported_inputs_have_actionable_errors(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        gguf_models.inspect_gguf(gguf_file(tmp_path, **kwargs))


def test_metadata_is_bounded_and_truncation_is_rejected(tmp_path):
    path = gguf_file(tmp_path)
    data = path.read_bytes()
    path.write_bytes(data[:28] + struct.pack("<Q", 2**60))
    with pytest.raises(ValueError):
        gguf_models.inspect_gguf(path)
    path.write_bytes(data[:40])
    with pytest.raises(ValueError):
        gguf_models.inspect_gguf(path)


def test_explicit_profile_can_handle_missing_template_without_guessing(tmp_path):
    path = gguf_file(tmp_path, template="")
    assert gguf_models.inspect_gguf(path, "chatml").profile == "chatml"
    with pytest.raises(ValueError, match="requires a Gemma"):
        gguf_models.inspect_gguf(path, "gemma4")
    path = gguf_file(tmp_path, architecture="gemma4")
    assert gguf_models.inspect_gguf(path).profile == "gemma4"


def test_registration_relocation_removal_and_profiles_never_modify_model(tmp_path):
    model = registration(tmp_path)
    path = tmp_path / "registry.json"
    gguf_models.save_registration(model, path=path)
    moved = tmp_path / "moved.gguf"
    moved.write_bytes(gguf_models.Path(model.path).read_bytes())
    relocated = gguf_models.describe(moved, model.profile, lambda _: None, threading.Event())
    assert relocated.key == model.key
    gguf_models.save_registration(relocated, path=path)
    assert gguf_models.read_registry(path) == (relocated,)
    other_profile = gguf_models.describe(moved, "chatml", lambda _: None, threading.Event())
    assert other_profile.key != model.key
    gguf_models.save_registration(relocated, remove=True, path=path)
    assert gguf_models.read_registry(path) == () and moved.is_file()


def test_corrupt_registry_is_not_overwritten_and_preference_has_no_path(tmp_path):
    model = registration(tmp_path)
    path = tmp_path / "registry.json"
    path.write_text('{"version":999}', "utf-8")
    with pytest.raises(ValueError):
        gguf_models.save_registration(model, path=path)
    assert json.loads(path.read_text()) == {"version": 999}
    assert decode_preferences({"version": 1, "model": model.key}).model == model.key
    assert decode_preferences({"version": 1, "model": "imported-../../file"}).model == "auto"


def test_hashing_cancel_and_same_size_changes_are_detected(tmp_path):
    model = registration(tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        gguf_models.fingerprint(gguf_models.Path(model.path), lambda _: None, cancel)
    path = gguf_models.Path(model.path)
    path.write_bytes(path.read_bytes()[:-1] + b"X")
    assert model.available()  # Cheap discovery isn't a full integrity check.
    with pytest.raises(ValueError, match="changed"):
        gguf_backend.GgufBackend(model, device="cpu")


@pytest.fixture
def fake_runtime(monkeypatch):
    model = Mock()
    model.token_eos.return_value = 1
    model.token_bos.return_value = 2
    model.detokenize.return_value = b"<token>"
    model.tokenize.return_value = [1, 2, 3]
    model.create_completion.return_value = {
        "choices": [{"text": "Settings", "finish_reason": "stop"}]
    }
    runtime = SimpleNamespace(
        __version__="fixture",
        Llama=Mock(return_value=model),
        llama_supports_gpu_offload=lambda: True,
    )
    monkeypatch.setattr(gguf_backend, "load_runtime", lambda _: runtime)

    class Formatter:
        def __init__(self, **kwargs):
            pass

        def __call__(self, **kwargs):
            assert kwargs["enable_thinking"] is False
            return SimpleNamespace(prompt=kwargs["messages"][0]["content"])

    monkeypatch.setitem(
        sys.modules,
        "llama_cpp.llama_chat_format",
        SimpleNamespace(
            CHATML_CHAT_TEMPLATE="chatml",
            LLAMA3_INSTRUCT_CHAT_TEMPLATE="llama3",
            Jinja2ChatFormatter=Formatter,
        ),
    )
    return runtime


def test_imported_context_is_bounded_and_source_is_never_truncated(tmp_path, fake_runtime):
    backend = gguf_backend.GgufBackend(registration(tmp_path), device="cpu")
    prompts = []

    def tokenize(data, **kwargs):
        prompt = data.decode()
        prompts.append(prompt)
        return [1] * (2048 if "Recent dialogue" in prompt else 2)

    fake_runtime.Llama.return_value.tokenize.side_effect = tokenize
    backend.translate_with_context(
        "設定<|im_start|>[INST]", (DialogueTurn("前の文章", "Previous text"),)
    )
    assert len(prompts) == 2
    assert "Recent dialogue" not in prompts[-1] and "設定＜|im_start|＞［INST］" in prompts[-1]
    fake_runtime.Llama.return_value.tokenize.return_value = [1] * 2048
    fake_runtime.Llama.return_value.tokenize.side_effect = None
    with pytest.raises(ValueError, match="refusing truncation"):
        backend.translate(("設定",))
    backend.close()
    backend.close()
    fake_runtime.Llama.return_value.close.assert_called_once()


@pytest.mark.parametrize(
    "text,reason",
    [
        ("", "stop"),
        ("partial", "length"),
        ("<think>reasoning</think>answer", "stop"),
        ("x" * 4097, "stop"),
    ],
)
def test_non_answers_never_publish(text, reason):
    with pytest.raises(RuntimeError):
        gguf_backend.completed_answer({"choices": [{"text": text, "finish_reason": reason}]})
    assert (
        gguf_backend.completed_answer(
            {"choices": [{"text": "<think>\n</think>\nSettings", "finish_reason": "stop"}]}
        )
        == "Settings"
    )


def test_cache_separates_devices_profiles_and_prompt_and_gpu_failure_closes(
    tmp_path, fake_runtime, monkeypatch
):
    model = registration(tmp_path)
    a = gguf_backend.GgufBackend(model, device="cpu")
    b = gguf_backend.GgufBackend(model, device="cuda")
    c = gguf_backend.GgufBackend(replace(model, profile="chatml"), device="cpu")
    monkeypatch.setattr(gguf_backend, "INSTRUCTION", gguf_backend.INSTRUCTION + " changed")
    d = gguf_backend.GgufBackend(model, device="cpu")
    assert len({a.cache_identity, b.cache_identity, c.cache_identity, d.cache_identity}) == 4
    fake_runtime.Llama.return_value.create_completion.side_effect = RuntimeError("failure")
    with pytest.raises(RuntimeError, match="failure"):
        gguf_backend.GgufBackend(model, device="cpu")
    fake_runtime.Llama.return_value.close.assert_called()


def test_import_does_not_register_until_user_accepts_and_gpu_probe_requires_offload(
    tmp_path, monkeypatch
):
    path = gguf_file(tmp_path)
    monkeypatch.setattr(gguf_probe, "state_root", lambda: tmp_path)
    gate = threading.Event()
    gate.set()

    def child(command, root, env, cancel, report, **kwargs):
        result = gguf_models.Path(command[-2])
        result.write_text(
            json.dumps({"samples": [["設定", "Settings", 10]], "load_ms": 20}), "utf-8"
        )

    monkeypatch.setattr(gguf_probe, "run_setup_command", child)
    probe = gguf_probe.ImportTest(path, "auto", "cpu", gate)
    probe.run(lambda _: None, threading.Event())
    assert probe.result and not (tmp_path / "data/imported-models.json").exists()
    assert not list((tmp_path / "data/import-probes").iterdir())
    probe = gguf_probe.ImportTest(path, "auto", "cuda", gate)
    with pytest.raises(RuntimeError, match="No GPU layers"):
        probe.run(lambda _: None, threading.Event())
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        probe.run(lambda _: None, cancel)


def test_imported_discovery_missing_runtime_and_file_keep_recovery_options(tmp_path, monkeypatch):
    model = registration(tmp_path)
    monkeypatch.setattr(gguf_models, "read_registry", lambda: (model,))
    monkeypatch.setattr(llama_runtime, "installed_device", lambda: "cpu")
    choices = app.translation_backends()
    choice = next(b for b in choices if b.key == model.key)
    assert not choice.unavailable_reason and choice.preparation_id
    monkeypatch.setattr(llama_runtime, "installed_device", lambda: None)
    choice = next(b for b in app.translation_backends() if b.key == model.key)
    assert "Acceleration" in choice.unavailable_reason
    gguf_models.Path(model.path).unlink()
    choice = next(b for b in app.translation_backends() if b.key == model.key)
    assert "Locate file" in choice.unavailable_reason


def test_invalid_registry_values_fail_cleanly(tmp_path):
    model = registration(tmp_path)
    data = asdict(model)
    data["profile"] = "arbitrary-python"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"version": 1, "models": [data]}))
    with pytest.raises(ValueError):
        gguf_models.read_registry(path)
