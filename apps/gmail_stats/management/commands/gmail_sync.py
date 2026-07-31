from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from apps.gmail_stats.services.gmail_client import GmailClient
from apps.gmail_assistant.services.sync import sync_gmail_messages_for_user
from apps.gmail_stats.services.credentials import get_google_credentials_for_user


class Command(BaseCommand):
    help = "Sync Gmail messages for statistics (responses/rejections/invites)."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--days", type=int, default=180)
        parser.add_argument("--max", type=int, default=500)

    def handle(self, *args, **opts):
        user_id = opts["user_id"]
        days = opts["days"]
        max_results_each = opts["max"]

        User = get_user_model()
        user = User.objects.filter(id=user_id).first()
        if not user:
            raise CommandError(f"User id={user_id} not found")

        credentials = get_google_credentials_for_user(user)  # you implement
        if not credentials:
            raise CommandError("No Google credentials for this user (missing Gmail scope?)")

        gmail_client = GmailClient(credentials)
        res = sync_gmail_messages_for_user(user=user, gmail_client=gmail_client, days=days, max_results_each=max_results_each)

        self.stdout.write(self.style.SUCCESS(f"OK: {res}"))
