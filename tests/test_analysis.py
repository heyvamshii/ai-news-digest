from dataclasses import replace

import pytest

from digest import analysis
from tests.conftest import FakeModel, make_article

pytestmark = pytest.mark.unit


def test_offline_rules_categorise_by_keywords():
    assert analysis.offline_category(make_article(1, source="arXiv cs.AI")) == "Research"
    assert analysis.offline_category(make_article(1, title="Startup raises $50 million")) == "Business"
    assert analysis.offline_category(make_article(1, title="EU passes AI law")) == "Policy"
    assert analysis.offline_category(make_article(1, title="Meta releases Llama 5")) == "Models"
    assert analysis.offline_category(make_article(1, title="A handy coding assistant", snippet="")) == "Tools"


def test_offline_importance_uses_source_weight():
    assert analysis.offline_importance(make_article(1, source="OpenAI", title="New GPT model")) == 10
    assert analysis.offline_importance(make_article(1, source="Unknown", title="x", snippet="")) == 5


def test_offline_summary_takes_two_unique_sentences():
    text = "First point. First point. Second point! Third point?"
    assert analysis.offline_summary(text) == "First point. Second point!"
    assert analysis.offline_summary("   ") == ""


def test_triage_uses_model_and_cleans_its_answers(fake_model):
    articles = [make_article(i) for i in range(3)]
    rated = analysis.triage(articles, fake_model, batch_size=2)
    assert [a.category for a in rated] == ["Models"] * 3          # lower-case 'models' accepted
    assert [a.importance for a in rated] == [10, 10, 9]           # 11 clamped to 10
    assert len(fake_model.calls) == 2                             # batched


def test_triage_skips_already_rated_articles(fake_model):
    done = make_article(1, category="Policy", importance=3)
    rated = analysis.triage([done, make_article(2)], fake_model, batch_size=20)
    assert rated[0] is done
    assert rated[1].category == "Models"


def test_triage_falls_back_to_keyword_rules_when_model_fails():
    errors = []
    rated = analysis.triage([make_article(1, title="Startup raises $5 million")], FakeModel(fail=True),
                            batch_size=20, on_error=errors.append)
    assert rated[0].category == "Business"
    assert "keyword rules" in errors[0]


def test_triage_fills_gaps_when_model_returns_bad_items():
    class Sloppy:
        name = "sloppy"

        def ask(self, system, user):
            return {"items": [{"id": 0, "category": "Gossip", "importance": "high"}, "junk", {"id": "x"}]}

    [rated] = analysis.triage([make_article(1, title="EU AI law passes")], Sloppy(), batch_size=20)
    assert (rated.category, rated.importance) == ("Policy", 7)


def test_triage_without_model_is_fully_offline():
    [rated] = analysis.triage([make_article(1)], None, batch_size=20)
    assert rated.category and rated.importance


def test_select_ranks_by_importance_and_limits_each_source():
    articles = [make_article(i, source="Same", importance=10 - i, category="Models") for i in range(4)]
    articles.append(make_article(9, source="Other", importance=1, category="Tools"))
    top, also = analysis.select(articles, top_count=3, also_count=5)
    assert [a.url[-1] for a in top] == ["0", "1", "9"]            # max 2 per source in top stories
    assert {a.url for a in also}.isdisjoint({a.url for a in top})


def test_summarise_uses_model_output(fake_model):
    top = [make_article(1), make_article(2)]
    summarised, overview = analysis.summarise(top, ["text one.", "text two."], fake_model)
    assert [a.summary for a in summarised] == ["AI summary 0.", "AI summary 1."]
    assert overview == ["Big day for open models.", "Regulators move."]   # blank bullet dropped


def test_summarise_falls_back_to_article_text_and_titles():
    top = [make_article(1)]
    errors = []
    summarised, overview = analysis.summarise(top, ["Opening line. Second line. Third."], FakeModel(fail=True),
                                              on_error=errors.append)
    assert summarised[0].summary == "Opening line. Second line."
    assert overview == [top[0].title]
    assert errors


def test_summarise_uses_title_when_there_is_no_text():
    [only], _ = analysis.summarise([make_article(1)], [""], None)
    assert only.summary == only.title


def test_summarise_with_nothing_to_do():
    assert analysis.summarise([], [], FakeModel()) == ([], [])


def test_articles_are_never_mutated(fake_model):
    original = make_article(1)
    analysis.triage([original], fake_model, batch_size=20)
    assert original.category is None and replace(original) == original
