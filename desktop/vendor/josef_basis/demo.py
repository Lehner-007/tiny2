"""Zehn Sekunden Leerlauf zum Prüfen von Fortschritt und Abbrechen."""
import time


def idle_demo(context, duration=10):
    started = time.monotonic()
    previous = -1
    while True:
        context.check_cancel()
        elapsed = min(duration, time.monotonic() - started)
        current = int(elapsed)
        if current != previous:
            context.progress(current, duration)
            previous = current
        if elapsed >= duration:
            context.progress(duration, duration)
            return duration
        context.cancel_event.wait(min(0.05, duration - elapsed))
