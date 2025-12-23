from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.applications.models import JobApplication


class Command(BaseCommand):
    """
    Reassign JobApplication.user for fixture-loaded records.

    Typical use:
      python manage.py assign_fixtures_owner --email you@gmail.com --from-user-id 1

    Notes:
    - loaddata runs with raw=True, so auto_now/auto_now_add won't fire.
    - Fixtures often reference a placeholder user_id (e.g., 1) - this command migrates them.
    """

    help = "Assign fixture-loaded applications to a real user by email."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--email",
            required=True,
            help="Target user email (must exist in DB).",
        )
        parser.add_argument(
            "--from-user-id",
            type=int,
            default=1,
            help="Move applications from this user_id to the target user (default: 1).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Reassign ALL applications (ignores --from-user-id).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many rows would be updated, without changing DB.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email: str = options["email"]
        from_user_id: int = options["from_user_id"]
        reassign_all: bool = options["all"]
        dry_run: bool = options["dry_run"]

        User = get_user_model()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist as exc:
            raise CommandError(f"User with email '{email}' not found.") from exc

        qs = JobApplication.objects.all() if reassign_all else JobApplication.objects.filter(user_id=from_user_id)

        count = qs.count()
        if count == 0:
            self.stdout.write(self.style.WARNING("No applications matched. Nothing to do."))
            return

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would reassign {count} applications to user_id={user.id}."))
            return

        updated = qs.update(user_id=user.id)
        self.stdout.write(self.style.SUCCESS(f"Reassigned {updated} applications to {email} (user_id={user.id})."))
