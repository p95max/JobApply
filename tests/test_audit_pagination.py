from django.test import RequestFactory, override_settings

from apps.gmail_assistant.audit_views import _audit_pagination, _audit_query_parameters


@override_settings(AI_AUDIT_API_MAX_PAGE_SIZE=25)
def test_audit_pagination_uses_one_limit_offset_and_user_contract():
    request = RequestFactory().get("/audit", {"limit": "10", "offset": "2", "user_id": "7"})

    assert _audit_pagination(request).limit == 10
    assert _audit_pagination(request).offset == 2
    assert _audit_pagination(request).user_id == 7
    assert [parameter["name"] for parameter in _audit_query_parameters(include_status=True)] == [
        "status",
        "user_id",
        "limit",
        "offset",
    ]
