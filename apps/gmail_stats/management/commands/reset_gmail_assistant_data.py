from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.gmail_stats.services.reset import reset_gmail_assistant_data


class Command(BaseCommand):
    help = "Delete cached Gmail Assistant data for one user without deleting applications or Google credentials."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(pk=options["user_id"]).first()
        if user is None:
            raise CommandError(f"User id={options['user_id']} not found")
        result = reset_gmail_assistant_data(user=user)
        self.stdout.write(self.style.SUCCESS(f"Reset Gmail Assistant data: {result}"))
