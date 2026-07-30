# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: the one writer of the shared transcripts table — every text feature stores its raw input through here
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transcript


async def save_transcript(db: AsyncSession, source: str, text: str) -> Transcript:
    """
    Persist a raw user text once, tagged with the feature that produced it.

    The table is shared by every text feature (see `app/models/transcript.py`),
    so the writer lives here rather than inside whichever feature happened to
    need it first. Each feature owns only its own `source` discriminator.
    """
    transcript = Transcript(source=source, text=text)
    db.add(transcript)
    await db.commit()
    await db.refresh(transcript)
    return transcript
