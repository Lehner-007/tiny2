"""Contract checks for bundled UI translations and offline help."""
import json
from pathlib import Path
from string import Formatter
import unittest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
CODES = {'ar', 'de', 'en', 'es', 'fr', 'hi', 'pt', 'ru', 'tr', 'zh'}
FOLDER = 'languages' if (ROOT / 'languages').is_dir() else 'lang'

class BundledLanguagesTests(unittest.TestCase):
    def test_complete_texts_and_placeholders(self):
        english = json.loads((ROOT / FOLDER / 'en.json').read_text())
        self.assertEqual({p.stem for p in (ROOT / FOLDER).glob('*.json')}, CODES)
        def fields(text):
            return [(name, spec, conversion) for _, name, spec, conversion in Formatter().parse(text) if name is not None]
        for code in CODES:
            data = json.loads((ROOT / FOLDER / (code + '.json')).read_text())
            self.assertEqual(set(data), set(english), code)
            for key, value in data.items():
                self.assertIsInstance(value, str)
                self.assertEqual(sorted(fields(value)), sorted(fields(english[key])), (code, key))
                self.assertNotIn('ZXQ', value)
                self.assertNotIn('ZXLINE', value)

    def test_offline_help_for_every_language(self):
        for code in CODES:
            path = ROOT / 'help' / (code + '.html') if FOLDER == 'languages' else ROOT / 'help' / code / 'index.html'
            self.assertTrue(path.is_file(), str(path))
            soup = BeautifulSoup(path.read_text(), 'html.parser')
            self.assertTrue(soup.html)
            self.assertEqual(soup.html.get('lang'), code)
            self.assertGreater(len(soup.get_text(strip=True)), 200)
            if code not in ('de', 'en'):
                self.assertFalse(soup.find(['script', 'iframe', 'object', 'embed']))
                if code == 'ar': self.assertEqual(soup.html.get('dir'), 'rtl')

    def test_bundled_languages_are_selectable_and_help_matches(self):
        import sys
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / 'desktop/vendor'))
        from josef_basis import model
        if model._configuration is None:
            model.configure(ROOT / 'projekt.json', development=True, state_dir=ROOT / 'work/bundled-language-tests')
        from josef_basis import i18n
        with patch.object(i18n, 'config_dir', return_value=ROOT / 'work/no-installed-languages'):
            self.assertEqual(set(i18n.Strings.languages()), CODES)
            for code in CODES:
                strings = i18n.Strings(code)
                self.assertEqual(strings.help_path(), ROOT / 'help' / code / 'index.html')
                self.assertNotEqual(strings.language_name(code), code)
