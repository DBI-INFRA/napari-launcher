"""
app menu and desktop shortcuts that start napari with plugin widgets docked

A shortcut runs `python -m napari_launcher launch -w ...` with the Python it was made with, so it
works in any environment that has napari and napari-launcher. Before it makes a shortcut,
napari-launcher asks that Python which plugins and widgets it has. Every shortcut carries a mark,
and napari-launcher only replaces or deletes shortcuts with that mark.
"""

import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from xml.parsers.expat import ExpatError

from . import _icons
from ._launch import data_folder, widget_groups, with_args

# characters Windows, macOS or a .desktop file name can't hold
UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# device names Windows keeps for itself, also when followed by an extension
RESERVED_NAME = re.compile(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', re.IGNORECASE)
ICON_SUFFIXES = ('.ico', '.png', '.svg')
# the marks of a shortcut made by napari-launcher
DESKTOP_MARK = 'X-Napari-Launcher=true'
PLIST_MARK = 'NapariLauncher'
LNK_MARK = '-m napari_launcher'
KNOWN_FOLDERS = {
    'Desktop': 'B4BFCC3A-DB2C-424C-B029-7FE99A87C641',
    'Programs': 'A77F5D77-2E2B-44C3-A6A2-ABA601054A51',
}
# values reach PowerShell through the environment, so no quoting can break them
LNK_WRITE = (
    '$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SHORTCUT_LNK); '
    '$s.TargetPath = $env:SHORTCUT_TARGET; $s.Arguments = $env:SHORTCUT_ARGS; '
    '$s.WorkingDirectory = $env:USERPROFILE; $s.Description = $env:SHORTCUT_COMMENT; '
    'if ($env:SHORTCUT_ICON) { $s.IconLocation = $env:SHORTCUT_ICON }; $s.Save()'
)
LNK_READ = '(New-Object -ComObject WScript.Shell).CreateShortcut($env:SHORTCUT_LNK).Arguments'
# prints {plugin name: [widget display names]} for the npe2 plugins of the Python that runs it, as
# napari's -w sees them; output from the plugins themselves goes to stderr
WIDGETS_SCRIPT = """\
import json, sys
from npe2 import PluginManager
out, sys.stdout = sys.stdout, sys.stderr
manager = PluginManager()
manager.discover()
widgets = {m.name: [w.display_name for w in m.contributions.widgets or ()] for m in manager.iter_manifests()}
out.write(json.dumps(widgets))
"""


class PluginCheckError(ValueError):
    """the plugins or widgets a shortcut would dock are not installed, or the check could not run"""


def _check_name(name):
    if (
        not name
        or name != name.strip()
        or name.startswith('.')
        or name.endswith('.')
        or UNSAFE_NAME.search(name)
        or RESERVED_NAME.fullmatch(name)
    ):
        raise ValueError(
            f'{name!r} does not work as a shortcut name. Use letters, digits, spaces and punctuation other '
            'than \\ / : * ? " < > |, with no space or dot at either end, and not a Windows device name '
            'such as CON, NUL, COM1 or LPT1'
        )


def _command(python, widgets):
    # `--` ends the last `-w`, so files dropped on the shortcut on Windows and Linux open as files
    return [str(python), '-m', 'napari_launcher', 'launch', *with_args(widgets), '--']


def _installed_widgets(python):
    """{plugin name: [widget display names]} for the npe2 plugins installed for `python`"""
    try:
        result = subprocess.run([str(python), '-c', WIDGETS_SCRIPT], capture_output=True, check=False)
    except OSError as e:
        raise PluginCheckError(f'could not run {python} to list its plugins: {e.strerror or e}') from e
    if result.returncode:
        error = result.stderr.decode('utf-8', errors='replace').strip()
        reason = error.splitlines()[-1] if error else f'exit code {result.returncode}'
        raise PluginCheckError(f'could not list the plugins installed for {python}: {reason}')
    return json.loads(result.stdout)


def _check_widgets(groups, python):
    """raise PluginCheckError unless `python` has each plugin in `groups` and the widgets named for it"""
    installed = _installed_widgets(python)
    for plugin, *names in groups:
        widgets = installed.get(plugin)
        if widgets is None:
            usable = sorted(name for name, found in installed.items() if found)
            raise PluginCheckError(
                f'no plugin called {plugin!r} is installed for {python}. '
                + (f'Plugins with widgets: {", ".join(usable)}' if usable else 'No installed plugin has widgets')
            )
        if not widgets:
            raise PluginCheckError(f'{plugin} has no widgets to dock')
        for name in names:
            if name != '__all__' and name not in widgets:
                raise PluginCheckError(
                    f'{plugin} has no widget called {name!r}. Its widgets: {", ".join(map(repr, widgets))}'
                )


def _windows_folder(name):
    """a Windows known folder such as Desktop or Programs, wherever the user has moved it"""
    import ctypes

    folder_id = ctypes.create_string_buffer(uuid.UUID(KNOWN_FOLDERS[name]).bytes_le, 16)
    path = ctypes.c_wchar_p()
    error = ctypes.windll.shell32.SHGetKnownFolderPath(folder_id, 0, None, ctypes.byref(path))
    try:
        if error:
            raise OSError(f'Windows did not give the {name} folder (error {error & 0xFFFFFFFF:#010x})')
        return Path(path.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)


def _powershell_env(environ, values):
    """`environ` plus `values`, without the PowerShell 7 module folders that break Windows PowerShell"""
    env = {**environ, **values}
    key = next((key for key in env if key.upper() == 'PSMODULEPATH'), None)
    if key:
        folders = [f for f in env.pop(key).split(';') if f and not re.search(r'\\PowerShell\\', f, re.IGNORECASE)]
        if folders:
            env[key] = ';'.join(folders)
    return env


def _powershell(script, **values):
    """run `script` in Windows PowerShell, which reads `values` as `$env:NAME`; returns its output"""
    exe = Path(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    # UTF-8 output whatever the console code page, so non-ASCII paths survive; setting it fails without a console
    script = (
        "$ErrorActionPreference = 'Stop'; "
        'try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch {}; ' + script
    )
    result = subprocess.run(
        [str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
        env=_powershell_env(os.environ, values),
        capture_output=True,
        check=False,
    )
    out, err = (stream.decode('utf-8-sig', errors='replace').strip() for stream in (result.stdout, result.stderr))
    if result.returncode:
        raise OSError(f'PowerShell failed: {err or out}')
    return out


def _linux_desktop():
    """the desktop folder set in user-dirs.dirs, else ~/Desktop; None if it does not exist"""
    home = Path.home()
    folder = home / 'Desktop'
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'user-dirs.dirs'
    if config.is_file():
        text = config.read_text(encoding='utf-8', errors='replace')
        match = re.search(r'^XDG_DESKTOP_DIR="(.*)"', text, re.MULTILINE)
        if match:
            folder = Path(re.sub(r'\$\{HOME\}|\$HOME\b', lambda _: str(home), match.group(1)))
    # a desktop folder set to the home folder means no desktop
    return folder if folder != home and folder.is_dir() else None


def _icon_folder():
    """where Windows and Linux shortcuts keep their icon, so it outlives the file it came from"""
    return data_folder() / 'icons'


def shortcut_paths(name, desktop=True):
    """where the shortcuts called `name` go on this platform: the app menu first, then the desktop"""
    _check_name(name)
    home = Path.home()
    if sys.platform == 'win32':
        folders = ['Programs'] + (['Desktop'] if desktop else [])
        return [_windows_folder(folder) / f'{name}.lnk' for folder in folders]
    if sys.platform == 'darwin':
        return [home / 'Applications' / f'{name}.app'] + ([home / 'Desktop' / f'{name}.app'] if desktop else [])
    data = Path(os.environ.get('XDG_DATA_HOME') or home / '.local' / 'share')
    folder = _linux_desktop() if desktop else None
    return [data / 'applications' / f'{name}.desktop'] + ([folder / f'{name}.desktop'] if folder else [])


def _exists(path):
    return path.is_symlink() or path.exists()


def _marked(path):
    """whether the shortcut at `path` has napari-launcher's mark"""
    if path.suffix == '.lnk':
        return path.is_file() and _powershell(LNK_READ, SHORTCUT_LNK=str(path)).startswith(LNK_MARK)
    if path.suffix == '.desktop':
        return path.is_file() and DESKTOP_MARK in path.read_text(encoding='utf-8', errors='replace').splitlines()
    if path.is_symlink():
        # a desktop link to the app of the same name in ~/Applications
        return Path(os.readlink(path)) == Path.home() / 'Applications' / path.name
    try:
        with open(path / 'Contents' / 'Info.plist', 'rb') as f:
            info = plistlib.load(f)
    except (OSError, ValueError, ExpatError):  # no Info.plist, or not a valid one
        return False
    return isinstance(info, dict) and info.get(PLIST_MARK) is True


def _check_marked(paths, action):
    for path in paths:
        if _exists(path) and not _marked(path):
            raise FileExistsError(f'{path} was not made by napari-launcher, so it is not {action}')


def _write_lnk(path, command, icon, comment):
    # pythonw: no console window behind napari
    python, *args = command
    pythonw = Path(python).with_name('pythonw.exe')
    path.parent.mkdir(parents=True, exist_ok=True)
    _powershell(
        LNK_WRITE,
        SHORTCUT_LNK=str(path),
        SHORTCUT_TARGET=str(pythonw if pythonw.exists() else python),
        SHORTCUT_ARGS=subprocess.list2cmdline(args),
        SHORTCUT_ICON=str(icon or ''),
        SHORTCUT_COMMENT=comment,
    )


def _bundle_id(name):
    slug = re.sub(r'[^A-Za-z0-9-]+', '-', name).strip('-') or 'app'
    return f'local.napari-launcher.{slug}'


def _write_app(app, command, icon, bundle_id):
    name = app.stem
    contents = app / 'Contents'
    (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
    launcher = contents / 'MacOS' / name
    launcher.write_text(f'#!/bin/sh\nexec {shlex.join(command)} "$@"\n', encoding='utf-8')
    launcher.chmod(0o755)
    icns = _icons.install(icon, contents / 'Resources', 'icon', ('.icns',))
    info = {
        'CFBundleName': name,
        'CFBundleDisplayName': name,
        'CFBundleExecutable': name,
        'CFBundleIdentifier': bundle_id or _bundle_id(name),
        'CFBundlePackageType': 'APPL',
        'NSHighResolutionCapable': True,
        PLIST_MARK: True,
    }
    if icns:
        info['CFBundleIconFile'] = icns.name
    with open(contents / 'Info.plist', 'wb') as f:
        plistlib.dump(info, f)


def _exec_arg(arg):
    """one argument of a .desktop Exec key, quoted and escaped as the Desktop Entry spec asks"""
    quoted = re.sub(r'(["`$\\])', r'\\\1', arg).replace('%', '%%')
    # the general string escaping applies on top of the Exec quoting
    return '"' + quoted.replace('\\', '\\\\') + '"'


def _write_desktop_entry(path, command, icon, comment):
    path.parent.mkdir(parents=True, exist_ok=True)
    exec_line = ' '.join(map(_exec_arg, command))
    path.write_text(
        '[Desktop Entry]\nType=Application\n'
        f'Name={path.stem}\nComment={comment}\nExec={exec_line} %F\n'
        + (f'Icon={icon}\n' if icon else '')
        + f'Terminal=false\nStartupWMClass=napari\nCategories=Science;Graphics;\n{DESKTOP_MARK}\n',
        encoding='utf-8',
    )
    path.chmod(0o755)
    # GNOME only starts desktop-folder launchers that are marked trusted
    if shutil.which('gio'):
        subprocess.run(['gio', 'set', str(path), 'metadata::trusted', 'true'], capture_output=True, check=False)


def create_shortcut(
    name, widgets=(), *, comment=None, icon=None, desktop=True, python=sys.executable, bundle_id=None, check=True
):
    """
    add shortcuts called `name` that start napari with `widgets` docked; returns their paths

    widgets: a plugin name, or a list of plugin names and (plugin, *widget names) tuples, as napari's
        `-w` takes them. Widget names are the display names in napari's Plugins menu.
    icon: a .png works everywhere; also an .ico (Windows), .icns (macOS), .svg (Linux), as a path or
        `package:path/in/package`. Default: napari's icon.
    desktop: also put a shortcut on the desktop
    python: the interpreter the shortcut runs; it needs napari and napari-launcher
    bundle_id: the macOS CFBundleIdentifier, by default made from the name
    check: first run `python` to check that it has each plugin, and the widgets named for it

    Raises PluginCheckError, a ValueError, if the check finds a plugin or widget missing or cannot run,
    and FileExistsError if a file in the way was not made by napari-launcher.
    """
    paths = shortcut_paths(name, desktop)
    groups = widget_groups(widgets)
    command = _command(python, groups)
    if check and groups:
        _check_widgets(groups, python)
    plugins = [group[0] for group in groups]
    comment = ' '.join((comment or (f'napari with {", ".join(plugins)}' if plugins else 'napari')).split())
    _check_marked(paths, 'replaced')
    if sys.platform == 'win32':
        icon_file = _icons.install(icon, _icon_folder(), name, ('.ico',))
        for path in paths:
            _write_lnk(path, command, icon_file, comment)
    elif sys.platform == 'darwin':
        app, *links = paths
        if app.is_dir():
            shutil.rmtree(app)
        _write_app(app, command, icon, bundle_id)
        for link in links:
            # a link to the app, so the Dock and Launchpad see one app
            link.parent.mkdir(parents=True, exist_ok=True)
            link.unlink(missing_ok=True)
            link.symlink_to(app)
    else:
        icon_file = _icons.install(icon, _icon_folder(), name, ('.svg', '.png'))
        for path in paths:
            _write_desktop_entry(path, command, icon_file, comment)
    return paths


def remove_shortcut(name):
    """
    delete the shortcuts and icon that create_shortcut() made for `name`; returns the paths that existed

    Raises FileExistsError, and deletes nothing, if one of the shortcuts was not made by napari-launcher.
    """
    paths = [path for path in shortcut_paths(name) if _exists(path)]
    _check_marked(paths, 'deleted')
    if sys.platform != 'darwin':
        paths += [_icon_folder() / f'{name}{suffix}' for suffix in ICON_SUFFIXES]
        paths = [path for path in paths if _exists(path)]
    for path in paths:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    if sys.platform != 'darwin':
        # the icon folder and its napari-launcher parent, once nothing else is in them
        for folder in (_icon_folder(), _icon_folder().parent):
            try:
                folder.rmdir()
            except OSError:
                break
    return paths
