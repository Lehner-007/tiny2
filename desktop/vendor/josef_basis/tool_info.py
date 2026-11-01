"""Optionale Werkzeugübersicht; ausschließlich lesende Verfügbarkeitsprüfung."""
import importlib.util
import importlib.metadata
import platform
import shutil
import subprocess
import threading
from gi.repository import Gtk, GLib
from .model import PROJECT
from .windows import center_after_map
from .gui import vertical


def inspect_tool(tool):
    result=dict(tool,available=False,version='')
    try:
        kind=tool['kind']
        if kind=='python':result.update(available=True,version=platform.python_version())
        elif kind=='gtk':result.update(available=True,version='.'.join(map(str,(Gtk.get_major_version(),Gtk.get_minor_version(),Gtk.get_micro_version()))))
        elif kind=='module':
            result['available']=importlib.util.find_spec(tool['module']) is not None
            if result['available']:
                try:result['version']=importlib.metadata.version(tool.get('distribution',tool['module']))
                except importlib.metadata.PackageNotFoundError:pass
        elif kind=='command':
            command=shutil.which(tool['command'])
            if command:
                process=subprocess.run([command,*tool.get('version_args',['--version'])],capture_output=True,text=True,timeout=5,check=False)
                result['available']=True
                lines=(process.stdout or process.stderr).splitlines()
                if process.returncode==0 and lines:result['version']=lines[0][:500]
    except (OSError,ValueError,ImportError,subprocess.SubprocessError):pass
    return result


def show_tool_info(owner):
    tools=PROJECT.get('tool_info',[])
    if not tools:return None
    for dialog in owner.dialogs:
        if dialog.get_name()=='tool_info_dialog':dialog.present();return dialog
    window=owner.track(Gtk.Window(title=owner.tr('info'),transient_for=owner,default_width=620,default_height=460))
    window.set_name('tool_info_dialog')
    owner.bindings.append((window,'set_title','info'))
    box=vertical();window.set_child(box)
    heading=Gtk.Box(spacing=10)
    heading.append(Gtk.Image.new_from_icon_name('dialog-information-symbolic'))
    title=owner.label('tool_info_title',xalign=0);title.add_css_class('title-2');heading.append(title);box.append(heading)
    scroll=Gtk.ScrolledWindow(vexpand=True);content=vertical(margin=0);scroll.set_child(content);box.append(scroll)
    loading=owner.label('tool_info_loading',xalign=0);content.append(loading)
    box.append(owner.button('close',lambda *_:owner.close_dialog(window)))
    def present(results):
        if not owner.alive or window not in owner.dialogs:return False
        owner.bindings[:]=[b for b in owner.bindings if b[0] is not loading]
        child=content.get_first_child()
        while child:
            following=child.get_next_sibling();content.remove(child);child=following
        for tool in results:
            row=Gtk.Box(spacing=10)
            icon=Gtk.Image.new_from_icon_name('emblem-ok-symbolic' if tool['available'] else 'dialog-warning-symbolic')
            icon.set_valign(Gtk.Align.START);row.append(icon)
            details=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=3,hexpand=True)
            status='tool_available' if tool['available'] else 'tool_missing'
            label=Gtk.Label(label=tool['name']+' — '+owner.tr(status),xalign=0,wrap=True)
            details.append(label)
            if tool['version']:details.append(Gtk.Label(label=tool['version'],xalign=0,wrap=True,selectable=True))
            if tool.get('apt'):details.append(Gtk.Label(label='APT: '+tool['apt'],xalign=0,wrap=True,selectable=True))
            if tool.get('optional'):details.append(Gtk.Label(label=owner.tr('tool_optional'),xalign=0,wrap=True))
            if tool.get('note_key'):details.append(Gtk.Label(label=owner.tr(tool['note_key']),xalign=0,wrap=True))
            row.append(details);content.append(row)
        window.tool_results=results
        window.refresh_info=lambda:present(results)
        return False
    def worker():GLib.idle_add(present,[inspect_tool(tool) for tool in tools])
    threading.Thread(target=worker,daemon=True).start()
    window.present();center_after_map(window,owner);return window
