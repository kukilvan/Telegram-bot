"""Delivery rules, pure: failures of one source and reason in one pass are folded; nothing else is."""

from datetime import datetime

from app.tracker import delivery, failures

T = datetime(2026, 10, 26, 12, 0)


def failure(item, title_id, name, source="TMDb", reason=failures.TIMEOUT, stamp="p1"):
    data = failures.failure_payload(name, source, reason, stamp)
    return delivery.Pending(item, item, failures.SOURCE_FAILED, title_id, data["text"], data, T)


def test_two_failures_with_one_source_reason_and_pass_become_one_unit():
    queue = [failure(1, 1, "Дюна"), failure(2, 2, "Укрытие")]

    (unit,) = delivery.fold(queue, episodes=False)

    assert unit.members == tuple(queue)
    assert unit.single is None
    assert unit.text == failures.message_many("TMDb", failures.TIMEOUT, ["Дюна", "Укрытие"])


def test_one_failure_stays_as_it_is():
    (unit,) = delivery.fold([failure(1, 1, "Дюна")], episodes=False)

    assert unit.single is not None
    assert unit.text == failures.message_one("Дюна", "TMDb", failures.TIMEOUT)


def test_another_source_reason_or_pass_is_not_folded():
    queue = [
        failure(1, 1, "А"),
        failure(2, 2, "Б", source="Shikimori"),
        failure(3, 3, "В", reason=failures.KEY_REJECTED),
        failure(4, 4, "Г", stamp="p2"),
    ]

    assert len(delivery.fold(queue, episodes=False)) == 4


def test_gone_titles_are_never_folded():
    queue = [failure(1, 1, "А", reason=failures.GONE), failure(2, 2, "Б", reason=failures.GONE)]

    assert len(delivery.fold(queue, episodes=False)) == 2


def test_an_old_common_event_is_left_alone():
    old = {"text": "⚠️ TMDb не отвечает.", "source": "TMDb", "titles": ["А", "Б"]}
    queue = [delivery.Pending(1, 1, failures.SOURCE_FAILED, None, old["text"], old, T)] * 2

    assert len(delivery.fold(queue, episodes=False)) == 2


def test_a_folded_unit_stands_at_the_place_of_its_first_member():
    other = delivery.Pending(9, 9, "test", None, "прочее", {}, T)
    queue = [failure(1, 1, "А"), other, failure(2, 2, "Б")]

    units = delivery.fold(queue, episodes=False)

    assert [len(u.members) for u in units] == [2, 1]
