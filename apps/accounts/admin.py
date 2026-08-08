from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db.models import F, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone


class ActiveUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "date_joined",
        "last_login",
        "tokens_30d_input",
        "tokens_30d_output",
        "tokens_30d_total",
    )
    list_filter = ("is_staff", "is_superuser", "date_joined", "last_login")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)

    def get_queryset(self, request):
        since = timezone.now() - timedelta(days=30)
        usage_filter = Q(gmail_openai_token_usage__created_at__gte=since)
        return (
            super()
            .get_queryset(request)
            .filter(is_active=True)
            .annotate(
                tokens_30d_input_value=Coalesce(
                    Sum("gmail_openai_token_usage__input_tokens", filter=usage_filter),
                    Value(0),
                    output_field=IntegerField(),
                ),
                tokens_30d_output_value=Coalesce(
                    Sum("gmail_openai_token_usage__output_tokens", filter=usage_filter),
                    Value(0),
                    output_field=IntegerField(),
                ),
            )
            .annotate(
                tokens_30d_total_value=F("tokens_30d_input_value") + F("tokens_30d_output_value")
            )
        )

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
