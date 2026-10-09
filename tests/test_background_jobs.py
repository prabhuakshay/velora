from procrastinate import testing
from procrastinate.contrib.django import app


def test_deferred_task_is_run_by_the_worker() -> None:
    ran: list[str] = []

    @app.task(name="tests.record")
    def record(word: str) -> None:
        ran.append(word)

    with app.replace_connector(testing.InMemoryConnector()) as in_memory_app:
        record.defer(word="hello")
        in_memory_app.run_worker(wait=False, concurrency=1)

    assert ran == ["hello"]
