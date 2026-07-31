from __future__ import annotations

import pytest

from apps.gmail_stats.services import credentials


def test_token_refresh_error_does_not_include_provider_response_body(monkeypatch):
    secret = "refresh-token-should-not-appear-in-errors"

    class FailedResponse:
        status_code = 400
        text = secret

    monkeypatch.setattr(credentials.requests, "post", lambda *args, **kwargs: FailedResponse())

    with pytest.raises(RuntimeError) as error:
        credentials._refresh_google_access_token(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        )

    assert "HTTP 400" in str(error.value)
    assert secret not in str(error.value)
