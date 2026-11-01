#!/usr/bin/env python3
"""Tiny entry point. CLI metadata works without GTK or a camera."""
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'desktop/vendor'))

def main():
    parser=argparse.ArgumentParser(description='Tiny – Tiny 2 und Logitech C922 Kamerasteuerung')
    parser.add_argument('--version',action='version',version='Tiny '+(ROOT/'VERSION').read_text().strip())
    parser.add_argument('--author',action='store_true',help='Mitwirkende anzeigen')
    args=parser.parse_args()
    if args.author:
        print('Josef – Desktop-Anwendung; Michael Jordan – obsbot-mcp')
        return 0
    from josef_basis import Anwendung
    # Source and portable ZIP copies keep their private state beside the
    # application. Debian installs are read-only and use the user's XDG path.
    app=Anwendung(ROOT/'projekt.json',entwicklung=(ROOT/'.development').is_file())
    try:
        from desktop.gui import CameraWindow
        return app.start(fensterklasse=CameraWindow)
    except (ImportError,ValueError) as exc:
        print('Tiny: GTK 4, PyGObject und GStreamer werden benötigt. '+str(exc),file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
