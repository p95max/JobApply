from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete expired demo user accounts and their related data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=None,
            help="Override demo account TTL in hours.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many demo accounts would be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        ttl_hours = options["hours"]
        if ttl_hours is None:
            ttl_hours = int(getattr(settings, "DEMO_ACCOUNT_TTL_HOURS", 12))
        ttl_hours = max(1, ttl_hours)

        cutoff = timezone.now() - timedelta(hours=ttl_hours)
        queryset = get_user_model().objects.filter(
            userprofile__is_demo_user=True,
            date_joined__lt=cutoff,
        )
        count = queryset.count()

        if options["dry_run"]:
            self.stdout.write(
                f"Would delete {count} demo account(s) older than {ttl_hours} hour(s)."
            )
            return

        if count:
            queryset.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {count} demo account(s) older than {ttl_hours} hour(s)."
            )
        )
