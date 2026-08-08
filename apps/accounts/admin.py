from __future__ import annotations

from datetime import timedelta

from allauth.socialaccount.models import SocialToken
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db.models import Count, Exists, F, IntegerField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.applications.models import JobApplication
from apps.gmail_assistant.usage_models import OpenAITokenUsage


class ActiveUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "telegram_connected",
        "drive_connected",
        "applications_count",
        "tokens_30d_total",
        "tokens_30d_input",
        "tokens_30d_output",
        "date_joined",
        "last_login",
    )
    list_filter = ("is_staff", "is_superuser", "date_joined", "last_login")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)

    def get_queryset(self, request):
        since = timezone.now() - timedelta(days=30)
        usage = (
            OpenAITokenUsage.objects
            .filter(user_id=OuterRef("pk"), created_at__gte=since)
            .values("user_id")
            .annotate(
                input_total=Sum("input_tokens"),
                output_total=Sum("output_tokens"),
            )
        )
        applications = (
            JobApplication.objects
            .filter(user_id=OuterRef("pk"))
            .values("user_id")
            .annotate(total=Count("pk"))
            .values("total")[:1]
        )
        telegram_link_exists = UserProfile.objects.filter(
            user_id=OuterRef("pk"),
            telegram_chat_id__isnull=False,
            telegram_user_id__isnull=False,
        )
        google_token_exists = SocialToken.objects.filter(
            account__user_id=OuterRef("pk"),
            account__provider="google",
        )

        return (
            super()
            .get_queryset(request)
            .filter(is_active=True)
            .annotate(
                tokens_30d_input_value=Coalesce(
                    Subquery(usage.values("input_total")[:1], output_field=IntegerField()),
                    Value(0),
                ),
                tokens_30d_output_value=Coalesce(
                    Subquery(usage.values("output_total")[:1], output_field=IntegerField()),
                    Value(0),
                ),
                applications_count_value=Coalesce(
                    Subquery(applications, output_field=IntegerField()),
                    Value(0),
                ),
                telegram_connected_value=Exists(telegram_link_exists),
                drive_connected_value=Exists(google_token_exists),
            )
            .annotate(
                tokens_30d_total_value=F("tokens_30d_input_value") + F("tokens_30d_output_value")
            )
        )

    @admin.display(description="Telegram", boolean=True, ordering="telegram_connected_value")
    def telegram_connected(self, obj: User) -> bool:
        return obj.telegram_connected_value

    @admin.display(description="Google Drive", boolean=True, ordering="drive_connected_value")
    def drive_connected(self, obj: User) -> bool:
        return obj.drive_connected_value

    @admin.display(description="Applications", ordering="applications_count_value")
    def applications_count(self, obj: User) -> int:
        return obj.applications_count_value

    @admin.display(description="Input tokens · 30d", ordering="tokens_30d_input_value")
    def tokens_30d_input(self, obj: User) -> int:
        return obj.tokens_30d_input_value

    @admin.display(description="Output tokens · 30d", ordering="tokens_30d_output_value")
    def tokens_30d_output(self, obj: User) -> int:
        return obj.tokens_30d_output_value

    @admin.display(description="Total tokens · 30d", ordering="tokens_30d_total_value")
    def tokens_30d_total(self, obj: User) -> int:
        return obj.tokens_30d_total_value


admin.site.unregister(User)
admin.site.register(User, ActiveUserAdmin)
