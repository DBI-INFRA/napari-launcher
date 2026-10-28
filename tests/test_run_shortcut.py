"""
Run the command a created shortcut stores, as the desktop would, and check which widgets dock.

A test plugin with an awkward widget name is put on PYTHONPATH. A sitecustomize module, also on
PYTHONPATH, keeps napari's window hidden and replaces napari.run, so napari records its docked
widgets and closes instead of waiting for the user.
"""

import json
import os
import subprocess
import sys

import pytest
from conftest import parse_exec

from napari_launcher import _icons, _shortcut, create_shortcut

PLUGIN = 'launcher-test-plugin'
WIDGET = 'It\'s a "50%" $HOME widget'
MANIFEST = {
    'name': PLUGIN,
    'display_name': 'Launcher test plugin',
    'contributions': {
        'commands': [
            {'id': f'{PLUGIN}.plain', 'python_name': 'launcher_test_plugin:plain', 'title': 'Plain'},
            {'id': f'{PLUGIN}.awkward', 'python_name': 'launcher_test_plugin:awkward', 'title': 'Awkward'},
        ],
        'widgets': [
            {'command': f'{PLUGIN}.plain', 'display_name': 'plain'},
            {'command': f'{PLUGIN}.awkward', 'display_name': WIDGET},
        ],
    },
}
PLUGIN_CODE = """\
from qtpy.QtWidgets import QLabel


def plain():
    return QLabel('plain')


def awkward():
    return QLabel('awkward')
"""
SITECUSTOMIZE = """\
import json
import os

import napari
from napari.viewer import Viewer

init = Viewer.__init__


def hidden_init(self, *args, **kwargs):
    kwargs['show'] = False
    init(self, *args, **kwargs)


def run(*args, **kwargs):
    viewer = napari.current_viewer()
    with open(os.environ['LAUNCHER_TEST_RESULT'], 'w', encoding='utf-8') as f:
        json.dump({'docked': sorted(viewer.window._dock_widgets), 'visible': viewer.window._qt_window.isVisible()}, f)
    viewer.close()


Viewer.__init__ = hidden_init
Viewer.show = lambda self, *args, **kwargs: None
napari.run = run
"""

pytestmark = pytest.mark.skipif(
    sys.platform.startswith('linux') and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')),
    reason='napari needs a display, even for a hidden window',
)


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    """the test plugin, installed for this Python through PYTHONPATH"""
    site = tmp_path / 'site'
    package = site / 'launcher_test_plugin'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text(PLUGIN_CODE)
    # JSON is also YAML
    (package / 'napari.yaml').write_text(json.dumps(MANIFEST))
    dist = site / 'launcher_test_plugin-0.1.dist-info'
    dist.mkdir()
    (dist / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {PLUGIN}\nVersion: 0.1\n')
    (dist / 'entry_points.txt').write_text(f'[napari.manifest]\n{PLUGIN} = launcher_test_plugin:napari.yaml\n')
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(filter(None, [str(site), os.environ.get('PYTHONPATH')])))


def _run(argv, tmp_path):
    """run `argv` with napari patched as described above; returns the names of the docked widgets"""
    patches = tmp_path / 'patches'
    patches.mkdir()
    (patches / 'sitecustomize.py').write_text(SITECUSTOMIZE)
    result = tmp_path / 'docked.json'
    env = {
        **os.environ,
        'PYTHONPATH': os.pathsep.join([str(patches), os.environ['PYTHONPATH']]),
        'LAUNCHER_TEST_RESULT': str(result),
        # napari before 0.7 restarts itself on macOS unless this is set
        '_NAPARI_RERUN_WITH_FIXES': '1',
        # no Dock icon on macOS
        'QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM': '1',
    }
    done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=300, check=False)
    assert done.returncode == 0, done.stderr
    seen = json.loads(result.read_text(encoding='utf-8'))
    assert not seen['visible']
    return seen['docked']


def _split_windows(line):
    """the arguments a Windows program gets for command line `line`, by the Microsoft C runtime rules"""
    args, arg, quoted, backslashes, started = [], '', False, 0, False
    for char in line + ' ':
        if char == '\\':
            backslashes += 1
            started = True
            continue
        if char == '"':
            arg += '\\' * (backslashes // 2)
            if backslashes % 2:
                arg += '"'
            else:
                quoted = not quoted
            backslashes, started = 0, True
            continue
        arg += '\\' * backslashes
        backslashes = 0
        if char in ' \t' and not quoted:
            if started:
                args.append(arg)
            arg, started = '', False
        else:
            arg += char
            started = True
    return args


def test_split_windows():
    args = ['a b', 'c"d', 'e\\', 'f\\\\"g', '', 'h\\i']
    assert _split_windows(subprocess.list2cmdline(args)) == args


def _desktop_command(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(sys, 'platform', 'linux')
        entry, *_ = create_shortcut('Test', [(PLUGIN, WIDGET)], desktop=False)
    exec_value = next(line for line in entry.read_text(encoding='utf-8').splitlines() if line.startswith('Exec='))
    # %F is the files dropped on the shortcut: none here
    return [arg for arg in parse_exec(exec_value[5:]) if arg != '%F']


def _app_command(monkeypatch):
    if sys.platform == 'win32':
        pytest.skip('the macOS launcher is a shell script')
    with monkeypatch.context() as m:
        m.setattr(sys, 'platform', 'darwin')
        app, *_ = create_shortcut('Test', [(PLUGIN, WIDGET)], desktop=False)
    return [str(app / 'Contents' / 'MacOS' / 'Test')]


def _lnk_command(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'AppData' / 'Local'))
    monkeypatch.setattr(_shortcut, '_windows_folder', lambda name: tmp_path / name)
    if sys.platform == 'win32':
        (lnk,) = create_shortcut('Test', [(PLUGIN, WIDGET)], desktop=False)
        target, args = _shortcut._powershell(
            '$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SHORTCUT_LNK); $s.TargetPath; $s.Arguments',
            SHORTCUT_LNK=str(lnk),
        ).splitlines()
        # a command line, as Windows passes it to the program
        return f'"{target}" {args}'
    written = {}

    def powershell(script, **values):
        if script == _shortcut.LNK_WRITE:
            written.update(values)
        return ''

    with monkeypatch.context() as m:
        m.setattr(sys, 'platform', 'win32')
        m.setattr(_shortcut, '_powershell', powershell)
        create_shortcut('Test', [(PLUGIN, WIDGET)], desktop=False)
    return [written['SHORTCUT_TARGET'], *_split_windows(written['SHORTCUT_ARGS'])]


@pytest.mark.parametrize('kind', ['desktop', 'app', 'lnk'])
def test_shortcut_command_docks_the_widget(kind, plugin, home, tmp_path, monkeypatch):
    # the icon plays no part in the command
    monkeypatch.setattr(_icons, 'install', lambda *args: None)
    if kind == 'desktop':
        command = _desktop_command(monkeypatch)
    elif kind == 'app':
        command = _app_command(monkeypatch)
    else:
        command = _lnk_command(monkeypatch, tmp_path)
    docked = _run(command, tmp_path)
    assert [name for name in docked if name.startswith(WIDGET)], docked
    assert not [name for name in docked if name.startswith('plain')], docked
