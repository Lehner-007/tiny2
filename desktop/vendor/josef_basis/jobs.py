"""Kooperative Hintergrundarbeit mit Rückmeldungen auf dem GUI-Hauptthread."""
import threading


class Cancelled(Exception):
    """Ein Vorgang wurde an einem sicheren Abbruchpunkt beendet."""


class JobContext:
    def __init__(self, cancel_event, report):
        self.cancel_event = cancel_event
        self._report = report

    def check_cancel(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    def progress(self, current, total):
        self.check_cancel()
        if total <= 0 or current < 0 or current > total:
            raise ValueError('Invalid progress')
        self._report(current, total)


class JobRunner:
    def __init__(self, dispatch):
        self.dispatch = dispatch
        self.running = False
        self.cancellable = False
        self.cancel_event = None
        self.token = None

    def start(self, task, on_progress, on_finish, cancellable=False):
        if self.running:
            return False
        self.running = True
        self.cancellable = cancellable
        self.cancel_event = threading.Event()
        token = self.token = object()
        def report(current, total):
            def deliver():
                if self.running and self.token is token:
                    on_progress(current, total)
            self.dispatch(deliver)
        context = JobContext(self.cancel_event, report)
        def work():
            try:
                result = task(context)
                if cancellable:
                    context.check_cancel()
                error = None
            except Exception as exc:
                result, error = None, exc
            def finish():
                if self.token is not token:
                    return
                self.running = False
                self.cancellable = False
                on_finish(result, error)
            self.dispatch(finish)
        self.thread = threading.Thread(target=work, daemon=False)
        self.thread.start()
        return True

    def cancel(self):
        if self.running and self.cancellable:
            self.cancel_event.set()
            return True
        return False
