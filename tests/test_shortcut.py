import plistlib
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import parse_exec

from napari_launcher import _icons, _shortcut, create_shortcut, remove_shortcut, shortcut_paths

PYTHON = '/opt/my env/bin/python'
_REAL_INSTALLED_WIDGETS = _shortcut._installed_widgets
WIDGETS = [('napari-foo', 'Foo widget')]


def _keys(entry):
    return dict(line.split('=', 1) for line in entry.read_text().splitlines()[1:])


@pytest.fixture
def linux(monkeypatch, home):
    """Linux, with a desktop folder"""
    monkeypatch.setattr(sys, 'platform', 'linux')
    (home / 'Desktop').mkdir()


@pytest.fixture
def macos(monkeypatch, home):
    if sys.platform == 'win32':
        pytest.skip('symbolic links need extra rights on Windows')
    monkeypatch.setattr(sys, 'platform', 'darwin')


@pytest.fixture
def windows(monkeypatch, tmp_path, home):
    """Windows, with the known folders in tmp_path and a PowerShell that keeps .lnk arguments as text"""
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'AppData' / 'Local'))
    monkeypatch.setattr(_shortcut, '_windows_folder', lambda name: tmp_path / name)
    writes = []

    def powershell(script, **values):
        lnk = Path(values['SHORTCUT_LNK'])
        if script == _shortcut.LNK_READ:
            return lnk.read_text()
        writes.append(values)
        lnk.write_text(values['SHORTCUT_ARGS'])
        return ''

    monkeypatch.setattr(_shortcut, '_powershell', powershell)
    return writes


@pytest.fixture(autouse=True)
def napari_icon(monkeypatch, tmp_path):
    """napari's icon in every format, whichever files the installed napari has"""
    folder = tmp_path / 'napari-icon'
    folder.mkdir()
    icons = []
    for suffix in ('.svg', '.ico', '.icns'):
        icons.append(folder / f'icon{suffix}')
        icons[-1].write_bytes(b'icon')
    monkeypatch.setattr(_icons, 'napari_icons', lambda: iter(icons))


@pytest.fixture
def no_napari_icon(monkeypatch):
    monkeypatch.setattr(_icons, 'napari_icons', lambda: iter(()))


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    """the plugins and widgets every Python has; returns the interpreters asked"""
    asked = []

    def installed_widgets(python):
        asked.append(python)
        return {'napari-foo': ['Foo widget', "It's 50%"], 'napari-bar': ['Bar'], 'napari-svg': []}

    monkeypatch.setattr(_shortcut, '_installed_widgets', installed_widgets)
    return asked


@pytest.mark.parametrize(
    'name', ['', ' padded', 'padded ', '.hidden', 'dot.', 'a/b', 'a:b', 'tab\there', 'CON', 'nul.txt', 'Com1', 'lpt9']
)
def test_unusable_names(name, home):
    with pytest.raises(ValueError, match='does not work as a shortcut name. Use letters'):
        shortcut_paths(name)


@pytest.mark.parametrize('name', ['CONSOLE', 'COM10', 'My App 2.0', 'Zellzählung'])
def test_usable_names(name, linux):
    assert shortcut_paths(name)[0].stem == name


@pytest.mark.parametrize('desktop', [True, False])
def test_linux_create_and_remove(linux, home, desktop):
    paths = create_shortcut('Foo', WIDGETS, python=PYTHON, desktop=desktop)
    assert paths == shortcut_paths('Foo', desktop)
    assert paths[0] == home / '.local' / 'share' / 'applications' / 'Foo.desktop'
    assert paths[1:] == ([home / 'Desktop' / 'Foo.desktop'] if desktop else [])
    icon = home / '.local' / 'share' / 'napari-launcher' / 'icons' / 'Foo.svg'
    assert all(p.is_file() for p in paths) and icon.is_file()

    assert remove_shortcut('Foo') == [*paths, icon]
    assert not any(p.exists() for p in [*paths, icon])
    assert not icon.parent.parent.exists()
    assert remove_shortcut('Foo') == []


def test_remove_keeps_icons_of_other_shortcuts(linux, home):
    create_shortcut('Foo')
    create_shortcut('Bar')
    remove_shortcut('Foo')
    assert (home / '.local' / 'share' / 'napari-launcher' / 'icons' / 'Bar.svg').is_file()


def test_linux_desktop_entry(linux, home):
    entry, _ = create_shortcut('Foo', WIDGETS, python=PYTHON, comment='segments\nthings')
    keys = _keys(entry)
    assert keys['Name'] == 'Foo'
    assert keys['Comment'] == 'segments things'
    assert (
        keys['Exec']
        == '"/opt/my env/bin/python" "-m" "napari_launcher" "launch" "-w" "napari-foo" "Foo widget" "--" %F'
    )
    assert keys['Icon'] == str(home / '.local' / 'share' / 'napari-launcher' / 'icons' / 'Foo.svg')
    assert keys['X-Napari-Launcher'] == 'true'


def test_linux_exec_escaping(linux):
    python = '/opt/a "b" `c` $d \\e 100%/python'
    entry, _ = create_shortcut('Foo', [('napari-foo', "It's 50%")], python=python)
    exec_line = next(line for line in entry.read_text().splitlines() if line.startswith('Exec='))[5:]
    assert parse_exec(exec_line) == [
        python,
        '-m',
        'napari_launcher',
        'launch',
        '-w',
        'napari-foo',
        "It's 50%",
        '--',
        '%F',
    ]


def test_bare_plugin_name(linux):
    entry, _ = create_shortcut('Foo', 'napari-foo', python=PYTHON)
    assert _keys(entry)['Exec'].endswith('"launch" "-w" "napari-foo" "--" %F')
    assert _keys(entry)['Comment'] == 'napari with napari-foo'


def test_xdg_data_home(linux, home, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    entry, desktop = create_shortcut('Foo')
    assert entry == tmp_path / 'data' / 'applications' / 'Foo.desktop'
    assert (tmp_path / 'data' / 'napari-launcher' / 'icons' / 'Foo.svg').is_file()
    assert desktop == home / 'Desktop' / 'Foo.desktop'


@pytest.mark.parametrize(('xdg_config_home', 'home_var'), [(False, '$HOME'), (True, '$HOME'), (False, '${HOME}')])
def test_linux_desktop_from_user_dirs(linux, home, tmp_path, monkeypatch, xdg_config_home, home_var):
    config = tmp_path / 'config' if xdg_config_home else home / '.config'
    if xdg_config_home:
        monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    config.mkdir()
    (config / 'user-dirs.dirs').write_text(f'# from xdg-user-dirs-update\nXDG_DESKTOP_DIR="{home_var}/Schreibtisch"\n')
    (home / 'Schreibtisch').mkdir()
    assert shortcut_paths('Foo')[1] == home / 'Schreibtisch' / 'Foo.desktop'


def test_linux_without_desktop_folder(linux, home):
    (home / 'Desktop').rmdir()
    assert create_shortcut('Foo') == [home / '.local' / 'share' / 'applications' / 'Foo.desktop']
    assert not (home / 'Desktop').exists()


def test_linux_desktop_disabled_in_user_dirs(linux, home):
    (home / '.config').mkdir()
    (home / '.config' / 'user-dirs.dirs').write_text('XDG_DESKTOP_DIR="$HOME/"\n')
    assert len(shortcut_paths('Foo')) == 1


def test_linux_shortcut_without_icon(linux, no_napari_icon):
    with pytest.warns(UserWarning, match='the shortcut has no icon'):
        entry, _ = create_shortcut('Foo')
    assert 'Icon' not in _keys(entry)


def test_linux_recreate_replaces_own_shortcut(linux):
    create_shortcut('Foo', comment='one')
    entry, _ = create_shortcut('Foo', comment='two')
    assert _keys(entry)['Comment'] == 'two'


def test_linux_leaves_other_files_alone(linux, home):
    other = home / 'Desktop' / 'Foo.desktop'
    other.write_text('[Desktop Entry]\nName=Foo\n')
    with pytest.raises(FileExistsError, match='was not made by napari-launcher, so it is not replaced'):
        create_shortcut('Foo')
    assert not shortcut_paths('Foo')[0].exists()
    with pytest.raises(FileExistsError, match='so it is not deleted'):
        remove_shortcut('Foo')
    assert other.read_text() == '[Desktop Entry]\nName=Foo\n'


def test_windows_create_and_remove(windows, tmp_path):
    menu, desktop = create_shortcut('Foo', WIDGETS, python=r'C:\env\python.exe')
    assert menu == tmp_path / 'Programs' / 'Foo.lnk'
    assert desktop == tmp_path / 'Desktop' / 'Foo.lnk'
    icon = tmp_path / 'AppData' / 'Local' / 'napari-launcher' / 'icons' / 'Foo.ico'
    assert icon.stat().st_size > 0
    values = windows[0]
    assert values['SHORTCUT_TARGET'] == r'C:\env\python.exe'
    assert values['SHORTCUT_ARGS'] == '-m napari_launcher launch -w napari-foo "Foo widget" --'
    assert values['SHORTCUT_ICON'] == str(icon)
    assert values['SHORTCUT_COMMENT'] == 'napari with napari-foo'

    assert remove_shortcut('Foo') == [menu, desktop, icon]
    assert not (tmp_path / 'AppData' / 'Local' / 'napari-launcher').exists()


def test_windows_prefers_pythonw(windows, tmp_path):
    python = tmp_path / 'env' / 'python.exe'
    python.parent.mkdir()
    (python.parent / 'pythonw.exe').touch()
    create_shortcut('Foo', python=python, desktop=False)
    assert windows[0]['SHORTCUT_TARGET'] == str(python.parent / 'pythonw.exe')


def test_windows_shortcut_without_icon(windows, no_napari_icon):
    with pytest.warns(UserWarning, match='the shortcut has no icon'):
        create_shortcut('Foo', desktop=False)
    assert windows[0]['SHORTCUT_ICON'] == ''


def test_windows_leaves_other_shortcuts_alone(windows, tmp_path):
    other = tmp_path / 'Desktop' / 'Foo.lnk'
    other.parent.mkdir()
    other.write_text('-jar foo.jar')
    with pytest.raises(FileExistsError, match='so it is not replaced'):
        create_shortcut('Foo')
    with pytest.raises(FileExistsError, match='so it is not deleted'):
        remove_shortcut('Foo')
    assert other.read_text() == '-jar foo.jar'


def test_powershell_env_drops_powershell_7_modules():
    environ = {
        'Path': r'C:\Windows',
        'PSMODULEPATH': r'C:\Users\Zoë\Documents\PowerShell\Modules;C:\Program Files\PowerShell\7\Modules;'
        r'C:\Program Files\WindowsPowerShell\Modules;C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules',
    }
    env = _shortcut._powershell_env(environ, {'SHORTCUT_LNK': 'a.lnk'})
    assert env == {
        'Path': r'C:\Windows',
        'PSMODULEPATH': r'C:\Program Files\WindowsPowerShell\Modules;C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules',
        'SHORTCUT_LNK': 'a.lnk',
    }
    assert 'PSModulePath' not in _shortcut._powershell_env({'PSModulePath': r'C:\x\PowerShell\Modules'}, {})


def test_powershell_command_and_output(monkeypatch):
    monkeypatch.setenv('SystemRoot', 'Windows')
    runs = []

    def run(command, env, capture_output, check):
        runs.append((command, env))
        return subprocess.CompletedProcess(command, 0, 'C:\\Users\\Zoë\\Desktop\r\n'.encode(), b'')

    monkeypatch.setattr(_shortcut.subprocess, 'run', run)
    assert _shortcut._powershell('Write-Output $env:X', X='1') == 'C:\\Users\\Zoë\\Desktop'
    ((command, env),) = runs
    assert command[0] == str(Path('Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'))
    assert command[-1].endswith('; Write-Output $env:X') and 'UTF8Encoding' in command[-1]
    assert env['X'] == '1'


def test_powershell_failure(monkeypatch):
    failed = subprocess.CompletedProcess([], 1, b'', 'Zugriff verweigert: Zoë'.encode())
    monkeypatch.setattr(_shortcut.subprocess, 'run', lambda command, env, capture_output, check: failed)
    with pytest.raises(OSError, match='PowerShell failed: Zugriff verweigert: Zoë'):
        _shortcut._powershell('Write-Error x')


def test_macos_app(macos, home):
    app, desktop = create_shortcut('Foo Bar', WIDGETS, python=PYTHON)
    assert app == home / 'Applications' / 'Foo Bar.app'
    contents = app / 'Contents'
    with open(contents / 'Info.plist', 'rb') as f:
        info = plistlib.load(f)
    assert info['CFBundleIdentifier'] == 'local.napari-launcher.Foo-Bar'
    assert info['NapariLauncher'] is True
    launcher = contents / 'MacOS' / info['CFBundleExecutable']
    assert launcher.read_text() == (
        "#!/bin/sh\nexec '/opt/my env/bin/python' -m napari_launcher launch -w napari-foo 'Foo widget' -- \"$@\"\n"
    )
    assert launcher.stat().st_mode & 0o111
    assert (contents / 'Resources' / info['CFBundleIconFile']).is_file()
    assert desktop.is_symlink() and desktop.resolve() == app.resolve()

    assert remove_shortcut('Foo Bar') == [app, desktop]
    assert not app.exists() and not desktop.is_symlink()


def test_macos_recreate_replaces_own_app(macos):
    app, _ = create_shortcut('Foo')
    (app / 'Contents' / 'Resources' / 'stale').touch()
    create_shortcut('Foo')
    assert not (app / 'Contents' / 'Resources' / 'stale').exists()


def test_macos_app_without_icon(macos, no_napari_icon):
    with pytest.warns(UserWarning, match='the shortcut has no icon'):
        app, _ = create_shortcut('Foo')
    with open(app / 'Contents' / 'Info.plist', 'rb') as f:
        assert 'CFBundleIconFile' not in plistlib.load(f)


def test_macos_leaves_other_apps_alone(macos, home, tmp_path):
    other = home / 'Applications' / 'Foo.app' / 'Contents'
    other.mkdir(parents=True)
    with open(other / 'Info.plist', 'wb') as f:
        plistlib.dump({'CFBundleIdentifier': 'org.example.foo'}, f)
    with pytest.raises(FileExistsError, match='so it is not replaced'):
        create_shortcut('Foo')
    with pytest.raises(FileExistsError, match='so it is not deleted'):
        remove_shortcut('Foo')
    assert (other / 'Info.plist').is_file()


def test_macos_leaves_other_desktop_links_alone(macos, home, tmp_path):
    link = home / 'Desktop' / 'Foo.app'
    link.parent.mkdir()
    link.symlink_to(tmp_path / 'elsewhere' / 'Foo.app')
    with pytest.raises(FileExistsError, match='so it is not replaced'):
        create_shortcut('Foo')
    assert create_shortcut('Foo', desktop=False)
    with pytest.raises(FileExistsError, match='so it is not deleted'):
        remove_shortcut('Foo')
    assert link.is_symlink()


@pytest.mark.skipif(sys.platform != 'darwin', reason='sips is on macOS only')
def test_macos_bundle_id_and_png_icon(home, tmp_path):
    from conftest import make_png

    icon = tmp_path / 'icon.png'
    icon.write_bytes(make_png(512, 512))
    (app,) = create_shortcut('Foo', icon=icon, desktop=False, bundle_id='org.example.foo')
    with open(app / 'Contents' / 'Info.plist', 'rb') as f:
        assert plistlib.load(f)['CFBundleIdentifier'] == 'org.example.foo'
    assert (app / 'Contents' / 'Resources' / 'icon.icns').read_bytes()[:4] == b'icns'


def test_checks_widgets_in_the_shortcut_python(linux, installed):
    create_shortcut('Foo', [('napari-foo', 'Foo widget', "It's 50%"), ('napari-bar', '__all__')], python=PYTHON)
    create_shortcut('Bar', 'napari-bar', python=PYTHON)
    assert installed == [PYTHON, PYTHON]


@pytest.mark.parametrize(
    ('widgets', 'message'),
    [
        (
            'napari-baz',
            "no plugin called 'napari-baz' is installed for .*Plugins with widgets: napari-bar, napari-foo$",
        ),
        (
            [('napari-foo', 'foo widget')],
            "napari-foo has no widget called 'foo widget'. Its widgets: 'Foo widget', \"It's",
        ),
        ([('napari-bar', 'Bar', 'Baz')], "napari-bar has no widget called 'Baz'"),
        ('napari-svg', 'napari-svg has no widgets to dock'),
    ],
)
def test_refuses_unknown_widgets(linux, widgets, message):
    with pytest.raises(_shortcut.PluginCheckError, match=message):
        create_shortcut('Foo', widgets, python=PYTHON)
    assert not any(path.exists() for path in shortcut_paths('Foo'))


def test_no_plugins_with_widgets(linux, monkeypatch):
    monkeypatch.setattr(_shortcut, '_installed_widgets', lambda python: {'napari': []})
    with pytest.raises(ValueError, match='No installed plugin has widgets'):
        create_shortcut('Foo', 'napari-foo')


def test_check_can_be_skipped(linux, installed):
    create_shortcut('Foo', 'napari-baz', check=False)
    create_shortcut('napari')
    assert installed == []


def test_installed_widgets_of_this_python():
    # napari's own manifest is always there
    assert 'napari' in _REAL_INSTALLED_WIDGETS(sys.executable)


def test_installed_widgets_failures(monkeypatch, tmp_path):
    with pytest.raises(_shortcut.PluginCheckError, match='could not run .*missing.* to list its plugins'):
        _REAL_INSTALLED_WIDGETS(tmp_path / 'missing' / 'python')
    monkeypatch.setattr(_shortcut, 'WIDGETS_SCRIPT', 'import sys; print("noise"); sys.exit("no npe2 here")')
    with pytest.raises(_shortcut.PluginCheckError, match='could not list the plugins installed for .*: no npe2 here$'):
        _REAL_INSTALLED_WIDGETS(sys.executable)


def test_bad_widget_group(linux):
    with pytest.raises(ValueError, match='a widget group'):
        create_shortcut('Foo', [()])


windows_only = pytest.mark.skipif(sys.platform != 'win32', reason='needs Windows')


@windows_only
@pytest.mark.parametrize('name', ['Desktop', 'Programs'])
def test_windows_known_folders(name):
    expected = _shortcut._powershell(f"[Environment]::GetFolderPath('{name}')")
    assert _shortcut._windows_folder(name) == Path(expected)


@windows_only
def test_windows_powershell_keeps_non_ascii():
    text = 'Zoë Ødegård 日本'
    assert _shortcut._powershell('Write-Output $env:TEXT', TEXT=text) == text


@windows_only
def test_windows_real_lnk(monkeypatch, tmp_path, home):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'AppData' / 'Local'))
    monkeypatch.setattr(_shortcut, '_windows_folder', lambda name: tmp_path / 'Zoë' / name)
    menu, desktop = create_shortcut('Zellzählung', WIDGETS)
    assert menu.read_bytes()[:4] == b'L\x00\x00\x00' and desktop.is_file()
    assert _shortcut._marked(menu)
    assert remove_shortcut('Zellzählung')[:2] == [menu, desktop]


@windows_only
def test_windows_real_lnk_of_another_app(monkeypatch, tmp_path, home):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'AppData' / 'Local'))
    monkeypatch.setattr(_shortcut, '_windows_folder', lambda name: tmp_path / name)
    other = tmp_path / 'Programs' / 'Foo.lnk'
    other.parent.mkdir()
    _shortcut._write_lnk(other, [sys.executable, '-c', 'pass'], None, 'another app')
    with pytest.raises(FileExistsError, match='so it is not replaced'):
        create_shortcut('Foo')
    assert other.is_file()
