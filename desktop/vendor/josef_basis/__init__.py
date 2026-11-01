"""Josefs gemeinsame GTK-4-Bausteine. Import startet weder GUI noch Netzwerk."""
from pathlib import Path
from ._version import __version__
from .jobs import JobRunner, JobContext, Cancelled

__all__ = ['Anwendung', 'JobRunner', 'JobContext', 'Cancelled', '__version__']


class Anwendung:
    """Eine Projektanwendung pro Prozess; GUI-Abhängigkeiten werden spät geladen."""

    def __init__(self, projektdatei, *, entwicklung=False, zustandsordner=None):
        from . import model
        model.configure(projektdatei, development=entwicklung, state_dir=zustandsordner)
        self.projekt = dict(model.PROJECT)
        self.version = model.VERSION
        self.projektordner = Path(projektdatei).resolve().parent

    def gtk_anwendung(self, *, fensterklasse=None):
        """Optional eigene Klasse auf Basis von josef_basis.gui.MainWindow übergeben."""
        from .gui import Application
        return Application(window_factory=fensterklasse)

    def start(self, *, fensterklasse=None):
        return self.gtk_anwendung(fensterklasse=fensterklasse).run([])
