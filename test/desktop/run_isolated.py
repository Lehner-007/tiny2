"""Run the desktop suite without enumerating or changing physical cameras."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
(ROOT/'work').mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('desktop_suite',ROOT/'test/desktop/test_desktop.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from desktop import uvc
inventory=uvc.inventory
def isolated_inventory(*args,**kwargs):
    return inventory(*args,**kwargs) if args or 'sys_root' in kwargs else []
with patch.object(uvc,'inventory',side_effect=isolated_inventory):
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
sys.exit(not result.wasSuccessful())
