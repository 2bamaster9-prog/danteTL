"""Application copy. English remains available before desktop startup and in workers."""

from collections.abc import Callable

# English source strings and the locales for which we ship Qt catalogs, in picker order.
INTERFACE_LANGUAGES = (
    "en",
    "bn",
    "de",
    "ja",
    "ar",
    "pt-PT",
    "es",
)


def mark(source: str) -> str:
    """Mark immutable metadata for translation when presented."""
    return source


_lookup: Callable[[str], str] = mark


def install_lookup(lookup: Callable[[str], str]) -> None:
    global _lookup
    _lookup = lookup


class CatalogText(str):
    """A snapshot label that can be rendered again without repeating the worker's operation."""

    source: str
    fields: dict[str, str | int | float]
    suffix: str

    def __new__(
        cls, source: str, /, *, suffix: str = "", **fields: str | int | float
    ) -> "CatalogText":
        value = super().__new__(cls, tr(source, **fields) + display(suffix))
        value.source, value.fields, value.suffix = source, fields, suffix
        return value


def display(value: str) -> str:
    if isinstance(value, CatalogText):
        return tr(value.source, **value.fields) + display(value.suffix)
    return value


def tr(source: str, /, **fields: object) -> str:
    message = display(source) if isinstance(source, CatalogText) else _lookup(source)
    if not fields:
        return message
    return message.format(
        **{k: display(v) if isinstance(v, CatalogText) else v for k, v in fields.items()}
    )
