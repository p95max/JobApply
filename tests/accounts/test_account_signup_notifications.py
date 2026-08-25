from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.accounts.signals import notify_admin_about_new_user


@pytest.mark.django_db
@patch("apps.accounts.signals.transaction.on_commit")
@patch("apps.accounts.signals.send_notification_once")
def test_new_user_signup_notifies_admin_with_email(send_notification_mock, on_commit_mock, django_user_model):
    user = django_user_model.objects.create_user(
        username="new-user",
        email="new.user@example.com",
    )
    on_commit_mock.side_effect = lambda callback: callback()

    notify_admin_about_new_user(sender=None, request=None, user=user)

    send_notification_mock.assert_called_once_with(
        event_key=f"new_user:{user.pk}",
        event_type="new_user",
        text=(
            "👤 <b>New JobApply user</b>\n\n"
            "📧 Email: <code>new.user@example.com</code>"
        ),
    )


@pytest.mark.django_db
@patch("apps.accounts.signals.transaction.on_commit")
def test_signup_without_email_does_not_queue_notification(on_commit_mock, django_user_model):
    user = django_user_model.objects.create_user(username="no-email", email="")

    notify_admin_about_new_user(sender=None, request=None, user=user)

    on_commit_mock.assert_not_called()
