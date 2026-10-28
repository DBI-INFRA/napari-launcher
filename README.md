# napari-launcher

napari-launcher starts [napari](https://napari.org) with a plugin's widgets already docked. It can
also add a shortcut to the app menu and the desktop that does the same, using the Python
environment napari-launcher is installed in. It works with any npe2 plugin, and the plugin needs no
changes.

Requirements: Windows, macOS or Linux, Python 3.10 or later, and napari 0.4.19 or later with a Qt
binding such as PyQt6.

## Add a shortcut

Install napari-launcher in the environment that has napari and the plugin. If you use conda,
activate the environment first and install with pip.

```bash
pip install napari-launcher
napari-launcher shortcut add -w napari-animation
```

This adds a shortcut called napari-animation to the app menu and the desktop. It opens napari with
the napari-animation widget docked.

To remove the shortcut:

```bash
napari-launcher shortcut remove -w napari-animation
```

A shortcut runs the Python it was made with. Remove the shortcut before you delete the environment.

## Choose the widgets

`-w` takes a plugin name, then the names of the widgets to dock. It works like `napari -w`.

- The plugin name is the name napari knows the plugin by. This is usually its package name, and
  `npe2 list` shows it.
- Widget names are the names in napari's Plugins menu. Put a name with spaces in quotes, for
  example `-w my-plugin "Cell counter"`.
- Without widget names, the plugin's first widget docks.
- `__all__` docks all of the plugin's widgets.
- To dock widgets from more than one plugin, repeat `-w`.
- Without `-w`, napari opens with no widgets docked.

Before it makes a shortcut, `shortcut add` checks these names. It asks the Python environment the
shortcut will use which plugins and widgets it has. If a plugin is not installed, has no widgets, or
has no widget of that name, `shortcut add` stops with an error that lists the names that would
work. The check only knows npe2 plugins. To skip it, pass `--no-check`. This is useful before the
plugin is installed, or for an older npe1 plugin.

## Commands

```text
napari-launcher launch [-w PLUGIN [WIDGET ...]] [-- FILE ...]
napari-launcher shortcut add [-w PLUGIN [WIDGET ...]] [--name NAME] [--comment TEXT]
                             [--icon ICON] [--no-desktop] [--bundle-id ID] [--no-check]
napari-launcher shortcut remove (--name NAME | -w PLUGIN)
napari-launcher --version
```

`launch` opens napari straight away. `-w` reads every word after it as a widget name, so put `--`
before the files to open: `napari-launcher launch -w napari-animation -- image.tif`.

`shortcut add` takes these options:

| Option | What it does |
| --- | --- |
| `--name` | The shortcut name. The default is the plugin name, or `napari` without `-w`. With more than one plugin, `--name` is needed. |
| `--comment` | A one-line description. The default is "napari with" followed by the plugin names. |
| `--icon` | The icon, described under Icons below. |
| `--no-desktop` | Add only the app menu entry. |
| `--bundle-id` | The macOS bundle identifier. The default is made from the name. |
| `--no-check` | Do not check the plugin and widget names. |

Running `shortcut add` again with the same name replaces the shortcut. A name cannot contain
`\ / : * ? " < > |`, start or end with a space or a dot, or be a Windows device name such as `CON`,
`NUL` or `COM1`.

`shortcut remove` takes the name the shortcut was added with. If it was added without `--name`, you
can pass the same `-w PLUGIN` instead.

`python -m napari_launcher` works the same as `napari-launcher`. Shortcuts use this form.

## Icons

`--icon` takes a file path, or `package:path/in/package` for a file inside an installed package, for
example `my_plugin:resources/icon.png`. A square PNG works on every platform. On Windows it is
turned into an .ico and scaled down to 256 pixels if larger. On macOS it is turned into an .icns
with `sips`. An .ico, .icns or .svg file only works on the platform that uses that format.

Without `--icon`, the shortcut gets napari's icon from the installed napari. If the installed napari
does not have the icon, napari-launcher downloads it from a fixed commit of napari's GitHub
repository and checks its checksum. If that fails too, napari-launcher makes the shortcut without
an icon of its own and prints a warning.

## Shortcuts that napari-launcher did not make

napari-launcher marks every shortcut it makes. If a shortcut with the same name exists without this
mark, `shortcut add` and `shortcut remove` stop with an error and change nothing.

## Platform notes

**Windows.** Shortcuts go in the Start menu and on the desktop, also when the desktop is in
OneDrive. They start napari with `pythonw.exe`, so no console window opens. Without a console,
napari-launcher writes its output to `%LOCALAPPDATA%\napari-launcher\logs\launch.log`, and replaces
the file each time. If napari then fails to start, a dialog shows the error. If PyTorch is
installed, napari-launcher imports it before Qt to avoid a DLL load error
([pytorch#166628](https://github.com/pytorch/pytorch/issues/166628)). Icons are kept in
`%LOCALAPPDATA%\napari-launcher\icons`.

**macOS.** The shortcut is a small app in `~/Applications`. The desktop gets a link to it, so the
Dock and Launchpad show one app.

**Linux.** The app menu entry is a `.desktop` file in `~/.local/share/applications`, or in
`$XDG_DATA_HOME/applications` if that is set. The desktop shortcut goes in the desktop folder set in
`~/.config/user-dirs.dirs`, or in `$XDG_CONFIG_HOME/user-dirs.dirs` if `XDG_CONFIG_HOME` is set.
If that file does not set a desktop folder, the shortcut goes in `~/Desktop`. napari-launcher does not create this
folder. If it does not exist, you only get the app menu entry. On GNOME, the desktop shortcut is
marked as trusted so it can start. Icons are kept in `~/.local/share/napari-launcher/icons`. If
napari-launcher starts without a console, its output goes to
`~/.local/share/napari-launcher/logs/launch.log`.

## Python API

```python
import napari_launcher

# open napari with the wizard docked and an image loaded; returns when napari closes
napari_launcher.launch([('napari-animation', 'wizard')], ['image.tif'])

# add the shortcuts and return their paths
napari_launcher.create_shortcut('Animation', 'napari-animation', icon='my_plugin:resources/icon.png')

# where the shortcuts called Animation go on this platform
napari_launcher.shortcut_paths('Animation')

# delete the shortcuts and return the paths that were deleted
napari_launcher.remove_shortcut('Animation')
```

`widgets` is a plugin name, or a list of plugin names and `(plugin, widget, ...)` tuples.
`create_shortcut` also takes `comment`, `desktop`, `bundle_id`, `python` and `check`:

- `python` is the interpreter the shortcut runs. The default is the one running napari-launcher.
- `check=True`, the default, runs `python` to check the plugin and widget names, as `shortcut add`
  does. If a name is wrong, or `python` cannot run the check, `create_shortcut` raises a
  `ValueError` and makes nothing. `check=False` skips the check.

`create_shortcut` and `remove_shortcut` raise `FileExistsError` for a shortcut that napari-launcher
did not make.

## For plugin authors

To give your users a shortcut, ask them to install napari-launcher next to your plugin and run
`napari-launcher shortcut add -w your-plugin`. An installer script can run the same command with
the environment's Python after it installs napari, napari-launcher and the plugin. The name check
then finds the plugin and catches a misspelled widget name before the user does.

## License

BSD-3-Clause
