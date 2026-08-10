from __future__ import annotations

import json

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.applications.models import JobApplication


@pytest.mark.django_db
@override_settings(APPLICATION_BULK_DELETE_MAX_IDS=2)
def test_bulk_delete_rejects_excessive_selection(client, django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    applications = [
        JobApplication.objects.create(user=user, company=f"Company {index}", title="Developer")
        for index in range(3)
    ]
    client.force_login(user)

    response = client.post(
        reverse("applications:bulk_delete"),
        data=json.dumps({"ids": [application.pk for application in applications]}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert JobApplication.objects.filter(user=user).count() == 3
