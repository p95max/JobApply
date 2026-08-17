from apps.gmail_assistant.services.classifier import classify_event


def test_application_subject_is_not_hidden_by_footer_noise():
    result = classify_event(
        "Ihre Bewerbung - EffiCon GmbH & Co. KG",
        "Leider müssen wir Ihnen jedoch mitteilen, dass wir Ihnen nach Prüfung Ihrer Bewerbung absagen müssen.",
        "Newsletter abbestellen / unsubscribe",
    )

    assert result.is_job_related is True
    assert result.event_type == "rejection"
    assert result.confidence == 92


def test_real_newsletter_still_counts_as_noise():
    result = classify_event(
        "Neue Jobs für dich",
        "Weekly job alert",
        "Newsletter unsubscribe marketing",
    )

    assert result.is_job_related is False
    assert result.event_type == "noise"
