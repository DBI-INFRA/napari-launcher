import re
import struct
import zlib

import pytest

from napari_launcher import _icons


def make_png(width, height):
    """a solid red RGBA PNG"""
    rows = b''.join(b'\x00' + b'\xff\x00\x00\xff' * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(rows))
        + chunk(b'IEND', b'')
    )


def parse_exec(value):
    """the arguments of a .desktop Exec value, undoing its string escaping and quoting as the Desktop Entry spec says"""
    value = re.sub(r'\\(.)', lambda m: {'s': ' ', 'n': '\n', 't': '\t', 'r': '\r'}.get(m.group(1), m.group(1)), value)
    args = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', value)
    return [re.sub(r'\\(.)', r'\1', quoted).replace('%%', '%') if quoted else bare for quoted, bare in args]


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    return home


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """icon downloads fail unless a test fakes them"""

    def urlopen(url, timeout):
        raise OSError(f'no network in tests: {url}')

    monkeypatch.setattr(_icons.urllib.request, 'urlopen', urlopen)
