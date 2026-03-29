import httpx

from notifications.telegram_commands import TelegramCommandHandler


class _DummyBrain:
    pass


def test_transient_poll_failures_back_off_without_traceback(monkeypatch) -> None:
    handler = TelegramCommandHandler(_DummyBrain())
    warnings: list[str] = []
    exceptions: list[str] = []

    monkeypatch.setattr(
        "notifications.telegram_commands.logger.warning",
        lambda message: warnings.append(message),
    )
    monkeypatch.setattr(
        "notifications.telegram_commands.logger.exception",
        lambda message: exceptions.append(message),
    )

    retry_1 = handler._record_poll_failure(httpx.ConnectError("boom"))
    retry_2 = handler._record_poll_failure(httpx.ConnectError("boom"))
    retry_3 = handler._record_poll_failure(httpx.ConnectError("boom"))

    assert retry_1 == 1.5
    assert retry_2 == 3.0
    assert retry_3 == 6.0
    assert handler._poll_failures == 3
    assert len(warnings) == 2
    assert not exceptions


def test_non_transient_poll_failure_uses_exception_logging(monkeypatch) -> None:
    handler = TelegramCommandHandler(_DummyBrain())
    warnings: list[str] = []
    exceptions: list[str] = []

    monkeypatch.setattr(
        "notifications.telegram_commands.logger.warning",
        lambda message: warnings.append(message),
    )
    monkeypatch.setattr(
        "notifications.telegram_commands.logger.exception",
        lambda message: exceptions.append(message),
    )

    retry = handler._record_poll_failure(RuntimeError("unexpected"))

    assert retry == 1.5
    assert not warnings
    assert len(exceptions) == 1


def test_poll_success_resets_failure_streak(monkeypatch) -> None:
    handler = TelegramCommandHandler(_DummyBrain())
    infos: list[str] = []

    monkeypatch.setattr(
        "notifications.telegram_commands.logger.info",
        lambda message: infos.append(message),
    )

    handler._poll_failures = 2
    handler._record_poll_success()

    assert handler._poll_failures == 0
    assert len(infos) == 1
