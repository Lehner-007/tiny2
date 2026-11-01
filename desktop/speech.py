"""Separate voice and gesture tabs with one visible row per camera function."""
from gi.repository import Gtk
from josef_basis.gui import vertical
from josef_basis.model import atomic_json, config_dir, ROOT

VOICE_COMMANDS=('wake','sleep','track','unlock','zoom-in','zoom-out','presets')
GESTURES=('target','zoom','dynamic-zoom','mirror')

class SpeechControls:
    def build_speech_page(self):
        page=vertical(margin=8)
        title=self.label('speech_gestures_heading',xalign=0,wrap=True)
        title.add_css_class('title-2')
        page.append(title)
        page.append(self.label('speech_functions_hint',xalign=0,wrap=True))
        self.speech_notebook=Gtk.Notebook(vexpand=True,hexpand=True)
        page.append(self.speech_notebook)
        self.speech_lists={}
        self.speech_controls={}
        self.speech_rows={}
        for tab,tool,parameter,values in (
                ('voice_tab','voice_control','command',VOICE_COMMANDS),
                ('gesture_tab','gesture_control','gesture',GESTURES)):
            content=vertical(margin=12)
            heading=self.label(tab+'_heading',xalign=0,wrap=True)
            heading.add_css_class('title-2')
            content.append(heading)
            if tab=='gesture_tab':content.append(self.label('gesture_sign_note',xalign=0,wrap=True))
            choices=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            choices.add_css_class('boxed-list')
            self.speech_lists[tab]=choices
            for value in values:
                key=f'{tool}:{value}'
                saved=self.tracking_values.get(key,{})
                # Preserve the previously selected command when migrating 0.16.0.
                if not isinstance(saved,dict) or 'enabled' not in saved:
                    old=self.tracking_values.get(tool,{})
                    saved=old if isinstance(old,dict) and old.get(parameter)==value else {}
                active=saved.get('enabled',False)
                widget=Gtk.Switch(active=active if type(active) is bool else False,
                                  valign=Gtk.Align.CENTER)
                row=self.speech_row(choices,'value_'+value,widget,gesture=value if tab=='gesture_tab' else None)
                self.speech_controls[key]=(tool,{parameter:value},widget,widget.get_active)
                self.speech_rows[key]=row
                def changed(*_,key=key,row=row,choices=choices,widget=widget):
                    choices.select_row(row)
                    self.remember_speech(key,{'enabled':widget.get_active()})
                widget.connect('notify::active',changed)
            if tab=='voice_tab':
                widget=Gtk.DropDown.new_from_strings([self.tr('value_english'),self.tr('value_chinese')])
                saved=self.tracking_values.get('voice_language',{})
                language=saved.get('language','english') if isinstance(saved,dict) else 'english'
                widget.set_selected(1 if language=='chinese' else 0)
                row=self.speech_row(choices,'field_language',widget)
                self.speech_controls['voice_language']=('voice_language',{},widget,
                    lambda widget=widget:('english','chinese')[widget.get_selected()])
                self.speech_rows['voice_language']=row
                def language_changed(*_,row=row,choices=choices,widget=widget):
                    choices.select_row(row)
                    self.remember_speech('voice_language',{'language':('english','chinese')[widget.get_selected()]})
                self.speech_language_handler=widget.connect('notify::selected',language_changed)
            choices.select_row(choices.get_row_at_index(0))
            content.append(choices)
            scroll=Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_child(content)
            self.speech_notebook.append_page(scroll,self.label(tab))
        button=self.button('apply_tool',lambda *_:self.apply_tool())
        button.set_halign(Gtk.Align.START)
        page.append(button)
        self.pages['speech_gestures']=self.add_stack_page(page,'speech_gestures')

    def speech_row(self,choices,label,widget,gesture=None):
        row=Gtk.ListBoxRow()
        box=Gtk.Box(spacing=16,margin_top=10,margin_bottom=10,margin_start=10,margin_end=10)
        if gesture:
            image=Gtk.Image.new_from_file(str(ROOT/'assets/gestures'/f'{gesture}.svg'))
            image.set_pixel_size(112)
            image.set_size_request(112,80)
            box.append(image)
            text=vertical(margin=0)
            text.set_hexpand(True)
            text.append(self.label(label,xalign=0,wrap=True))
            description=self.label('gesture_sign_'+gesture,xalign=0,wrap=True)
            description.add_css_class('dim-label')
            text.append(description)
            box.append(text)
        else:
            box.append(self.label(label,xalign=0,wrap=True,hexpand=True))
        box.append(widget)
        row.set_child(box)
        choices.append(row)
        return row

    def remember_speech(self,key,values):
        if getattr(self,'resetting_settings',False):return
        self.tracking_values[key]=values
        try:atomic_json(config_dir()/'tracking.json',self.tracking_values)
        except OSError:
            self.logger.exception('Sprach-/Gesteneinstellungen konnten nicht gespeichert werden')
            self.notify('write_error')

    def apply_speech(self):
        if self.busy:return
        tab=('voice_tab','gesture_tab')[self.speech_notebook.get_current_page()]
        selected=self.speech_lists[tab].get_selected_row()
        for key,row in self.speech_rows.items():
            if row is selected:
                tool,parameters,widget,get=self.speech_controls[key]
                arguments=dict(parameters)
                arguments['language' if tool=='voice_language' else 'enabled']=get()
                self.command(tool,arguments)
                return

    def refresh_speech_language(self):
        widget=self.speech_controls['voice_language'][2]
        selected=widget.get_selected()
        widget.handler_block(self.speech_language_handler)
        try:
            widget.set_model(Gtk.StringList.new([self.tr('value_english'),self.tr('value_chinese')]))
            widget.set_selected(selected)
        finally:widget.handler_unblock(self.speech_language_handler)
