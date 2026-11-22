"""Recreated views observe existing application operations without restarting them."""

import os
from dataclasses import replace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402
from test_setup_ownership import configured  # noqa: E402

from dantetl.runtime.hardware_values import HardwareStatus  # noqa: E402
from dantetl.runtime.setup_values import SetupLane  # noqa: E402
from dantetl.translation.models.values import ImportedModel, ProbeResult  # noqa: E402
from dantetl.ui.model_import_dialog import ModelImportDialog  # noqa: E402
from dantetl.ui.runtime_dialog import RuntimeSetupDialog  # noqa: E402
from dantetl.ui.setup_assistant import SetupAssistant  # noqa: E402


def test_recreated_runtime_view_keeps_active_install_and_cancels_explicitly(app, tmp_path):
    replay = configured(tmp_path)
    try:
        assert replay.setup.install_runtime("cpu")
        for _ in range(2):
            view = RuntimeSetupDialog(replay.setup)
            try:
                view.refresh_view()
                assert view.choice.currentData().key == "cpu"
                assert not view.install.isEnabled() and not view.restart.isEnabled()
                view.hide()
                assert len(replay.operations) == 1
                assert not replay.operations[0].cancelled
            finally:
                shiboken6.delete(view)
        view = RuntimeSetupDialog(replay.setup)
        try:
            view.cancel_operation()
            assert replay.operations[0].cancelled and replay.setup.busy
            replay.operations[0].finish(cancelled=True)
            replay.setup.advance()
            view.refresh_view()
            assert "cancelled" in view.status.text().lower()
            assert not view.restart.isEnabled()
        finally:
            shiboken6.delete(view)
    finally:
        replay.close()


def test_recreated_guide_observes_same_review_and_completion(app, tmp_path):
    replay = configured(tmp_path)
    parent = QWidget()
    try:
        review = replay.setup.review("model", "cpu", HardwareStatus(llama_device="cpu"))
        assert replay.setup.start_review(review.token)
        for _ in range(2):
            view = SetupAssistant(replay.setup, None, parent)
            try:
                assert view.pages.currentIndex() == 4
                assert view.model.currentData() == "model"
                assert view.runtime.currentData().key == "cpu"
                assert not view.next.isEnabled()
                view.hide()
                assert len(replay.operations) == 1 and not replay.operations[0].cancelled
            finally:
                shiboken6.delete(view)
        replay.operations[0].finish()
        replay.setup.advance()
        view = SetupAssistant(replay.setup, None, parent)
        try:
            assert view.pages.currentIndex() == 4 and view.next.isEnabled()
            assert len(replay.operations) == 1
            assert not replay.setup.start_review(review.token)
            completed = []
            view.completed.connect(lambda key, target: completed.append((key, target)))
            view.next.click()
            assert completed == [("model", None)]
            reopened = SetupAssistant(replay.setup, None, parent)
            try:
                assert reopened.pages.currentIndex() == 0
                assert len(replay.operations) == 1
            finally:
                shiboken6.delete(reopened)
        finally:
            shiboken6.delete(view)
    finally:
        shiboken6.delete(parent)
        replay.close()


def test_guide_offers_only_models_it_can_review_and_keeps_imports_elsewhere(app, tmp_path):
    replay = configured(tmp_path)
    parent = QWidget()
    try:
        data = replay.inventory.snapshot().data
        imported = replace(data.files[-1], key="imported:user", name="User GGUF")
        replay.discover(replace(data, files=(*data.files, imported)))
        view = SetupAssistant(replay.setup, None, parent)
        try:
            assert imported in replay.setup.files
            assert [view.model.itemData(i) for i in range(view.model.count())] == ["model"]
            view.hardware_status = HardwareStatus(llama_device="cpu")
            view._show(3)
            assert replay.setup.reviewed and replay.setup.reviewed.model == "model"
            with pytest.raises(ValueError, match="setup guide"):
                replay.setup.review(imported.key, "cpu", view.hardware_status)
            assert not replay.operations
        finally:
            shiboken6.delete(view)
    finally:
        shiboken6.delete(parent)
        replay.close()


def test_recreated_import_preserves_successful_probe_until_registration(app, tmp_path):
    replay = configured(tmp_path)
    try:
        model = ImportedModel(
            "imported:x",
            str(tmp_path / "file.gguf"),
            "Model",
            "hash",
            20,
            "llama",
            "embedded",
            "template",
        )
        assert isinstance(replay.dependencies.probe, Mock)
        replay.dependencies.probe.return_value.result = ProbeResult(
            model, "cpu", (("設定", "Settings", 12),), 20
        )
        assert replay.setup.test_import(model.path, model.profile)
        replay.operations[0].finish()
        replay.setup.advance()
        for _ in range(2):
            view = ModelImportDialog(replay.setup)
            try:
                assert view.file.text() == model.path and view.name.text() == model.name
                assert view.profile.currentData() == model.profile
                assert view.add_button.isEnabled() and "Settings" in view.results.toPlainText()
                assert len(replay.operations) == 1
            finally:
                shiboken6.delete(view)
        assert replay.setup.save_import("Renamed")
        assert not replay.setup.save_import("Duplicate")
        replay.operations[-1].finish()
        replay.setup.advance()
        assert replay.setup.probe_result is None
        assert not replay.setup.job(SetupLane.MODELS).busy
    finally:
        replay.close()
