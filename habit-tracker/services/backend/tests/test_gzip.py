"""
Responses are compressed for a client that accepts gzip (#309).

The phone reads the server over Tailscale; a year of the category chart was
1.5 MB of JSON before this. The guard is the class, not one route: every GET
the iOS screens read and that weighs more than a kilobyte must come compressed,
and the text/event-stream of the chat must still arrive event by event.
"""

# [review:need-review] 309
# summary: every GET the iOS screens read comes gzip-compressed when it is over a kilobyte and the client accepts gzip; a smaller answer and a client without gzip get plain JSON; a text/event-stream passes through untouched, chunk for chunk

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from starlette.types import Message, Receive, Scope, Send

from app.core import daytime
from app.core.compression import (
    COMPRESS_FROM_BYTES,
    StreamSafeGZipMiddleware,
)

CATEGORIES = 8
DAYS = 6
PLAIN = {"Accept-Encoding": "identity"}
GZIP = {"Accept-Encoding": "gzip"}


@pytest.fixture
async def history(client: AsyncClient) -> None:
    """Eight counted habits with a button each and six days of entries, one diary page."""
    today = daytime.today_local()
    for index in range(CATEGORIES):
        created = await client.post(
            "/api/v1/categories",
            json={
                "name": f"Привычка {index}",
                "fields": [{"name": "Сколько", "field_type": "number", "order": 1}],
            },
        )
        assert created.status_code == 201
        category = created.json()
        field_id = category["fields"][0]["id"]
        button = await client.post(
            "/api/v1/quick-marks",
            json={
                "label": f"+1 к привычке {index}",
                "category_id": category["id"],
                "field_id": field_id,
                "kind": "increment",
                "step": 1,
            },
        )
        assert button.status_code == 201
        for offset in range(DAYS):
            entry = await client.post(
                "/api/v1/entries",
                json={
                    "category_id": category["id"],
                    "entry_date": str(today - timedelta(days=offset)),
                    "values": [{"field_id": field_id, "value": "3"}],
                },
            )
            assert entry.status_code == 201
    page = await client.post(
        "/api/v1/journal",
        json={"title": "День", "content": "текст дня " * 200, "entry_date": str(today)},
    )
    assert page.status_code == 201


IOS_READS = (
    "/api/v1/categories",
    "/api/v1/entries",
    "/api/v1/table",
    "/api/v1/quick-marks",
    "/api/v1/dashboard/summary",
    "/api/v1/journal",
)


def _params(path: str) -> dict[str, str]:
    """The query each screen sends; the dates are read when the test runs."""
    today = daytime.today_local()
    week_ago = str(today - timedelta(days=DAYS))
    return {
        "/api/v1/entries": {"start_date": week_ago, "end_date": str(today)},
        "/api/v1/table": {"date_from": week_ago, "date_to": str(today)},
        "/api/v1/quick-marks": {"surface": "ios"},
        "/api/v1/dashboard/summary": {"period": "month"},
    }.get(path, {})


def _stable(body: Any) -> Any:
    """The answer without the moment the dashboard insight was worded."""
    if isinstance(body, dict) and isinstance(body.get("insight"), dict):
        body["insight"].pop("generated_at")
    return body


@pytest.mark.parametrize("path", IOS_READS)
@pytest.mark.usefixtures("history")
async def test_a_large_read_comes_compressed_and_says_the_same(
    client: AsyncClient, path: str
) -> None:
    plain = await client.get(path, params=_params(path), headers=PLAIN)
    packed = await client.get(path, params=_params(path), headers=GZIP)

    assert plain.status_code == packed.status_code == 200
    assert len(plain.content) > COMPRESS_FROM_BYTES, "the fixture is too small"
    assert "content-encoding" not in plain.headers
    assert packed.headers["content-encoding"] == "gzip"
    assert int(packed.headers["content-length"]) < len(plain.content)
    # httpx inflates the body; the answer itself is unchanged.
    assert _stable(packed.json()) == _stable(plain.json())


async def test_a_small_answer_is_not_compressed(client: AsyncClient) -> None:
    response = await client.get("/api/v1/categories", headers=GZIP)

    assert len(response.content) < COMPRESS_FROM_BYTES
    assert "content-encoding" not in response.headers


def _streaming_app(content_type: bytes, chunks: list[bytes]) -> Any:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", content_type)],
            }
        )
        for chunk in chunks:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    return app


async def _sent(content_type: bytes, chunks: list[bytes]) -> list[Message]:
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    middleware = StreamSafeGZipMiddleware(_streaming_app(content_type, chunks))
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"accept-encoding", b"gzip")],
    }
    await middleware(scope, receive, send)
    return sent


# Larger than the threshold, so the size is not what keeps them plain.
EVENTS = [b"event: delta\ndata: " + b"x" * COMPRESS_FROM_BYTES + b"\n\n"] * 3


async def test_an_event_stream_passes_through_chunk_for_chunk() -> None:
    sent = await _sent(b"text/event-stream; charset=utf-8", EVENTS)

    start, *bodies = sent
    assert b"content-encoding" not in dict(start["headers"])
    assert [message["body"] for message in bodies] == [*EVENTS, b""]


async def test_another_stream_is_still_compressed() -> None:
    """The control: the same stream as JSON is compressed, so the test above can fail."""
    sent = await _sent(b"application/json", EVENTS)

    start, *bodies = sent
    assert dict(start["headers"])[b"content-encoding"] == b"gzip"
    assert [message["body"] for message in bodies] != [*EVENTS, b""]
