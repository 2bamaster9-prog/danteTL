"""Qualitative model guidance, separate from runtime availability and benchmark scores."""

from dataclasses import dataclass

from dantetl.i18n import mark

RECOMMENDED_TRANSLATION = "gemma"
MODEL_ORDER = ("gemma", "gemma-e4b", "plamo-2b", "plamo-0.8b", "qwen35-4b", "ocr")
COMPARISON_NOTE = mark("Practical ratings from tests and player feedback; results vary by game.")


@dataclass(frozen=True, slots=True)
class Rating:
    text: str
    tone: str
    detail: str


@dataclass(frozen=True, slots=True)
class ModelAdvice:
    dialogue: Rating
    terms: Rating
    speed: Rating
    memory: Rating
    license: str


GOOD = Rating(
    mark("✓ Good"), "success", mark("Generally useful in testing; occasional errors remain.")
)
MIXED = Rating(mark("~ Mixed"), "warning", mark("Can change meaning or produce awkward phrasing."))
TERMS = Rating(
    mark("✕ Unreliable"),
    "error",
    mark(
        "Player testing found stat errors such as Critical Rate becoming Heart Rate. "
        "Our earlier small synthetic comparison did not expose this weakness."
    ),
)
FAST = Rating(
    mark("✓ Fast"), "success", mark("Responsive on the tested GPU; CPU and busy scenes are slower.")
)
VERY_FAST = Rating(
    mark("✓ Very fast"), "success", mark("Among the quickest options in our local tests.")
)
SLOW = Rating(
    mark("✕ Slow"),
    "error",
    mark("Substantially slower than Gemma with the app's current settings."),
)
LOW = Rating(
    mark("✓ Low"), "success", mark("Lower resource use relative to the other offered models.")
)
MODERATE = Rating(
    mark("~ Moderate"), "warning", mark("Needs working memory in addition to downloaded weights.")
)
HIGH = Rating(
    "! High", "warning", mark("The largest offered model; leave RAM/VRAM available for the game.")
)

ADVICE = {
    "gemma": ModelAdvice(GOOD, GOOD, FAST, MODERATE, "Apache-2.0 · Google QAT Q4_0"),
    "gemma-e4b": ModelAdvice(GOOD, GOOD, FAST, HIGH, "Apache-2.0 · Google QAT Q4_0"),
    "plamo-2b": ModelAdvice(GOOD, TERMS, FAST, MODERATE, "PLaMo Community License · Q4_K_M"),
    "plamo-0.8b": ModelAdvice(MIXED, TERMS, VERY_FAST, LOW, "PLaMo Community License · Q4_K_M"),
    "qwen35-4b": ModelAdvice(GOOD, GOOD, SLOW, MODERATE, "Apache-2.0 · Unsloth Q4_K_M"),
}
