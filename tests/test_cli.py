import sys
import warnings

import pytest

import napari_launcher
from napari_launcher import _launch, _shortcut
from napari_launcher.__main__ import main


@pytest.fixture
def calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        _shortcut, 'create_shortcut', lambda name, widgets, **kw: calls.append((name, widgets, kw)) or ['a']
    )
    monkeypatch.setattr(_shortcut, 'remove_shortcut', lambda name: calls.append(name) or ['a'])
    return calls


@pytest.fixture
def napari_argv(monkeypatch):
    """the sys.argv that napari's main sees, after argv[0]"""
    import napari.__main__

    seen = []

    def napari_main():
        assert sys.argv[0] == napari.__main__.__file__
        seen.extend(sys.argv[1:])

    monkeypatch.setattr(napari.__main__, 'main', napari_main)
    monkeypatch.setattr(sys, 'argv', sys.argv[:])
    return seen


def _exit_code(argv):
    with pytest.raises(SystemExit) as exit_:
        main(argv)
    return exit_.value.code


def test_add_names(calls, capsys):
    assert main(['shortcut', 'add', '-w', 'napari-foo', 'Foo widget']) == 0
    assert main(['shortcut', 'add']) == 0
    assert main(['shortcut', 'add', '-w', 'a', '-w', 'b', '--name', 'Both', '--no-desktop']) == 0
    assert [(name, widgets, kw['desktop']) for name, widgets, kw in calls] == [
        ('napari-foo', [['napari-foo', 'Foo widget']], True),
        ('napari', [], True),
        ('Both', [['a'], ['b']], False),
    ]
    assert capsys.readouterr().out.splitlines() == ['created a'] * 3


def test_add_options(calls):
    main(['shortcut', 'add', '-w', 'napari-foo', '--comment', 'c', '--icon', 'pkg:icon.png', '--bundle-id', 'org.x'])
    assert calls[0][2] == {'comment': 'c', 'icon': 'pkg:icon.png', 'desktop': True, 'bundle_id': 'org.x', 'check': True}
    main(['shortcut', 'add', '-w', 'napari-foo', '--no-check'])
    assert calls[1][2]['check'] is False


def test_failed_check_names_the_escape(monkeypatch, capsys):
    def fail(name, widgets, **kw):
        raise _shortcut.PluginCheckError("napari-foo has no widget called 'Foo'. Its widgets: 'Foo widget'")

    monkeypatch.setattr(_shortcut, 'create_shortcut', fail)
    assert _exit_code(['shortcut', 'add', '-w', 'napari-foo', 'Foo']) == 1
    assert capsys.readouterr().err == (
        "adding the shortcut failed: napari-foo has no widget called 'Foo'. Its widgets: 'Foo widget'\n"
        'To add the shortcut anyway, pass --no-check\n'
    )


def test_two_plugins_need_a_name(calls, capsys):
    assert _exit_code(['shortcut', 'add', '-w', 'a', '-w', 'b']) == 2
    assert 'pass --name' in capsys.readouterr().err


@pytest.mark.parametrize('argv', [['--name', 'napari-foo'], ['-w', 'napari-foo'], ['-w', 'napari-foo', 'Foo widget']])
def test_remove(calls, capsys, argv):
    assert main(['shortcut', 'remove', *argv]) == 0
    assert calls == ['napari-foo']
    assert capsys.readouterr().out == 'removed a\n'


def test_remove_needs_a_name(calls, capsys):
    assert _exit_code(['shortcut', 'remove']) == 2
    assert 'pass --name, or -w with the plugin' in capsys.readouterr().err
    assert calls == []


@pytest.mark.parametrize(
    'argv',
    [
        ['shortcut'],
        ['shortcut', '-w', 'napari-foo'],
        ['shortcut', 'remove', '--name', 'Foo', '--icon', 'icon.png'],
        ['shortcut', 'remove', '--name', 'Foo', '--no-desktop'],
        ['shortcut', 'remove', '--name', 'Foo', '--no-check'],
        ['launch', '--name', 'Foo'],
    ],
)
def test_options_only_where_they_apply(calls, argv):
    assert _exit_code(argv) == 2
    assert calls == []


def test_version(capsys):
    assert _exit_code(['--version']) == 0
    assert capsys.readouterr().out == f'napari-launcher {napari_launcher.__version__}\n'


def test_shortcut_failure(monkeypatch, capsys):
    def fail(name, widgets, **kw):
        raise OSError('read-only file system')

    monkeypatch.setattr(_shortcut, 'create_shortcut', fail)
    assert _exit_code(['shortcut', 'add']) == 1
    assert 'adding the shortcut failed: read-only file system' in capsys.readouterr().err


def test_warnings_are_short(monkeypatch, capsys):
    def warn(name, widgets, **kw):
        warnings.warn('no icon', stacklevel=1)
        return ['a']

    monkeypatch.setattr(_shortcut, 'create_shortcut', warn)
    assert main(['shortcut', 'add']) == 0
    assert capsys.readouterr().err == 'warning: no icon\n'


@pytest.mark.parametrize(
    ('argv', 'expected'),
    [
        (['launch'], ['--']),
        (['launch', 'a.tif'], ['--', 'a.tif']),
        (
            ['launch', '-w', 'napari-foo', 'Foo widget', '--', 'a.tif', 'b.tif'],
            ['-w', 'napari-foo', 'Foo widget', '--', 'a.tif', 'b.tif'],
        ),
        (['launch', '-w', 'a', '-w', 'b', 'B1', 'B2', '--'], ['-w', 'a', '-w', 'b', 'B1', 'B2', '--']),
    ],
)
def test_launch(napari_argv, argv, expected):
    main(argv)
    assert napari_argv == expected


def test_launch_api_takes_plugin_names(napari_argv):
    napari_launcher.launch(['napari-foo', ('napari-bar', 'Bar')], ['a.tif'])
    assert napari_argv == ['-w', 'napari-foo', '-w', 'napari-bar', 'Bar', '--', 'a.tif']


def test_launch_api_takes_single_strings(napari_argv):
    napari_launcher.launch('napari-foo', 'a.tif')
    assert napari_argv == ['-w', 'napari-foo', '--', 'a.tif']


@pytest.fixture
def log(monkeypatch, tmp_path):
    """where the log goes"""
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    return tmp_path / 'napari-launcher' / 'logs' / 'launch.log'


def _launch_without_console(monkeypatch):
    """`napari-launcher launch` with no stdout or stderr, as under pythonw.exe"""
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    try:
        return main(['launch'])
    finally:
        sys.stdout.close()


def test_output_goes_to_log_without_console(monkeypatch, log):
    import napari.__main__

    def napari_main():
        print('to stdout')
        print('to stderr', file=sys.stderr)

    monkeypatch.setattr(napari.__main__, 'main', napari_main)
    monkeypatch.setattr(sys, 'argv', sys.argv[:])
    log.parent.mkdir(parents=True)
    log.write_text('from the last start\n')
    _launch_without_console(monkeypatch)
    assert log.read_text() == 'to stdout\nto stderr\n'


def test_startup_error_without_console(monkeypatch, log):
    import napari.__main__

    def napari_main():
        raise RuntimeError('no Qt platform plugin')

    shown = []
    monkeypatch.setattr(napari.__main__, 'main', napari_main)
    monkeypatch.setattr(sys, 'argv', sys.argv[:])
    monkeypatch.setattr(_launch, 'show_error', lambda error, log: shown.append((str(error), log)))
    assert _launch_without_console(monkeypatch) == 1
    assert shown == [('no Qt platform plugin', log)]
    assert 'RuntimeError: no Qt platform plugin' in log.read_text()


def test_startup_error_with_console(monkeypatch):
    import napari.__main__

    def napari_main():
        raise RuntimeError('no Qt platform plugin')

    monkeypatch.setattr(napari.__main__, 'main', napari_main)
    monkeypatch.setattr(sys, 'argv', sys.argv[:])
    with pytest.raises(RuntimeError):
        main(['launch'])


def test_error_dialog(monkeypatch, tmp_path):
    widgets = pytest.importorskip('qtpy.QtWidgets')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    shown = []
    monkeypatch.setattr(widgets.QMessageBox, 'critical', lambda parent, title, text: shown.append((title, text)))
    _launch.show_error(RuntimeError('broken'), tmp_path / 'launch.log')
    assert shown == [('napari did not start', f'broken\n\nThe details are in {tmp_path / "launch.log"}')]
