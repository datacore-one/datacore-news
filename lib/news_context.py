"""Bind news clients to a declared installed core and canonical private space."""
import os
from pathlib import Path
import sys

MODULE_DIR = Path(__file__).resolve().parent.parent
selected = os.environ.get('DATACORE_LIB')
LIB = Path(selected) if selected else MODULE_DIR.parents[1] / 'lib'
if selected is not None and (not selected or not LIB.is_absolute()):
    raise RuntimeError('invalid explicit installed core library')
if not (LIB / 'module_context.py').is_file() or not (LIB / 'file_utils.py').is_file():
    raise RuntimeError('qualified installed core required; configure DATACORE_LIB')
LIB = LIB.resolve(strict=True)
for name in ('module_context', 'file_utils', 'spaces'):
    loaded = sys.modules.get(name)
    if loaded is not None and Path(getattr(loaded, '__file__', '')).resolve().parent != LIB:
        raise RuntimeError('mixed core implementations are not supported')
sys.path.insert(0, str(LIB))
from module_context import resolve  # noqa: E402


def context(*, create=True):
    return resolve('news', MODULE_DIR, create=create)
