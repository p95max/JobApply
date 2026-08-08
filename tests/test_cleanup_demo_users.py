from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.applications.models import JobApplication


@pytest.mark.django_db
def test_cleanup_demo_users_deletes_only_expired_demo_accounts(django_user_model):
    expired_demo = django_user_model.objects.create_user("demo-expired")
    UserProfile.objects.create(user=expired_demo, is_demo_user=True)
    JobApplication.objects.create(user=expired_demo, title="Demo role", company="Demo GmbH")
    django_user_model.objects.filter(pk=expired_demo.pk).update(
        date_joined=timezone.now() - timedelta(hours=25)
    )

    fresh_demo = django_user_model.objects.create_user("demo-fresh")
    UserProfile.objects.create(user=fresh_demo, is_demo_user=True)
    django_user_model.objects.filter(pk=fresh_demo.pk).update(
        date_joined=timezone.now() - timedelta(hours=23)
    )

    real_user = django_user_model.objects.create_user("real", email="real@example.com")
    UserProfile.objects.create(user=real_user, is_demo_user=False)
    django_user_model.objects.filter(pk=real_user.pk).update(
        date_joined=timezone.now() - timedelta(days=30)
    )

    output = StringIO()
    call_command("cleanup_demo_users", hours=24, stdout=output)

    assert not django_user_model.objects.filter(pk=expired_demo.pk).exists()
    assert django_user_model.objects.filter(pk=fresh_demo.pk).exists()
    assert django_user_model.objects.filter(pk=real_user.pk).exists()
    assert "Deleted 1 demo account(s) older than 24 hour(s)." in output.getvalue()


@pytest.mark.django_db
def test_cleanup_demo_users_dry_run_does_not_delete(django_user_model):
    demo = django_user_model.objects.create_user("demo-dry-run")
    UserProfile.objects.create(user=demo, is_demo_user=True)
    django_user_model.objects.filter(pk=demo.pk).update(
        date_joined=timezone.now() - timedelta(days=2)
    )

    output = StringIO()
    call_command("cleanup_demo_users", hours=24, dry_run=True, stdout=output)

    assert django_user_model.objects.filter(pk=demo.pk).exists()
    assert "Would delete 1 demo account(s) older than 24 hour(s)." in output.getvalue()
