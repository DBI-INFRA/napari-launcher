"""
start napari with plugin widgets docked, from the command line or an app shortcut
"""

from ._launch import launch
from ._shortcut import create_shortcut, remove_shortcut, shortcut_paths

try:
    from ._version import version as __version__
except ImportError:
    __version__ = 'unknown'

__all__ = ['create_shortcut', 'launch', 'remove_shortcut', 'shortcut_paths']
