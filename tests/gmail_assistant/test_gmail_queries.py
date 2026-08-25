from apps.gmail_assistant.services.queries import build_candidate_query, build_rejections_query


def test_candidate_query_keeps_promotions_excluded_from_the_broad_scan():
    assert "-category:promotions" in build_candidate_query(7)


def test_rejection_query_includes_transactional_promotions_without_sent_messages():
    query = build_rejections_query(7)

    assert "-category:promotions" not in query
    assert "-category:social" in query
    assert "-from:me" in query
    assert "bedauern" in query
