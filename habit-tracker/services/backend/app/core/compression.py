# [review:need-review] 309
# summary: gzip for every answer over a kilobyte when the client accepts it, except text/event-stream, which Starlette 0.27 would hold in the zlib buffer instead of sending event by event
"""
Сжатие ответов.

Телефон ходит на сервер по Tailscale, и год графика категории весил 1,5 МБ
JSON; сжатый — 41 КБ. URLSession сам шлёт `Accept-Encoding: gzip` и сам
распаковывает, клиенту ничего менять не надо.

**Поток событий не сжимается.** `GZipResponder` из Starlette 0.27 пишет каждый
кусок потока в `GzipFile` без `flush`: мелкое событие SSE остаётся в буфере
zlib, и чат получил бы ответ одним куском в конце. Starlette 0.39 сам исключает
`text/event-stream`; до него — этот модуль. Обновить Starlette отдельно нельзя:
FastAPI 0.104 держит его ниже 0.28.
"""

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware, GZipResponder
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Below this an answer is sent as it is: the gzip header and the CPU cost more
# than the bytes saved.
COMPRESS_FROM_BYTES = 1024
# zlib's own default. Level 9 (Starlette's default) took 14 ms on the 1.5 MB
# table for 33 KB; level 6 takes 5 ms for 41 KB — on the one event loop of the
# server the milliseconds matter more than the last 8 KB.
COMPRESS_LEVEL = 6
EVENT_STREAM = "text/event-stream"


class _StreamSafeResponder(GZipResponder):
    async def send_with_gzip(self, message: Message) -> None:
        await super().send_with_gzip(message)
        if message["type"] == "http.response.start":
            content_type = Headers(raw=message["headers"]).get("content-type", "")
            if content_type.startswith(EVENT_STREAM):
                # The parent passes an answer with its own encoding through
                # untouched, start message and every chunk as they come.
                self.content_encoding_set = True


class StreamSafeGZipMiddleware(GZipMiddleware):
    """`GZipMiddleware` that leaves a `text/event-stream` answer uncompressed."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(
            app, minimum_size=COMPRESS_FROM_BYTES, compresslevel=COMPRESS_LEVEL
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "gzip" in Headers(scope=scope).get(
            "Accept-Encoding", ""
        ):
            responder = _StreamSafeResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )
            await responder(scope, receive, send)
            return
        await self.app(scope, receive, send)
