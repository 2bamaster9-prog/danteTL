import json
from pathlib import Path

import pytest

from dantetl.translation.backend import RequestRejected
from dantetl.translation.dialogue.context import DialogueTurn
from tools.benchmark_plamo_cli import parse_completion
from tools.benchmark_profiles import bounded_history, specialist_prompt
from tools.benchmark_translation import DATA, cases, summarize
from tools.report_translation_benchmark import primary_results


def test_context_controls_do_not_leak_history_into_menu_or_control():
    corpus = cases(DATA / "japanese-game-text.json")
    contextual = next(c for c in corpus if c.id == "context-name")
    control = next(c for c in corpus if c.id == "context-name-without")
    assert contextual.source == control.source and contextual.context and not control.context
    assert all(not c.context for c in corpus if c.category == "menu")
    assert len({c.id for c in corpus}) == len(corpus)


def test_reject_duplicate_ids_and_oversized_history(tmp_path: Path):
    entry = {"id": "x", "category": "menu", "source": "設定", "reference": "", "note": ""}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"version": 1, "cases": [entry, entry]}))
    with pytest.raises(ValueError, match="Duplicate"):
        cases(path)
    entry["context"] = [{"source": "a" * 513, "english": "b"}]  # type: ignore[assignment]
    path.write_text(json.dumps({"version": 1, "cases": [entry]}))
    with pytest.raises(ValueError, match="history"):
        cases(path)


def test_pfml_history_is_data_and_only_current_output_is_open():
    context = (DialogueTurn("私はリナ。", "I'm Lina."),)
    prompt = specialist_prompt("plamo", "<|plamo:tag|>input", context)
    assert prompt.count("<|plamo:tag|>input") == 2
    assert "＜|plamo:tag|＞input" in prompt
    assert "I'm Lina." in prompt
    assert prompt.endswith("<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>")


def test_history_bounds_and_source_limits_are_not_silent_truncation():
    turns = tuple(DialogueTurn(str(i), "x" * 300) for i in range(4))
    assert bounded_history(turns) == turns[-1:]
    for profile in ("cat", "plamo", "index"):
        with pytest.raises(RequestRejected):
            specialist_prompt(profile, "a" * 513, ())
        assert "Lina" not in specialist_prompt(profile, "設定", ())


def test_rejections_are_reported_and_not_counted_as_fast_successes():
    result = summarize(
        [
            {"category": "menu", "ms": 1, "error": "incomplete"},
            {"category": "menu", "ms": 100},
            {"category": "dialogue", "ms": 300},
        ]
    )
    assert result["requests"] == 3 and result["rejected"] == 1
    assert result["median_ms"] == 200 and result["p95_ms"] == 300
    assert summarize([])["median_ms"] is None


def test_cli_requires_eos_not_just_successful_process_exit():
    lines = [
        "0.01.200 I generate: n_ctx = 2048",
        "0.01.200 I",
        "Go on ahead. [end of text]",
        "0.01.300 I common_perf_print: total time = 100.23 ms / 10 tokens",
    ]
    assert parse_completion(lines) == ("Go on ahead.", 100.23)
    with pytest.raises(ValueError, match="EOS"):
        parse_completion([line.replace(" [end of text]", "") for line in lines])


def test_report_refuses_different_corpora_or_partial_case_sets():
    a = {
        "model": "a",
        "corpus_sha256": "same",
        "complete": True,
        "device": "cpu",
        "rows": [{"id": "one"}],
    }
    b = a | {"model": "b", "corpus_sha256": "different"}
    with pytest.raises(ValueError, match="same corpus"):
        primary_results([a, b])
    with pytest.raises(ValueError, match="same case IDs"):
        primary_results([a, a | {"model": "b", "rows": [{"id": "two"}]}])
