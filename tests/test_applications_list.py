from __future__ import annotations

import pytest
from django.urls import reverse

from apps.applications.models import ApplicationStatus, JobApplication


@pytest.mark.django_db
def test_application_list_highlights_rows_by_current_status(client, django_user_model):
    user = django_user_model.objects.create_user("applications-user", email="applications@example.com")
    JobApplication.objects.create(
        user=user,
        company="Example GmbH",
        title="Developer",
        status=ApplicationStatus.REJECTED,
    )
    client.force_login(user)

    response = client.get(reverse("applications:list"))

    assert response.status_code == 200
    assert b"apps-table__row--rejected" in response.content
    assert b"application-card--rejected" in response.content
