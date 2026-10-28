"""
command line: `napari-launcher launch | shortcut add | shortcut remove`, or `python -m napari_launcher ...`
"""

import argparse
import subprocess
import sys
import traceback
import warnings

from . import __version__

WITH_HELP = (
    'dock widgets of PLUGIN, the name napari knows the plugin by (usually its package name). '
    "Name each WIDGET as napari's Plugins menu shows it; without WIDGET the plugin's first widget docks, "
    'and __all__ docks them all. Repeat -w for more plugins.'
)


def _add_with(parser, text):
    parser.add_argument(
        '-w',
        '--with',
        dest='widgets',
        nargs='+',
        action='append',
        default=[],
        metavar=('PLUGIN', 'WIDGET'),
        help=text,
    )


def _launch(parser, args):
    from ._launch import launch, log_to_file, show_error

    # under pythonw.exe there is no console, so output goes to a log and errors to a dialog
    log = log_to_file()
    try:
        return launch(args.widgets, args.paths)
    except Exception as e:
        if log is None:
            raise
        traceback.print_exc()
        show_error(e, log)
        return 1


def _name(parser, args, default):
    if args.name:
        return args.name
    if len(args.widgets) > 1:
        parser.error('with more than one plugin, pass --name')
    if args.widgets:
        return args.widgets[0][0]
    if default is None:
        parser.error('pass --name, or -w with the plugin the shortcut is named after')
    return default


def _run(parser, doing, done, action):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            paths = action()
        except (OSError, ValueError, ImportError, subprocess.SubprocessError) as e:
            parser.exit(1, f'{doing} the shortcut failed: {e}\n')
        finally:
            for warning in caught:
                print(f'warning: {warning.message}', file=sys.stderr)
    for path in paths:
        print(f'{done} {path}')
    return 0


def _add(parser, args):
    from ._shortcut import PluginCheckError, create_shortcut

    name = _name(parser, args, default='napari')

    def add():
        try:
            return create_shortcut(
                name,
                args.widgets,
                comment=args.comment,
                icon=args.icon,
                desktop=not args.no_desktop,
                bundle_id=args.bundle_id,
                check=not args.no_check,
            )
        except PluginCheckError as e:
            raise PluginCheckError(f'{e}\nTo add the shortcut anyway, pass --no-check') from None

    return _run(parser, 'adding', 'created', add)


def _remove(parser, args):
    from ._shortcut import remove_shortcut

    name = _name(parser, args, default=None)
    return _run(parser, 'removing', 'removed', lambda: remove_shortcut(name))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='napari-launcher',
        description='start napari with plugin widgets docked, from the command line or an app shortcut',
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    commands = parser.add_subparsers(dest='command', required=True, metavar='COMMAND')

    launch = commands.add_parser(
        'launch', help='start napari with plugin widgets docked', description='start napari with plugin widgets docked'
    )
    _add_with(launch, WITH_HELP + ' Put -- between the last widget and any files.')
    launch.add_argument('paths', nargs='*', metavar='FILE', help='files to open')
    launch.set_defaults(run=_launch)

    shortcut = commands.add_parser(
        'shortcut', help='add or remove app menu and desktop shortcuts', description='app menu and desktop shortcuts'
    )
    actions = shortcut.add_subparsers(dest='action', required=True, metavar='ACTION')

    add_help = (
        'add app menu and desktop shortcuts that start napari with plugin widgets docked, using this Python environment'
    )
    add = actions.add_parser('add', help=add_help, description=add_help)
    _add_with(add, WITH_HELP)
    add.add_argument('--name', help='the shortcut name (default: the plugin name, or napari without -w)')
    add.add_argument('--comment', help='a one-line description')
    add.add_argument(
        '--icon',
        help='a .png, or an .ico (Windows), .icns (macOS) or .svg (Linux); a path or package:path/in/package '
        "(default: napari's icon)",
    )
    add.add_argument(
        '--bundle-id', help='the macOS bundle identifier (default: made from the name); not used on Windows or Linux'
    )
    add.add_argument('--no-desktop', action='store_true', help='only add the app menu entry')
    add.add_argument(
        '--no-check',
        action='store_true',
        help='add the shortcut without checking that this Python environment has the plugin and widgets',
    )
    add.set_defaults(run=_add)

    remove_help = 'delete the shortcuts that `shortcut add` made'
    remove = actions.add_parser('remove', help=remove_help, description=remove_help)
    remove.add_argument('--name', help='the shortcut name')
    _add_with(remove, 'the plugin the shortcut is named after, if it was added without --name')
    remove.set_defaults(run=_remove)

    args = parser.parse_args(argv)
    return args.run(parser, args)


if __name__ == '__main__':
    sys.exit(main())
