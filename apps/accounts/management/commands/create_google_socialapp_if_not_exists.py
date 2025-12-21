from __future__ import annotations

import os

from django.core.management.base import BaseCommand
from django.db import transaction

from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site


class Command(BaseCommand):
    help = "Create/update Site and Google SocialApp from env vars (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        secret = os.getenv("GOOGLE_CLIENT_SECRET")
        domain = os.getenv("DJANGO_SITE_DOMAIN", "localhost:8000")
        name = os.getenv("DJANGO_SITE_NAME", "JobApply")

        if not client_id or not secret:
            self.stdout.write("GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET not set; skipping SocialApp.")
            return

        site, _ = Site.objects.get_or_create(id=1, defaults={"domain": domain, "name": name})
        changed = False
        if site.domain != domain:
            site.domain = domain
            changed = True
        if site.name != name:
            site.name = name
            changed = True
        if changed:
            site.save(update_fields=["domain", "name"])
            self.stdout.write(f"Site updated: {site.domain}")

        app = SocialApp.objects.filter(provider="google").first()
        if not app:
            app = SocialApp.objects.create(
                provider="google",
                name="Google",
                client_id=client_id,
                secret=secret,
            )
            app.sites.add(site)
            self.stdout.write("Google SocialApp created.")
            return

        # update existing
        upd = False
        if app.client_id != client_id:
            app.client_id = client_id
            upd = True
        if app.secret != secret:
            app.secret = secret
            upd = True
        if app.name != "Google":
            app.name = "Google"
            upd = True
        if upd:
            app.save()
        app.sites.add(site)
        self.stdout.write("Google SocialApp ensured/updated.")
