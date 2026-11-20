"""Application-owned cloud accounts, backend recipes and bounded setup work.

Commands and result adoption are serialized by the application driver. Credential,
catalog and network work runs on the single setup worker; backend creation runs on
the translation owner. Neither path retains a view.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from dantetl.i18n import tr
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.languages.target import ENGLISH
from dantetl.translation.cloud.api_connections import ApiConnections
from dantetl.translation.cloud.auth_work import AuthWork
from dantetl.translation.cloud.backend import CloudAllowance, CloudBackend
from dantetl.translation.cloud.catalog import CatalogCache, fetch_models
from dantetl.translation.cloud.chatgpt_auth import PLAN_SCOPE, ChatGPTConnections
from dantetl.translation.cloud.credentials import Secrets
from dantetl.translation.cloud.profiles import CloudProfiles
from dantetl.translation.cloud.state import CloudDraft, CloudSnapshot
from dantetl.translation.cloud.values import (
    ApiConnection,
    CatalogModel,
    ChatGPTAccount,
    CloudProfile,
    CloudUsage,
)


@dataclass(frozen=True)
class SetupResult:
    profiles: tuple[CloudProfile, ...]
    available: set[str]
    accounts: tuple[ChatGPTAccount, ...]
    api: tuple[ApiConnection, ...]
    api_ready: set[str]
    message: str
    failed: bool
    catalogs: dict[str, tuple[CatalogModel, ...]] = field(default_factory=dict)
    discovered: tuple[CatalogModel, ...] | None = None
    changed_credentials: frozenset[tuple[str, str]] = frozenset()
    discovery_problem: str = ""


class CloudServices:
    def __init__(
        self,
        catalog: CloudProfiles,
        secrets: Callable[[], Secrets],
        connections: ChatGPTConnections,
        *,
        on_change: Callable[[], None] = lambda: None,
        language: SourceLanguage = DEFAULT_SOURCE,
    ) -> None:
        self.language = language
        self.test_target = ENGLISH
        self.catalog = catalog
        self.api_connections = ApiConnections(self.catalog)
        self.catalog_cache = CatalogCache(self.catalog.path.parent / "cloud-catalogs")
        self._catalogs: dict[str, tuple[CatalogModel, ...]] = {}
        self._discovered: tuple[CatalogModel, ...] | None = None
        self.api_accounts: tuple[ApiConnection, ...] = ()
        self._api_ready: set[str] = set()
        self._secrets = secrets
        self.connections = connections
        self.accounts: tuple[ChatGPTAccount, ...] = ()
        self._new_account = ""
        self._welcome = ""
        self._select_after = ""
        self.revision = 0
        self._credential_revisions: dict[tuple[str, str], int] = {}
        self._credential_changes: set[tuple[str, str]] = set()
        self._mutating = False
        self._saving = False
        self.profiles: tuple[CloudProfile, ...] = ()
        self._available: set[str] = set()
        self._allowances: dict[str, CloudAllowance] = {}
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._result: SetupResult | None = None
        self._testing: CloudBackend | None = None
        self._cancelled = threading.Event()
        self.problem = ""

        self._on_change = on_change
        self._version = self._completion = 0
        self._message = ""
        self._selected = ""
        self._saved = False
        self._browser = ""
        self._closed = False

    def start(self) -> None:
        self._run(lambda _: "", tr("Reading cloud settings…"))

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def snapshot(self) -> CloudSnapshot:
        return CloudSnapshot(
            self._version,
            self.revision,
            self.busy,
            self.profiles,
            frozenset(self._available),
            self.accounts,
            self.api_accounts,
            frozenset(self._api_ready),
            tuple(sorted(self._catalogs.items())),
            self._message,
            self.problem,
            self._completion,
            self._mutating,
            self._saved,
            self._selected,
            self._new_account,
            self._discovered,
        )

    def usage(self, key: str) -> CloudUsage:
        return self.allowance(key).snapshot()

    def _changed(self) -> None:
        self._version += 1
        self._on_change()

    def _open_browser(self, url: str) -> None:
        with self._lock:
            if self._closed or self._cancelled.is_set():
                return
            self._browser = url
        self._on_change()

    def take_browser(self) -> str:
        with self._lock:
            url, self._browser = self._browser, ""
        return url

    def take_welcome(self) -> str:
        if self.busy or self._cancelled.is_set():
            return ""
        account, self._welcome = self._welcome, ""
        return account

    def acknowledge_welcome(self, account: str) -> None:
        if account:
            self._run(lambda _: self._mark_welcome(account), tr("Saving account preferences…"))

    def discard_draft(self) -> None:
        with self._lock:
            self._allowances = {
                k: v for k, v in self._allowances.items() if any(p.key == k for p in self.profiles)
            }

    def available(self, key: str) -> bool:
        return key in self._available

    def credential_revision(self, profile: CloudProfile) -> int:
        key = profile.account if profile.provider == "chatgpt" else profile.credential_key
        return self._credential_revisions.get((profile.provider, key), 0)

    def create_backend(
        self, profile: CloudProfile, game: str, language: SourceLanguage
    ) -> CloudBackend:
        return CloudBackend(
            profile,
            "chatgpt-plan"
            if profile.provider == "chatgpt"
            else self.api_connections.secret(profile, self._secrets()),
            game=game,
            language=language,
            allowance=self.allowance(profile.key),
            access_token=(lambda work: self.connections.access_token(profile.account, work))
            if profile.provider == "chatgpt"
            else None,
        )

    def allowance(self, key: str) -> CloudAllowance:
        with self._lock:
            return self._allowances.setdefault(key, CloudAllowance())

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            if self._testing:
                self._testing.cancel_pending()

    def close(self) -> None:
        self._closed = True
        self.cancel()
        with self._lock:
            self._browser = ""

    def resume(self) -> None:
        assert not self.busy
        self._closed = False

    def _run(
        self,
        operation: Callable[[Secrets], str],
        message: str,
        *,
        mutating: bool = False,
        saving: bool = False,
    ) -> None:
        if self._closed or self._worker is not None:
            return
        self.problem = ""
        self._mutating, self._saving = mutating, saving
        self._cancelled.clear()
        self._discovered = None
        self._message = message
        self._saved = False
        self._new_account = ""
        self._credential_changes = set()
        self._changed()

        def work() -> None:
            failed = False
            try:
                result = operation(self._secrets())
            except Exception as error:
                result = str(error) or tr("Operation cancelled.")
                failed = True
            try:
                completed = self._discover(result, failed)
            except Exception as error:
                completed = SetupResult(
                    self.profiles,
                    set(),
                    (),
                    (),
                    set(),
                    str(error),
                    True,
                    changed_credentials=frozenset(self._credential_changes),
                )
            with self._lock:
                self._result = completed
            self._on_change()

        self._worker = threading.Thread(target=work, name="cloud-setup", daemon=True)
        self._worker.start()

    def _discover(self, message: str, failed: bool) -> SetupResult:
        problems: list[str] = []
        try:
            accounts = self.connections.accounts(problems.append)
        except (OSError, ValueError):
            problems.append(tr("Invalid ChatGPT connection record."))
            accounts = ()
        inventory = self.api_connections.discover(self._secrets, problems.append)
        profiles, api, api_ready = inventory.profiles, inventory.connections, set(inventory.ready)
        account_models = {(a.key, model) for a in accounts if a.enabled for model, _ in a.models}
        ready = {(c.provider, c.key) for c in api if c.key in api_ready}
        available = {
            p.key
            for p in profiles
            if (
                (p.account, p.model) in account_models
                if p.provider == "chatgpt"
                else (p.provider, p.credential_key) in ready
            )
        }
        return SetupResult(
            profiles,
            available,
            accounts,
            api,
            api_ready,
            message,
            failed,
            {
                c.key: models
                for c in api
                if (models := self.catalog_cache.read(c.provider, c.key)) is not None
            },
            self._discovered,
            frozenset(self._credential_changes),
            " ".join(dict.fromkeys(problems)),
        )

    def advance(self) -> bool:
        """Adopt a completed operation, even when every view is hidden or destroyed."""
        if not self._worker or self._worker.is_alive():
            return False
        with self._lock:
            result, self._result = self._result, None
        self._worker = None
        if result is None:
            return False
        before = (self.profiles, self._available)
        self.profiles, self._available, self.accounts = (
            result.profiles,
            result.available,
            result.accounts,
        )
        self.api_accounts, self._api_ready = result.api, result.api_ready
        self._catalogs, self._discovered = result.catalogs, result.discovered
        changed = before != (self.profiles, self._available) or (
            self._mutating and not result.failed
        )
        if self._mutating and not result.failed:
            self.revision += 1
        # A credential operation can change durable state before a later discovery
        # step fails. Revoke that connection's old worker identity in either case.
        if result.changed_credentials:
            self.revision += int(result.failed)
            for key in result.changed_credentials:
                self._credential_revisions[key] = self.revision
        referenced = {
            (p.provider, p.account if p.provider == "chatgpt" else p.credential_key)
            for p in self.profiles
        }
        referenced.update((c.provider, c.key) for c in self.api_accounts)
        referenced.update(("chatgpt", a.key) for a in self.accounts)
        self._credential_revisions = {
            k: v for k, v in self._credential_revisions.items() if k in referenced
        }
        self.problem = " ".join(
            filter(None, (result.message if result.failed else "", result.discovery_problem))
        )
        self._message = " ".join(filter(None, (result.message, result.discovery_problem)))
        self._saved = self._saving and not result.failed
        self._selected, self._select_after = self._select_after, ""
        self._completion += 1
        self._changed()
        return changed

    def save(self, draft: CloudDraft) -> None:
        if self._closed or self.busy:
            return

        def save(secrets: Secrets) -> str:
            if self._cancelled.is_set():
                raise ValueError(tr("Save cancelled."))
            profile = draft.profile
            if profile.provider != "chatgpt":
                previous_secret = (
                    secrets.read(draft.connection) if draft.secret and draft.connection else None
                )
                saved = self.api_connections.save_model(
                    profile, draft.connection, draft.secret, secrets
                )
                if draft.secret and draft.secret != previous_secret:
                    self._credential_changes.add((profile.provider, saved.credential_key))
                if draft.models is not None:
                    try:
                        self.catalog_cache.write(
                            profile.provider, saved.credential_key, draft.models
                        )
                    except (OSError, ValueError):
                        return tr(
                            "Model saved. Catalog cache unavailable; refresh models when needed."
                        )
            else:
                accounts = self.connections.accounts()
                if not any(
                    a.key == profile.account and a.enabled and profile.model in dict(a.models)
                    for a in accounts
                ):
                    raise ValueError(tr("Sign in and choose an available account model first."))
                profiles = self.catalog.read()
                self.catalog.write(tuple(p for p in profiles if p.key != profile.key) + (profile,))
            return tr("Model saved. Select it on the main screen to use it.")

        self._select_after = draft.profile.key
        self._run(save, tr("Saving model securely…"), mutating=True, saving=True)

    def refresh_models(self, draft: CloudDraft) -> None:
        if self._closed or self.busy:
            return

        def refresh(secrets: Secrets) -> str:
            profile = replace(draft.profile, credential=draft.connection)
            key = draft.secret or self.api_connections.secret(profile, secrets)
            models = fetch_models(profile.provider, key, self._cancelled)
            if self._cancelled.is_set():
                return tr("Model refresh cancelled; previous list kept.")
            if draft.connection and not draft.secret:
                self.catalog_cache.write(profile.provider, draft.connection, models)
            self._discovered = models
            return tr(
                "Found {count} models. Selection unchanged; test unfamiliar models before use.",
                count=len(models),
            )

        self._run(refresh, tr("Refreshing provider models…"))

    @property
    def test_sample(self) -> str:
        return "会心率" if self.language == DEFAULT_SOURCE else self.language.warmup_text

    def test(self, draft: CloudDraft) -> None:
        if self._closed or self.busy:
            return
        profile = draft.profile
        target = self.test_target

        def test(secrets: Secrets) -> str:
            if self._cancelled.is_set():
                return tr("Test cancelled.")
            source = (
                replace(profile, credential=draft.connection)
                if profile.provider != "chatgpt"
                else profile
            )
            key = (
                (draft.secret or self.api_connections.secret(source, secrets))
                if profile.provider != "chatgpt"
                else "chatgpt-plan"
            )
            backend = CloudBackend(
                source,
                key,
                language=self.language,
                allowance=self.allowance(profile.key),
                access_token=(lambda work: self.connections.access_token(profile.account, work))
                if profile.provider == "chatgpt"
                else None,
            )
            try:
                with self._lock:
                    self._testing = backend
                if self._cancelled.is_set():
                    return tr("Test cancelled.")
                result = backend.translate((self.test_sample,), target=target)[0]
                return (
                    tr("Test cancelled.")
                    if self._cancelled.is_set()
                    else tr(
                        "✓ Test successful ({name}): {result}", name=tr(target.name), result=result
                    )
                )
            finally:
                backend.close()
                with self._lock:
                    self._testing = None

        self._run(test, tr("Testing this model without saving changes…"))

    def remove(self, profile: CloudProfile) -> None:
        if self._closed or self.busy:
            return

        def remove(_: Secrets) -> str:
            self.catalog.write(tuple(p for p in self.catalog.read() if p.key != profile.key))
            with self._lock:
                self._allowances.pop(profile.key, None)
            return tr("Model removed. Its connection is still saved.")

        self._available.discard(profile.key)
        self._changed()
        self._run(remove, tr("Removing cloud model…"), mutating=True)

    def forget_key(self, key: str) -> None:
        if self._closed or self.busy:
            return
        if not key:
            return
        self._available.difference_update(p.key for p in self.profiles if p.credential_key == key)
        self._changed()

        def forget(secrets: Secrets) -> str:
            self._credential_changes.update(
                (c.provider, key) for c in self.api_accounts if c.key == key
            )
            self.api_connections.forget(key, secrets)
            return tr("Key forgotten on this PC. Revoke it at the provider if no longer needed.")

        self._run(forget, tr("Forgetting saved API key…"), mutating=True)

    def sign_in(self, selected: str) -> None:
        if self._closed or self.busy:
            return

        def sign_in(_: Secrets) -> str:
            key = self.connections.sign_in(selected, self._open_browser, self._cancelled)
            self._credential_changes.add(("chatgpt", key))
            record = self.connections.store.read(key)
            self._new_account = key
            if not record.get("welcomed") and PLAN_SCOPE in record.get("scopes", []):
                self._welcome = key
            return (
                tr("ChatGPT connected. Choose a model and save it.")
                if PLAN_SCOPE in record.get("scopes", [])
                else tr("Signed in, but plan use was not enabled. Sign in again to approve it.")
            )

        self._run(sign_in, tr("Finish sign-in and plan consent in your browser…"), mutating=True)

    def _mark_welcome(self, account: str) -> str:
        with self.connections.store.lock(account):
            record = self.connections.store.read(account)
            self.connections.store.write(account, {**record, "welcomed": True})
        return tr("Choose a ChatGPT model and save it.")

    def sign_out(self, account: str) -> None:
        if self._closed or self.busy:
            return
        if account:
            self._available.difference_update(p.key for p in self.profiles if p.account == account)
            self._changed()

            def sign_out(_: Secrets) -> str:
                self._credential_changes.add(("chatgpt", account))
                return self.connections.sign_out(account, AuthWork(self._cancelled))

            self._run(
                sign_out,
                tr("Signing out…"),
                mutating=True,
            )

    def refresh_account(self, account: str) -> None:
        if self._closed or self.busy:
            return
        if account:

            def refresh(_: Secrets) -> str:
                self._credential_changes.add(("chatgpt", account))
                self.connections.refresh_models(account, AuthWork(self._cancelled))
                return tr("ChatGPT models refreshed.")

            self._run(refresh, tr("Reading available models…"), mutating=True)
