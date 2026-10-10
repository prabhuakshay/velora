from datetime import date
from pkgutil import resolve_name
from typing import TYPE_CHECKING, Any

import pytest
from django.core import mail

from apps.accounts.tests.conftest import make_account
from apps.cards.models import Statement
from apps.cards.tests.conftest import make_card, make_card_emi, record
from apps.classification.models import Party
from apps.digest.models import Digest
from apps.quick_add.models import Draft
from apps.schedules import daily_job
from apps.schedules.daily_job import DailyJobError, run_daily_job
from apps.schedules.matching import match_transactions
from apps.schedules.models import Occurrence
from apps.schedules.occurrences import materialise_occurrences
from apps.schedules.tests.conftest import make_schedule, paid

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_django import Settings

    from apps.schedules.models import Schedule
    from apps.users.models import User

pytestmark = pytest.mark.django_db

BROKEN = "Broken"


def fail_after(
    monkeypatch: pytest.MonkeyPatch, target: str, bad: Callable[[Any], bool]
) -> None:
    """Make the target raise once it has written, for items `bad` picks."""
    original = resolve_name(target)

    def failing(item: Any, *args: Any) -> None:
        original(item, *args)
        if bad(item):
            raise RuntimeError(BROKEN)

    monkeypatch.setattr(target, failing)


def assert_logged(caplog: pytest.LogCaptureFixture, *names: str) -> None:
    [record] = [r for r in caplog.records if r.levelname == "ERROR"]
    assert record.name == "daily_job"
    assert record.exc_info
    for name in names:
        assert name in record.getMessage()


def rent(name: str) -> Schedule:
    bank = make_account(f"{name} bank", "asset")
    return make_schedule(
        (bank, make_account(name, "expense"), "25000"),
        party=Party.objects.create(name=name),
        description=name,
    )


def broken_step(today: date) -> None:
    raise RuntimeError(BROKEN)


def test_a_failed_step_does_not_stop_the_later_steps(
    user: User, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    rent("Flat rent")
    monkeypatch.setattr(
        daily_job,
        "STEPS",
        tuple(
            broken_step if step is match_transactions else step
            for step in daily_job.STEPS
        ),
    )

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 5))

    assert Draft.objects.exists()
    [email] = mail.outbox
    assert email.to == [user.email]
    assert_logged(caplog, "broken_step")


def test_a_failed_step_emails_the_admins(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.ADMINS = ["admin@example.com"]
    monkeypatch.setattr(daily_job, "STEPS", (broken_step,))

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 5))

    [email] = mail.outbox
    assert email.to == ["admin@example.com"]
    assert "broken_step" in email.subject
    assert f"RuntimeError: {BROKEN}" in email.body


def test_failed_items_and_steps_send_one_admin_email(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.ADMINS = ["admin@example.com"]
    first, second = rent("Flat rent"), rent("Gym")
    fail_after(monkeypatch, "apps.schedules.occurrences.materialise", bool)
    monkeypatch.setattr(daily_job, "STEPS", (materialise_occurrences, broken_step))

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 1))

    [email] = mail.outbox
    assert email.to == ["admin@example.com"]
    for failure in (
        f"materialise_occurrences failed for Schedule {first.pk}",
        f"materialise_occurrences failed for Schedule {second.pk}",
        "broken_step failed",
    ):
        assert failure in email.body
    assert email.body.count(f"RuntimeError: {BROKEN}") == 3


def test_a_clean_run_emails_no_admins(settings: Settings) -> None:
    settings.ADMINS = ["admin@example.com"]
    rent("Flat rent")

    run_daily_job(date(2026, 10, 1))

    assert not [email for email in mail.outbox if "admin@example.com" in email.to]


def test_one_failed_schedule_leaves_the_others_materialised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bad, good = rent("Flat rent"), rent("Gym")
    fail_after(monkeypatch, "apps.schedules.occurrences.materialise", bad.__eq__)

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 1))

    assert not bad.occurrences.exists()
    assert good.occurrences.exists()
    assert_logged(caplog, "materialise_occurrences", f"Schedule {bad.pk}")


def test_one_failed_match_leaves_the_others_matched(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    schedules = rent("Flat rent"), rent("Gym")
    for schedule in schedules:
        split = schedule.splits.get()
        assert schedule.party
        paid(
            (split.from_account, split.to_account),
            schedule.party,
            ("25000", date(2026, 10, 5)),
        )
    bad, good = schedules
    fail_after(
        monkeypatch,
        "apps.schedules.matching.match_occurrence",
        lambda occurrence: occurrence.schedule == bad,
    )

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 5))

    failed = bad.occurrences.get(due_date=date(2026, 10, 5))
    assert failed.transaction is None
    assert good.occurrences.get(due_date=date(2026, 10, 5)).transaction
    assert_logged(caplog, "match_transactions", f"Occurrence {failed.pk}")


def test_one_failed_draft_leaves_the_others_proposed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bad, good = rent("Flat rent"), rent("Gym")
    fail_after(
        monkeypatch,
        "apps.schedules.occurrences.propose_draft",
        lambda occurrence: occurrence.schedule == bad,
    )

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 5))

    assert Draft.objects.get(occurrence__schedule=good)
    assert Draft.objects.count() == 1
    failed = bad.occurrences.get(due_date=date(2026, 10, 5))
    assert failed.status == Occurrence.Status.UPCOMING
    assert_logged(caplog, "propose_due_drafts", f"Occurrence {failed.pk}")


def test_one_failed_card_leaves_the_others_statements_created(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    groceries = make_account("Groceries", "expense")
    bad, good = make_card("HDFC card"), make_card("ICICI card")
    for card in bad, good:
        record(card, groceries, "1200", date(2026, 9, 20))
    fail_after(monkeypatch, "apps.cards.statements.create_statement", bad.__eq__)

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 16))

    assert [s.card for s in Statement.objects.all()] == [good]
    assert not Draft.objects.filter(statement__card=bad).exists()
    assert_logged(caplog, "create_statements", f"Account {bad.pk}")


def test_one_failed_statement_leaves_the_others_settled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    groceries = make_account("Groceries", "expense")
    bad, good = make_card("HDFC card"), make_card("ICICI card")
    for card in bad, good:
        record(card, groceries, "1200", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))
    for card in bad, good:
        assert card.pays_from
        record(card.pays_from, card, "1200", date(2026, 11, 3))
    fail_after(
        monkeypatch,
        "apps.cards.statements.settle",
        lambda statement: statement.card == bad,
    )

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 11, 3))

    assert Statement.objects.get(card=bad).transaction is None
    assert Draft.objects.get(statement__card=bad)
    assert Draft.objects.count() == 1
    assert Statement.objects.get(card=good).transaction
    assert_logged(caplog, "match_card_payments", "Statement")


def test_one_failed_card_emi_leaves_the_others_proposed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bad, good = (
        make_card_emi(make_card("HDFC card")),
        make_card_emi(make_card("ICICI card")),
    )
    fail_after(monkeypatch, "apps.cards.emis.propose_installment", bad.__eq__)

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 9, 16))

    assert not bad.drafts.exists()
    assert good.drafts.exists()
    assert_logged(caplog, "propose_card_emi_drafts", f"CardEMI {bad.pk}")


def test_a_failed_digest_send_keeps_no_digest_record(
    user: User, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    rent("Flat rent")

    def mail_down(*args: Any, **kwargs: Any) -> int:
        raise OSError(BROKEN)

    monkeypatch.setattr("apps.digest.email.send_mail", mail_down)

    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 2))

    assert not Digest.objects.filter(user=user).exists()
    assert_logged(caplog, "send_digest")
