"""
start napari with plugin widgets docked
"""

import os
import sys
from importlib.util import find_spec
from pathlib import Path


def widget_groups(widgets):
    """`widgets` as a list of (plugin, *widget names) tuples; a single string is one plugin"""
    if isinstance(widgets, str):
        widgets = [widgets]
    groups = []
    for group in widgets:
        group = (group,) if isinstance(group, str) else tuple(group)
        if not group or not all(isinstance(part, str) and part for part in group):
            raise ValueError(f'a widget group is a plugin name and widget names, not {group!r}')
        groups.append(group)
    return groups


def with_args(widgets):
    """napari's `-w PLUGIN [WIDGET ...]` arguments for `widgets`"""
    return [arg for group in widget_groups(widgets) for arg in ('-w', *group)]


def data_folder():
    """the per-user folder for napari-launcher's own files, such as icons and the log"""
    if sys.platform == 'win32':
        return Path(os.environ['LOCALAPPDATA']) / 'napari-launcher'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'napari-launcher'


def log_to_file():
    """
    send stdout and stderr to a log file if either has nowhere to go, as under pythonw.exe;
    returns the log file, or None if the output already goes somewhere
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    log = data_folder() / 'logs' / 'launch.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    # the log stays open until the process ends
    sys.stdout = sys.stderr = open(log, 'w', encoding='utf-8', errors='backslashreplace', buffering=1)  # noqa: SIM115
    return log


def show_error(error, log):
    """tell the user in a dialog that napari did not start, if Qt is there to show one"""
    try:
        from qtpy.QtWidgets import QApplication, QMessageBox
    except ImportError:  # no Qt binding, or a broken one
        return
    _app = QApplication.instance() or QApplication([])
    QMessageBox.critical(None, 'napari did not start', f'{error}\n\nThe details are in {log}')


def launch(widgets=(), paths=()):
    """
    open napari with `widgets` docked and `paths` loaded; returns when napari closes

    widgets: a plugin name, or a list of plugin names and (plugin, *widget names) tuples
    paths: a file, or a list of files
    """
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    args = with_args(widgets)
    if sys.platform == 'win32' and find_spec('torch'):
        # torch must load before Qt on Windows: https://github.com/pytorch/pytorch/issues/166628
        import torch  # noqa: F401
    import napari.__main__

    # argv[0] as `python -m napari` sets it: napari before 0.7 restarts itself on macOS, and that
    # restart only works for an argv[0] of a napari script or of napari's __main__ module
    sys.argv = [napari.__main__.__file__, *args, '--', *map(str, paths)]
    return napari.__main__.main()
