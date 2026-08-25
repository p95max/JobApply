from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication
from apps.interviews.models import InterviewEvent, InterviewStatus


@pytest.mark.django_db
def test_application_and_interview_forms_use_shared_record_style(client):
    user = get_user_model().objects.create_user(username="record-style-user")
    client.force_login(user)

    application_response = client.get(reverse("applications:create"))
    interview_response = client.get(reverse("interviews:create"))

    assert application_response.status_code == 200
    assert interview_response.status_code == 200
    assert b"record-page" in application_response.content
    assert b"record-form-card" in application_response.content
    assert b"record-page" in interview_response.content
    assert b"record-form-card" in interview_response.content


@pytest.mark.django_db
def test_interview_list_uses_status_rows_and_application_links(client):
    user = get_user_model().objects.create_user(username="interview-style-user")
    application = JobApplication.objects.create(
        user=user,
        company="Example GmbH",
        title="Python Developer",
        status=ApplicationStatus.INTERVIEW,
    )
    InterviewEvent.objects.create(
        user=user,
        application=application,
        status=InterviewStatus.SCHEDULED,
        starts_at=timezone.now(),
    )
    client.force_login(user)

    response = client.get(reverse("interviews:list"))

    assert response.status_code == 200
    assert b"interviews-table__row--scheduled" in response.content
    assert f'href="/applications/{application.pk}/"'.encode() in response.content
