"""One cancellable, deadline-bound authentication operation, including streamed HTTP."""

import asyncio
import threading
import time

import httpx2

from dantejp.i18n import tr

AUTH_RESPONSE_LIMIT = 128 * 1024


class AuthInterrupted(ValueError):
    """Safe diagnostic; interruption never invalidates saved credentials."""


class AuthWork:
    def __init__(
        self,
        cancelled: threading.Event | None = None,
        *,
        deadline: float | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.cancelled = cancelled if cancelled is not None else threading.Event()
        self.deadline = deadline if deadline is not None else time.monotonic() + 30
        self.transport = transport

    def check(self) -> None:
        if self.cancelled.is_set():
            raise AuthInterrupted(tr("ChatGPT authentication cancelled."))
        if time.monotonic() >= self.deadline:
            raise AuthInterrupted(tr("ChatGPT authentication timed out."))

    def request(
        self, method: str, url: str, *, max_response_bytes: int = AUTH_RESPONSE_LIMIT, **kwargs
    ) -> tuple[int, bytes]:
        """Called on the auth/setup owner. Async I/O allows cancellation during headers/body."""
        self.check()
        return asyncio.run(self._request(method, url, max_response_bytes, **kwargs))

    async def _request(
        self, method: str, url: str, max_response_bytes: int, **kwargs
    ) -> tuple[int, bytes]:
        owner = asyncio.current_task()
        assert owner is not None

        async def watch() -> None:
            while not self.cancelled.is_set():
                await asyncio.sleep(0.025)
            owner.cancel()

        watcher = asyncio.create_task(watch())
        try:
            async with asyncio.timeout(max(0, self.deadline - time.monotonic())):
                async with (
                    httpx2.AsyncClient(
                        timeout=8, follow_redirects=False, trust_env=False, transport=self.transport
                    ) as client,
                    client.stream(method, url, **kwargs) as response,
                ):
                    data = bytearray()
                    # Bound decoded bytes, including compressed/chunked responses without
                    # Content-Length. Catalog metadata needs more room than token responses.
                    async for chunk in response.aiter_bytes(chunk_size=16 * 1024):
                        self.check()
                        if len(data) + len(chunk) > max_response_bytes:
                            raise AuthInterrupted(
                                tr(
                                    "ChatGPT setup response exceeds its size limit "
                                    "({value:,} KiB).",
                                    value=max_response_bytes // 1024,
                                )
                            )
                        data.extend(chunk)
                    self.check()
                    return response.status_code, bytes(data)
        except asyncio.CancelledError:
            raise AuthInterrupted(tr("ChatGPT authentication cancelled.")) from None
        except TimeoutError:
            raise AuthInterrupted(tr("ChatGPT authentication timed out.")) from None
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
