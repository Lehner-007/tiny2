"""Formatwahl und portabler Export von Ergebnisdatensätzen."""
import csv
import html
import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from gi.repository import Gtk
from .model import ROOT, PROJECT, PROGRAM_ID, VERSION
from .file_dialogs import choose, check_export_target

FORMATS = ('csv', 'json', 'html')


def serialize(rows, columns, format_, tr):
    if format_ not in FORMATS:
        raise ValueError('Unknown export format')
    def value(row, key):
        item = row.get(key, '')
        return tr('result_' + item) if key == 'status' else str(item)
    if format_ == 'json':
        return json.dumps(dict(program_id=PROGRAM_ID, version=VERSION, results=rows), ensure_ascii=False, indent=2) + '\n'
    if format_ == 'csv':
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, delimiter=';')
        writer.writerow([tr(label) for _, label in columns])
        for row in rows:
            # Tabellenprogramme dürfen Benutzerdaten nicht als Formeln ausführen.
            cells = [value(row, key) for key, _ in columns]
            writer.writerow(["'" + cell if cell.lstrip().startswith(('=', '+', '-', '@')) else cell for cell in cells])
        return '\ufeff' + stream.getvalue()
    title = html.escape(PROJECT['name'])
    headings = ''.join('<th>' + html.escape(tr(label)) + '</th>' for _, label in columns)
    body = ''.join('<tr>' + ''.join('<td>' + html.escape(value(row, key)) + '</td>' for key, _ in columns) + '</tr>' for row in rows)
    watermark = ''
    image = ROOT / PROJECT.get('watermark', 'assets/report_watermark.png')
    if image.is_file():
        import base64
        encoded = base64.b64encode(image.read_bytes()).decode('ascii')
        import mimetypes
        mime = mimetypes.guess_type(str(image))[0] or 'image/png'
        watermark = 'body::before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.1;background:url(data:' + mime + ';base64,' + encoded + ') center/260px no-repeat;}'
    return ('<!doctype html><html lang="' + html.escape(tr.code, quote=True) + '"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>' + title + '</title>'
            '<style>body{font-family:system-ui;margin:2em}table{border-collapse:collapse;width:100%}th,td{border:1px solid #aaa;padding:.5em;text-align:start;overflow-wrap:anywhere}' + watermark + '</style>'
            '<body><h1>' + title + '</h1><p>' + html.escape(datetime.now().strftime('%d.%m.%Y %H:%M:%S')) + '</p><table><thead><tr>' + headings + '</tr></thead><tbody>' + body + '</tbody></table></body></html>')


def write_export(path, rows, columns, format_, tr):
    path = check_export_target(path)
    content = serialize(rows, columns, format_, tr)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def show_export(owner):
    window = owner.track(Gtk.Window(title=owner.tr('results_export'), transient_for=owner, modal=True,
                                   default_width=460))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                  margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
    window.set_child(box)
    box.append(owner.label('export_format', xalign=0))
    format_ = Gtk.DropDown.new_from_strings(['CSV', 'JSON', 'HTML'])
    box.append(format_)
    box.append(owner.label('export_scope', xalign=0))
    scope = Gtk.DropDown.new_from_strings([owner.tr('export_all'), owner.tr('export_visible')])
    box.append(scope)
    def save(*_):
        choice = FORMATS[format_.get_selected()]
        rows = owner.results.rows(visible=scope.get_selected() == 1)
        if not rows:
            owner.notify('export_empty')
            return
        def selected(path):
            write_export(path, rows, owner.results.columns, choice, owner.tr)
            owner.logger.info(owner.tr('results_exported', path=str(path)))
            owner.set_status('results_exported', path=str(path))
            owner.close_dialog(window)
        choose(owner, 'results_export', selected, action=Gtk.FileChooserAction.SAVE, parent=window,
               filename=PROGRAM_ID + '-ergebnisse.' + choice, filters=((choice.upper(), ('*.' + choice,)),))
    footer = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    footer.append(owner.button('cancel', lambda *_: owner.close_dialog(window)))
    button = owner.button('choose_save', save)
    footer.append(button)
    box.append(footer)
    window.export_controls = dict(format=format_, scope=scope, save=button)
    window.present()
    return window
