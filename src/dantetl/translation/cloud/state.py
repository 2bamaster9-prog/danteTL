"""Immutable cloud command and presentation values; no credentials or services in snapshots."""

from dataclasses import dataclass, field

from dantetl.translation.cloud.values import (
    ApiConnection,
    CatalogModel,
    ChatGPTAccount,
    CloudProfile,
)


@dataclass(frozen=True)
class CloudDraft:
    profile: CloudProfile
    connection: str
    secret: str = field(repr=False)
    models: tuple[CatalogModel, ...] | None = None


@dataclass(frozen=True)
class CloudSnapshot:
    version: int
    revision: int
    busy: bool
    profiles: tuple[CloudProfile, ...]
    available: frozenset[str]
    accounts: tuple[ChatGPTAccount, ...]
    api: tuple[ApiConnection, ...]
    api_ready: frozenset[str]
    catalogs: tuple[tuple[str, tuple[CatalogModel, ...]], ...]
    message: str
    problem: str
    completion: int
    mutating: bool
    saved: bool
    selected: str
    new_account: str
    discovered: tuple[CatalogModel, ...] | None
