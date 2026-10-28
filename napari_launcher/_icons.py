"""
icons for the shortcuts, in the format each platform wants
"""

import hashlib
import re
import shutil
import struct
import subprocess
import urllib.request
import warnings
from http.client import HTTPException
from importlib.resources import files
from pathlib import Path

# `package:path/in/package`; the package part is at least two characters, so `C:\...` stays a path
RESOURCE = re.compile(r'([A-Za-z_][\w.]+):(.+)')
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
ICO_MAX = 256

# napari's icon inside the napari package; which of these exist depends on the napari version
NAPARI_FILES = (
    'resources/logos/gradient-padded-dark.svg',
    'resources/icon.ico',
    'resources/icon.icns',
    'resources/logo.png',
)
# the same icons at a fixed napari commit (tag v0.9.1), for when the installed napari lacks a format
NAPARI_COMMIT = '9c06e25a745586e84021a1bc86b1a315ded6205f'
DOWNLOADS = {
    '.svg': (
        'src/napari/resources/logos/gradient-padded-dark.svg',
        '1a3ca7cad4b953807422e099381e3ac9de7c63dd4ad1ec05d4927e2e8ee5d60f',
    ),
    '.ico': ('src/napari/resources/icon.ico', '8cd459d75cabe894e6b24a1e88c3b453adeadcb18028d8b2a313ab5723371bb3'),
    '.icns': ('src/napari/resources/icon.icns', '4c9d9f875ac22c5b91310dc89a75604281879c2618442c284a1054c1fb337cc3'),
}
DOWNLOAD_TIMEOUT = 20
DOWNLOAD_MAX = 2**21


def resolve(spec):
    """the file an icon spec names: a path, or `package:path` inside an installed package"""
    match = RESOURCE.fullmatch(str(spec))
    if match:
        path = Path(str(files(match.group(1)) / match.group(2)))
    else:
        path = Path(spec).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'no icon at {path}')
    return path


def napari_icons():
    """the files of napari's icon that napari_resources and napari have installed"""
    try:
        from napari_resources import logo_path

        yield Path(logo_path('gradient', 'padded'))
    except (ImportError, OSError, ValueError):
        pass
    for name in NAPARI_FILES:
        path = files('napari') / name
        if path.is_file():
            yield Path(str(path))


def download(suffix, target):
    """download napari's icon as `suffix` to `target`, checking its size and checksum"""
    path, sha256 = DOWNLOADS[suffix]
    url = f'https://raw.githubusercontent.com/napari/napari/{NAPARI_COMMIT}/{path}'
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
        data = response.read(DOWNLOAD_MAX + 1)
    if len(data) > DOWNLOAD_MAX or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f'{url} is not the expected file')
    target.write_bytes(data)
    return target


def _napari_icon(folder, stem, formats):
    """napari's icon at `folder/stem<suffix>`, installed or downloaded; None if neither works"""
    for source in napari_icons():
        if source.suffix in formats:
            target = folder / f'{stem}{source.suffix}'
            shutil.copyfile(source, target)
            return target
    error = 'no download in these formats'
    for suffix in formats:
        if suffix in DOWNLOADS:
            try:
                return download(suffix, folder / f'{stem}{suffix}')
            except (OSError, ValueError, HTTPException) as e:
                error = e
    warnings.warn(f"napari's icon is not installed and the download failed ({error}), so the shortcut has no icon")
    return None


def _png_size(data):
    if data[:8] != PNG_SIGNATURE:
        raise ValueError('not a PNG file')
    return struct.unpack('>II', data[16:24])


def _shrink(data):
    """scale a PNG down to ICO_MAX pixels with Qt, which comes with napari"""
    try:
        from qtpy.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from qtpy.QtGui import QImage
    except ImportError as e:
        raise ValueError(
            f'the icon is larger than {ICO_MAX} pixels and Qt is not installed to scale it down; '
            f'give a PNG of at most {ICO_MAX} pixels or an .ico'
        ) from e
    image = QImage.fromData(data, 'PNG').scaled(
        ICO_MAX, ICO_MAX, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    out = QByteArray()
    buffer = QBuffer(out)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(out)


def png_to_ico(data):
    """an .ico holding one PNG image, a format Windows has read since Vista"""
    width, height = _png_size(data)
    if max(width, height) > ICO_MAX:
        data = _shrink(data)
        width, height = _png_size(data)
    header = struct.pack('<HHH', 0, 1, 1)
    # in the directory entry, a size of 0 stands for 256
    entry = struct.pack('<BBBBHHII', width % 256, height % 256, 0, 0, 1, 32, len(data), len(header) + 16)
    return header + entry + data


def install(spec, folder, stem, formats):
    """
    copy or convert the icon `spec` to `folder/stem<suffix>`, with the first suffix in `formats`
    that it already has or can be converted to; returns the new file

    Without `spec`, napari's icon is used, and the result is None if it is neither installed nor
    downloadable.
    """
    folder.mkdir(parents=True, exist_ok=True)
    if not spec:
        return _napari_icon(folder, stem, formats)
    source = resolve(spec)
    suffix = source.suffix.lower()
    if suffix in formats:
        target = folder / f'{stem}{suffix}'
        shutil.copyfile(source, target)
    elif suffix == '.png' and '.ico' in formats:
        target = folder / f'{stem}.ico'
        target.write_bytes(png_to_ico(source.read_bytes()))
    elif suffix == '.png' and '.icns' in formats:
        target = folder / f'{stem}.icns'
        # sips comes with macOS
        subprocess.run(
            ['sips', '-s', 'format', 'icns', str(source), '--out', str(target)], capture_output=True, check=True
        )
    else:
        accepted = ' or '.join(dict.fromkeys(['.png', *formats]))
        raise ValueError(f'{source.name} does not work as an icon on this platform; use {accepted}')
    return target
