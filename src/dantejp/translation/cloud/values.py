"""Non-secret provider/model/account values; no I/O or backend factories."""

import re
from dataclasses import dataclass
from uuid import uuid4

from dantejp.i18n import mark, tr

MAX_CLOUD_PROFILES = 16

PROVIDERS = {
    "chatgpt": mark("ChatGPT plan"),
    "openai": mark("OpenAI · API key"),
    "deepseek": mark("DeepSeek · API key"),
    "gemini": mark("Gemini · API key"),
    "claude": mark("Claude · API key"),
}

MODELS = {
    "openai": (("gpt-5.4-mini-2026-03-17", "GPT-5.4 mini"), ("gpt-6-luna", "GPT-6 Luna")),
    "deepseek": (("deepseek-flash", "DeepSeek Flash"),),
    "gemini": (
        ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite"),
        ("gemini-3.8-flash", "Gemini 3.8 Flash"),
        ("gemini-4-hydrogen", "Gemini 4 Hydrogen"),
    ),
    "claude": (
        ("claude-haiku-5-5", "Claude Haiku 5.5"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ),
    "chatgpt": (),
}

ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "chatgpt": "https://api.openai.com/v1/responses",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/",
    "claude": "https://api.anthropic.com/v1/messages",
}


@dataclass(frozen=True, slots=True)
class CloudProfile:
    key: str
    name: str
    provider: str
    model: str
    requests_per_minute: int = 120
    request_limit: int = 1000
    account: str = ""
    credential: str = ""
    decoding: str = "preset"
    model_revision: str = ""

    def __post_init__(self) -> None:
        if (
            not all(
                isinstance(value, str)
                for value in (
                    self.key,
                    self.name,
                    self.provider,
                    self.model,
                    self.account,
                    self.credential,
                    self.decoding,
                    self.model_revision,
                )
            )
            or type(self.requests_per_minute) is not int
            or type(self.request_limit) is not int
        ):
            raise ValueError(tr("Invalid cloud model settings."))
        if not re.fullmatch(r"cloud-[0-9a-f]{32}", self.key):
            raise ValueError(tr("Invalid cloud profile ID."))
        if not self.name.strip() or len(self.name) > 80:
            raise ValueError(tr("Choose a name of at most 80 characters."))
        if self.credential and not re.fullmatch(r"(?:api|cloud)-[0-9a-f]{32}", self.credential):
            raise ValueError(tr("Invalid API connection ID."))
        if self.provider == "chatgpt":
            if self.credential:
                raise ValueError(tr("ChatGPT plan models cannot use API credentials."))
            if not re.fullmatch(r"account-[0-9a-f]{32}", self.account) or not re.fullmatch(
                r"[A-Za-z0-9._:-]{1,120}", self.model
            ):
                raise ValueError(tr("Sign in to ChatGPT and choose an account model first."))
        elif self.provider not in PROVIDERS or not re.fullmatch(
            r"[A-Za-z0-9._:-]{1,120}", self.model
        ):
            raise ValueError(tr("Choose a supported provider and model."))
        allowed = {
            "chatgpt": ("preset",),
            "openai": ("preset", "default"),
            "deepseek": ("preset", "default"),
            "gemini": ("preset", "default", "gemini-no-thinking"),
            "claude": (
                "preset",
                "default",
                "claude-disabled-low",
                "claude-between-low",
                "claude-adaptive-low",
                "claude-disabled",
                "claude-between",
            ),
        }
        if self.decoding not in allowed[self.provider] or len(self.model_revision) > 120:
            raise ValueError(tr("Unsupported cloud request settings."))
        if (
            self.provider != "chatgpt"
            and self.decoding == "preset"
            and self.model not in dict(MODELS[self.provider])
        ):
            raise ValueError(tr("Refresh models to configure this model's request settings."))
        if not 10 <= self.requests_per_minute <= 600 or not 1 <= self.request_limit <= 100_000:
            raise ValueError(tr("Cloud request limits are out of range."))

    @classmethod
    def new(cls, provider: str) -> "CloudProfile":
        if not MODELS.get(provider):
            raise ValueError(tr("Choose an account model after signing in to ChatGPT."))
        model, label = MODELS[provider][0]
        return cls("cloud-" + uuid4().hex, label, provider, model)

    @property
    def credential_key(self) -> str:
        return self.credential or self.key


@dataclass(frozen=True, slots=True)
class ApiConnection:
    key: str
    provider: str
    name: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.key, str)
            or not re.fullmatch(r"(?:api|cloud)-[0-9a-f]{32}", self.key)
            or self.provider not in PROVIDERS
            or self.provider == "chatgpt"
            or not isinstance(self.name, str)
            or not self.name.strip()
            or len(self.name) > 90
        ):
            raise ValueError(tr("Invalid API connection settings."))


@dataclass(frozen=True, slots=True)
class ChatGPTAccount:
    key: str
    label: str
    enabled: bool
    models: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogModel:
    model: str
    label: str
    decoding: str = "default"
    revision: str = ""
    lifecycle: str = "active"

    def profile(self, provider: str) -> CloudProfile:
        return CloudProfile(
            "cloud-" + "0" * 32,
            self.label[:80],
            provider,
            self.model,
            decoding=self.decoding,
            model_revision=self.revision,
        )


def recommended(provider: str) -> tuple[CatalogModel, ...]:
    return tuple(CatalogModel(key, label, "preset") for key, label in MODELS.get(provider, ()))


@dataclass(frozen=True, slots=True)
class CloudUsage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


USAGE_URL = "https://chatgpt.com/settings/usage"
