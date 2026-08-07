from __future__ import annotations

import pytest

from apps.reports.drive import SCOPE as DRIVE_SCOPE
from apps.reports.views import _fetch_drive_credentials


class FakeOAuthSession:
    def __init__(self, scope: object):
        self.scope = scope
        self.token: dict[str, str] = {}


class FakeFlow:
    def __init__(self, returned_scope: object):
        self.oauth2session = FakeOAuthSession([DRIVE_SCOPE])
        self.oauth2session.token["scope"] = returned_scope
        self.credentials = object()
        self.authorization_response = ""

    def fetch_token(self, *, authorization_response: str):
        self.authorization_response = authorization_response


@pytest.mark.parametrize(
    "returned_scope",
    (
        f"https://www.googleapis.com/auth/gmail.readonly {DRIVE_SCOPE} openid",
        ["https://www.googleapis.com/auth/gmail.readonly", DRIVE_SCOPE, "openid"],
    ),
)
def test_incremental_drive_consent_accepts_previously_granted_scopes(returned_scope):
    flow = FakeFlow(returned_scope)

    credentials = _fetch_drive_credentials(flow, "https://example.test/callback?code=abc")

    assert credentials is flow.credentials
    assert flow.oauth2session.scope is None


def test_incremental_drive_consent_requires_drive_scope():
    flow = FakeFlow("https://www.googleapis.com/auth/gmail.readonly openid")

    with pytest.raises(RuntimeError, match="required Google Drive permission"):
        _fetch_drive_credentials(flow, "https://example.test/callback?code=abc")
