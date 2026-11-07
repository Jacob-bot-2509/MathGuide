"""习题词表:分类 key、34 条交叉项与多标签校验。"""
from __future__ import annotations

import pytest

from exercises import taxonomy


def test_category_keys_match_classifier():
    assert taxonomy.CATEGORY_KEYS == (
        "analysis",
        "algebra",
        "geometry",
        "ode",
        "probability",
        "complex",
        "numberTheory",
        "topology",
    )


def test_cross_topic_ids_are_complete_and_unique():
    assert len(taxonomy.CROSS_TOPIC_IDS) == 34
    assert len(set(taxonomy.CROSS_TOPIC_IDS)) == 34
    assert "least-squares" in taxonomy.CROSS_TOPIC_IDS
    assert "fourier-transform" in taxonomy.CROSS_TOPIC_IDS
    assert "parseval" in taxonomy.CROSS_TOPIC_IDS


def test_validate_topics_dedupes_and_keeps_order():
    topics, cross = taxonomy.validate_topics(
        "analysis",
        ["analysis", "ode", "analysis"],
        ["fourier-transform", "fourier-transform"],
    )

    assert topics == ("analysis", "ode")
    assert cross == ("fourier-transform",)


def test_validate_topics_rejects_unknown_category():
    with pytest.raises(taxonomy.TaxonomyError, match="未知 topic"):
        taxonomy.validate_topics("analysis", ["analysis", "astrology"])


def test_validate_topics_rejects_primary_outside_topics():
    with pytest.raises(taxonomy.TaxonomyError, match="primary"):
        taxonomy.validate_topics("analysis", ["algebra"])


def test_validate_topics_rejects_unknown_cross_topic():
    with pytest.raises(taxonomy.TaxonomyError, match="未知 cross topic"):
        taxonomy.validate_topics("analysis", ["analysis"], ["not-a-topic"])


def test_validate_topics_rejects_empty_topics():
    with pytest.raises(taxonomy.TaxonomyError, match="不能为空"):
        taxonomy.validate_topics("analysis", [])
