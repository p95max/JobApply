from django.test import override_settings

from apps.site_urls import jobapply_url


@override_settings(DJANGO_SITE_DOMAIN="jobapply.example.test")
def test_jobapply_url_adds_https_and_normalizes_the_path():
    assert jobapply_url("reports/ai-statistics/") == "https://jobapply.example.test/reports/ai-statistics/"
    assert jobapply_url("/applications/") == "https://jobapply.example.test/applications/"


@override_settings(DJANGO_SITE_DOMAIN="https://staging.jobapply.example.test/")
def test_jobapply_url_preserves_an_explicit_scheme():
    assert jobapply_url() == "https://staging.jobapply.example.test/"
