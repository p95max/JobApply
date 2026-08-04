from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.applications.models import ApplicationStatus, JobApplication
from apps.interviews.models import InterviewEvent


@pytest.mark.django_db
def test_dashboard_requires_authentication(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert "/accounts/google/login/" in response.url


@pytest.mark.django_db
def test_dashboard_shows_user_metrics_only(client):
    user = get_user_model().objects.create_user(username="dashboard-user")
    other_user = get_user_model().objects.create_user(username="other-user")
    UserProfile.objects.create(
        user=user,
        google_data_access_consent=True,
        consent_accepted_at=timezone.now(),
    )
    UserProfile.objects.create(
        user=other_user,
        google_data_access_consent=True,
        consent_accepted_at=timezone.now(),
    )
    application = JobApplication.objects.create(
        user=user,
        company="Example GmbH",
        title="Python Developer",
        status=ApplicationStatus.APPLIED,
    )
    JobApplication.objects.create(
        user=other_user,
        company="Hidden GmbH",
        title="Other Role",
        status=ApplicationStatus.APPLIED,
    )
    InterviewEvent.objects.create(
        user=user,
        application=application,
        starts_at=timezone.now() + timedelta(days=2),
    )
    client.force_login(user)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Example GmbH" in content
    assert "Python Developer" in content
    assert "Hidden GmbH" not in content
    assert response.context["active_application_count"] == 1
    assert response.context["upcoming_interview_count"] == 1
