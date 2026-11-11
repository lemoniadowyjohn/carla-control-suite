"""V94: deterministic adversarial GUI callback-registration race.

Test uses only the stdlib, no CARLA/PyQt/OS-specific assumptions.
"""
import threading

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled


def test_registration_during_cancel_event_publication_delivered_once():
    entered_set = threading.Event()
    release_set = threading.Event()
    seen = []

    class PausingEvent(threading.Event):
        def set(self):
            entered_set.set()
            assert release_set.wait(2), "test harness failed to release set()"
            super().set()

    token = CancellationToken()
    token._event = PausingEvent()
    worker = threading.Thread(target=lambda: token.cancel("operator-stop"))
    worker.start()
    assert entered_set.wait(2), "cancellation did not reach set()"

    registered = threading.Event()

    def register():
        token.on_cancel(seen.append)
        registered.set()

    registrant = threading.Thread(target=register)
    registrant.start()
    # On old code registration returns in the publish gap (callback is lost).
    # On corrected code the cancellation lock excludes this interleaving.
    registered.wait(0.10)
    release_set.set()
    worker.join(2)
    registrant.join(2)
    assert not worker.is_alive() and not registrant.is_alive()
    assert registered.is_set()
    assert token.cancelled and token.reason == "operator-stop"
    assert seen == ["operator-stop"]


def test_callback_registered_before_cancel_fires_once_even_if_cancel_repeated():
    token = CancellationToken()
    seen = []
    token.on_cancel(seen.append)
    token.cancel("first")
    token.cancel("second")
    assert seen == ["first"]
    assert token.reason == "first"


def test_callback_registered_after_cancel_fires_once():
    token = CancellationToken()
    token.cancel("already")
    seen = []
    token.on_cancel(seen.append)
    assert seen == ["already"]


def test_bad_callback_does_not_prevent_other_callbacks_or_cancellation():
    token = CancellationToken()
    seen = []

    def bad(_):
        raise RuntimeError("callback error")

    token.on_cancel(bad)
    token.on_cancel(seen.append)
    token.cancel("stop")
    assert seen == ["stop"]
    try:
        token.raise_if_cancelled()
    except OperationCancelled as exc:
        assert "stop" in str(exc)
    else:
        raise AssertionError("cancelled token did not raise")


def test_cancel_waiter_unblocks_and_timeout_is_observed():
    token = CancellationToken()
    assert token.wait(timeout=0.005) is False
    token.cancel("stop")
    assert token.wait(timeout=0.005) is True
