# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: shared FastAPI dependencies — the single LLM-client provider both LLM endpoints (and their tests) hang off
from app.llm.client import LLMClient, resolve_llm_client


def get_llm_client() -> LLMClient | None:
    """
    LLM client dependency; None when no backend is available (the 503 case).

    One function rather than one per endpoint: FastAPI keys an override on the
    function object, so a second copy would mean a test that mocks the model for
    one endpoint still reaches the real backend from another.
    """
    return resolve_llm_client()
