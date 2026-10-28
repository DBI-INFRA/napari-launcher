import hashlib
import io
import struct
import sys
import urllib.request

import pytest
from conftest import make_png

from napari_launcher import _icons

REAL_URLOPEN = urllib.request.urlopen


@pytest.fixture
def napari_files(monkeypatch, tmp_path):
    """an installed napari without napari_resources, whose package files are in the returned folder"""
    folder = tmp_path / 'napari'
    (folder / 'resources' / 'logos').mkdir(parents=True)
    monkeypatch.setitem(sys.modules, 'napari_resources', None)
    monkeypatch.setattr(_icons, 'files', lambda package: folder)
    return folder


def _fake_download(monkeypatch, data):
    """serve `data` for every URL and expect b'icon' as the .ico download; returns the requested URLs"""
    urls = []

    def urlopen(url, timeout):
        urls.append(url)
        return io.BytesIO(data)

    monkeypatch.setattr(_icons.urllib.request, 'urlopen', urlopen)
    monkeypatch.setitem(_icons.DOWNLOADS, '.ico', ('icon.ico', hashlib.sha256(b'icon').hexdigest()))
    return urls


@pytest.mark.parametrize('formats', [('.ico',), ('.icns',), ('.svg', '.png')])
def test_installed_napari_icon(tmp_path, formats):
    target = _icons.install(None, tmp_path, 'app', formats)
    assert target.parent == tmp_path and target.stem == 'app' and target.suffix in formats
    assert target.stat().st_size > 0


def test_icon_of_napari_without_napari_resources(napari_files, tmp_path):
    (napari_files / 'resources' / 'logos' / 'gradient-padded-dark.svg').write_text('<svg/>')
    assert _icons.install(None, tmp_path, 'app', ('.svg', '.png')).read_text() == '<svg/>'


def test_png_icon_of_older_napari(napari_files, tmp_path):
    (napari_files / 'resources' / 'logo.png').write_bytes(make_png(1, 1))
    assert _icons.install(None, tmp_path, 'app', ('.svg', '.png')) == tmp_path / 'app.png'


def test_download_when_napari_has_no_icon(napari_files, monkeypatch, tmp_path):
    urls = _fake_download(monkeypatch, b'icon')
    assert _icons.install(None, tmp_path, 'app', ('.ico',)).read_bytes() == b'icon'
    assert urls == [f'https://raw.githubusercontent.com/napari/napari/{_icons.NAPARI_COMMIT}/icon.ico']


@pytest.mark.parametrize('data', [b'not the icon', b'icon' * 10])
def test_bad_download_leaves_no_icon(napari_files, monkeypatch, tmp_path, data):
    _fake_download(monkeypatch, data)
    monkeypatch.setattr(_icons, 'DOWNLOAD_MAX', 20)
    with pytest.warns(UserWarning, match='is not the expected file'):
        assert _icons.install(None, tmp_path, 'app', ('.ico',)) is None
    assert not (tmp_path / 'app.ico').exists()


def test_offline_leaves_no_icon(napari_files, tmp_path):
    with pytest.warns(UserWarning, match='no network in tests'):
        assert _icons.install(None, tmp_path, 'app', ('.ico',)) is None


def test_pinned_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(_icons.urllib.request, 'urlopen', REAL_URLOPEN)
    for suffix in _icons.DOWNLOADS:
        try:
            _icons.download(suffix, tmp_path / f'icon{suffix}')
        except OSError as e:
            pytest.skip(f'offline: {e}')


def test_resolve_resource_and_path(tmp_path):
    assert _icons.resolve('napari:resources/icon.ico').name == 'icon.ico'
    icon = tmp_path / 'icon.png'
    icon.write_bytes(make_png(1, 1))
    assert _icons.resolve(icon) == icon.resolve()
    with pytest.raises(FileNotFoundError):
        _icons.resolve(tmp_path / 'missing.png')


def test_windows_drive_is_a_path():
    assert not _icons.RESOURCE.fullmatch(r'C:\icons\app.png')
    assert _icons.RESOURCE.fullmatch('my_plugin.resources:icon.png')


def _ico_entry(ico):
    reserved, kind, count = struct.unpack('<HHH', ico[:6])
    assert (reserved, kind, count) == (0, 1, 1)
    width, height, _, _, planes, bpp, size, offset = struct.unpack('<BBBBHHII', ico[6:22])
    assert (planes, bpp) == (1, 32)
    assert offset == 22 and size == len(ico) - 22
    return width or 256, height or 256, ico[offset:]


@pytest.mark.parametrize(('width', 'height'), [(16, 16), (256, 256), (48, 32)])
def test_png_to_ico(width, height):
    png = make_png(width, height)
    assert _ico_entry(_icons.png_to_ico(png)) == (width, height, png)


def test_large_png_is_scaled_down():
    pytest.importorskip('qtpy.QtGui')
    width, height, data = _ico_entry(_icons.png_to_ico(make_png(512, 384)))
    assert (width, height) == (256, 192)
    assert _icons._png_size(data) == (256, 192)


def test_png_to_ico_rejects_other_files():
    with pytest.raises(ValueError, match='not a PNG'):
        _icons.png_to_ico(b'GIF89a' + bytes(30))


def test_install_converts_png_to_ico(tmp_path):
    source = tmp_path / 'icon.png'
    source.write_bytes(make_png(32, 32))
    target = _icons.install(source, tmp_path / 'icons', 'app', ('.ico',))
    assert target.suffix == '.ico'
    assert _ico_entry(target.read_bytes())[:2] == (32, 32)


def test_install_keeps_png_where_it_works(tmp_path):
    source = tmp_path / 'icon.PNG'
    source.write_bytes(make_png(32, 32))
    assert _icons.install(source, tmp_path, 'app', ('.svg', '.png')) == tmp_path / 'app.png'


@pytest.mark.skipif(sys.platform != 'darwin', reason='sips is on macOS only')
def test_install_converts_png_to_icns(tmp_path):
    source = tmp_path / 'icon.png'
    source.write_bytes(make_png(512, 512))
    target = _icons.install(source, tmp_path / 'icons', 'icon', ('.icns',))
    assert target.read_bytes()[:4] == b'icns'


@pytest.mark.parametrize(
    ('formats', 'accepted'),
    [(('.ico',), '.png or .ico'), (('.svg', '.png'), '.png or .svg'), (('.icns',), '.png or .icns')],
)
def test_install_rejects_unusable_format(tmp_path, formats, accepted):
    source = tmp_path / 'icon.gif'
    source.write_bytes(b'GIF89a')
    with pytest.raises(ValueError, match=rf'icon.gif does not work as an icon on this platform; use {accepted}$'):
        _icons.install(source, tmp_path, 'app', formats)
