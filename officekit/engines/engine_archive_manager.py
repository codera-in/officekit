"""Local archive engine discovery and conservative format capabilities."""

import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REQUESTED_FORMATS = [
    ('7z', '7-Zip archive', ['.7z'], '7z'), ('ar', 'Unix archive', ['.ar'], 'ar'),
    ('arj', 'ARJ archive', ['.arj'], 'arj'), ('bz2', 'Bzip2', ['.bz2'], 'bz2'),
    ('cab', 'Cabinet', ['.cab'], 'cab'), ('chm', 'Compiled HTML Help', ['.chm'], 'chm'),
    ('cpio', 'CPIO', ['.cpio'], 'cpio'), ('dmg', 'Apple disk image', ['.dmg'], 'dmg'),
    ('exe', 'Self-extracting archive', ['.exe'], 'exe'), ('fat', 'FAT image', ['.fat'], 'fat'),
    ('gz', 'Gzip', ['.gz'], 'gz'), ('iso', 'ISO image', ['.iso'], 'iso'),
    ('lha', 'LHA', ['.lha'], 'lha'), ('lz4', 'LZ4', ['.lz4'], 'lz4'),
    ('lzh', 'LZH', ['.lzh'], 'lzh'), ('lzx', 'LZX', ['.lzx'], 'lzx'),
    ('msi', 'Windows Installer', ['.msi'], 'msi'), ('ntfs', 'NTFS image', ['.ntfs'], 'ntfs'),
    ('pkg', 'Package archive', ['.pkg'], 'pkg'), ('qcow2', 'QEMU disk image', ['.qcow2'], 'qcow2'),
    ('rar', 'RAR archive', ['.rar'], 'rar'), ('rpm', 'RPM package', ['.rpm'], 'rpm'),
    ('sea', 'Self-extracting archive', ['.sea'], 'sea'), ('sit', 'StuffIt archive', ['.sit'], 'sit'),
    ('sitx', 'StuffIt X archive', ['.sitx'], 'sitx'), ('squashfs', 'SquashFS image', ['.squashfs'], 'squashfs'),
    ('tar', 'TAR archive', ['.tar'], 'tar'), ('tar-bz2', 'TAR.BZ2 archive', ['.tar.bz2'], 'tar-bz2'),
    ('tar-gz', 'TAR.GZ archive', ['.tar.gz', '.tgz'], 'tar-gz'), ('tar-lz4', 'TAR.LZ4 archive', ['.tar.lz4'], 'tar-lz4'),
    ('tar-xz', 'TAR.XZ archive', ['.tar.xz', '.txz'], 'tar-xz'), ('tar-z', 'TAR.Z archive', ['.tar.z'], 'tar-z'),
    ('vdi', 'VirtualBox disk image', ['.vdi'], 'vdi'), ('vhd', 'Virtual hard disk', ['.vhd'], 'vhd'),
    ('vhdx', 'Hyper-V virtual disk', ['.vhdx'], 'vhdx'), ('vmdk', 'VMware disk image', ['.vmdk'], 'vmdk'),
    ('wim', 'Windows Imaging Format', ['.wim'], 'wim'), ('xar', 'XAR archive', ['.xar'], 'xar'),
    ('xz', 'XZ', ['.xz'], 'xz'), ('z', 'Compress', ['.z'], 'z'),
    ('zip', 'ZIP archive', ['.zip'], 'zip'), ('zipx', 'ZIPX archive', ['.zipx'], 'zipx'),
]

# These formats are in the bundled engine's documented read/extract set.
SEVEN_ZIP_READ = set('7z ar arj bz2 cab chm cpio dmg fat gz iso lzh msi ntfs qcow2 rar rpm squashfs tar vdi vhd vhdx vmdk wim xar xz z zip'.split())
# These extensions may expose only an outer archive layer or require format
# variant detection. They can be browsed, but extraction stays disabled.
SEVEN_ZIP_PARTIAL = set('exe lha tar-bz2 tar-gz tar-xz tar-z zipx'.split())
MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_LIST_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 ** 3
MAX_UNPACKED_BYTES = 32 * 1024 ** 3


def engine_path():
    """Resolve only the engine shipped by the app or its pinned build dependency."""
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    names = ['7z.exe', '7z.dll'] if os.name == 'nt' else ['7zz']
    packaged = root / 'archive-engines'
    candidates = [packaged / name for name in names]
    if all(path.is_file() and not path.is_symlink() for path in candidates) and (os.name == 'nt' or os.access(candidates[0], os.X_OK)):
        return str(candidates[0])
    arch = platform.machine().lower()
    arch = 'arm64' if arch in {'arm64', 'aarch64'} else 'x64'
    node_root = Path(__file__).resolve().parents[2] / 'node_modules' / '7zip-bin-full'
    source = node_root / ('win' if os.name == 'nt' else 'mac') / arch
    candidates = [source / name for name in names]
    if all(path.is_file() and not path.is_symlink() for path in candidates) and (os.name == 'nt' or os.access(candidates[0], os.X_OK)):
        return str(candidates[0])
    return None


def capabilities():
    available = engine_path() is not None
    result = []
    for key, label, extensions, _ in REQUESTED_FORMATS:
        read = available and key in SEVEN_ZIP_READ | SEVEN_ZIP_PARTIAL
        extract = (available and key in SEVEN_ZIP_READ) or key == 'zip'
        create = key == 'zip'
        read_state = 'supported' if read and key in SEVEN_ZIP_READ else 'partial' if read else 'unsupported'
        extract_state = 'supported' if extract else 'partial' if available and key in SEVEN_ZIP_PARTIAL else 'unsupported'
        create_state = 'supported' if create else 'unsupported'
        result.append({'id': key, 'label': label, 'extensions': extensions,
                       'read': read_state, 'extract': extract_state, 'create': create_state,
                       'limitations': ([] if read_state == 'supported' else ['Format detection or container layering may be partial.'] if read_state == 'partial' else ['No bundled engine capability is enabled for this format.'])
                       + ([] if extract_state == 'supported' else ['Safe extraction requires a fully supported format capability.'])
                       + ([] if create else ['Archive creation is currently enabled for ZIP only.'])})
    return result


def extension_hint(name):
    lowered = name.lower()
    for key, _, extensions, _ in sorted(REQUESTED_FORMATS, key=lambda item: max(map(len, item[2])), reverse=True):
        if any(lowered.endswith(extension) for extension in extensions):
            return key
    return 'unknown'


def list_archive(path, timeout=30, pass_fds=()):
    try:
        if os.stat(path).st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('The archive exceeds the 32 GiB input limit.')
    except OSError:
        raise ValueError('The selected archive is unavailable.') from None
    binary = engine_path()
    if not binary:
        raise ValueError('The bundled archive engine is unavailable for this platform.')
    env = {'PATH': os.path.dirname(binary), 'LANG': 'C.UTF-8'}
    if os.name == 'nt':
        for key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP'):
            if os.environ.get(key):
                env[key] = os.environ[key]
    with tempfile.TemporaryFile(mode='w+b') as listing_output:
        options = {'stdout': listing_output, 'stderr': subprocess.DEVNULL,
                   'stdin': subprocess.DEVNULL, 'shell': False, 'env': env}
        if os.name == 'nt':
            options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        else:
            options['start_new_session'] = True
            if pass_fds:
                options['pass_fds'] = tuple(pass_fds)
        process = subprocess.Popen([binary, 'l', '-slt', path], **options)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if listing_output.tell() > MAX_ARCHIVE_LIST_BYTES:
                    raise ValueError('The archive contains too much listing data to display safely.')
                if time.monotonic() - started > timeout:
                    raise ValueError('Archive indexing took too long. The source archive remains unchanged.')
                time.sleep(0.05)
            if listing_output.tell() > MAX_ARCHIVE_LIST_BYTES:
                raise ValueError('The archive contains too much listing data to display safely.')
            if process.returncode not in (0, 1):
                raise ValueError('The archive could not be read. It may be damaged, encrypted or unsupported.')
            listing_output.seek(0)
            listing = listing_output.read(MAX_ARCHIVE_LIST_BYTES + 1).decode('utf-8', errors='replace')
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
    entries = []
    block = {}
    in_entries = False
    for line in listing.splitlines():
        if line.strip() == '----------':
            in_entries = True
            block = {}
            continue
        if not in_entries:
            continue
        if not line:
            if 'Path' in block and block['Path'] != path:
                entries.append(block)
            block = {}
            continue
        if ' = ' in line:
            key, value = line.split(' = ', 1)
            block[key] = value
    if 'Path' in block and block['Path'] != path:
        entries.append(block)
    normalized = []
    seen = set()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise ValueError('The archive exceeds the 10,000-entry browsing limit.')
    if sum(int(entry.get('Size', '0') or 0) for entry in entries) > MAX_UNPACKED_BYTES:
        raise ValueError('The archive exceeds the 32 GiB expanded-size limit.')
    for entry in entries:
        raw_name = entry.get('Path', '')
        name = raw_name.rstrip('/') if entry.get('Folder') == '+' else raw_name
        parts = name.split('/')
        reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', *(f'COM{index}' for index in range(1, 10)), *(f'LPT{index}' for index in range(1, 10))}
        windows_unsafe = any(part.endswith((' ', '.')) or part.split('.')[0].upper() in reserved for part in parts)
        mode = entry.get('Mode', '')
        attributes = entry.get('Attributes', '').split()
        has_link = (any(key in entry for key in ('Symbolic Link', 'Hard Link', 'Reparse Point'))
                    or entry.get('Type', '').lower() in {'link', 'symbolic link', 'hard link'}
                    or mode.startswith('l') or 'L' in attributes)
        if not name or len(name) > 32767 or '\\' in name or '\x00' in name or name.startswith('/') or any(part in {'', '.', '..'} or len(part) > 255 or any(ord(char) < 32 or char in '<>:"|?*' for char in part) for part in parts) or windows_unsafe or has_link or name.casefold() in seen:
            raise ValueError('The archive contains an unsafe entry path.')
        seen.add(name.casefold())
        try:
            size = int(entry.get('Size', '0') or 0)
            packed = int(entry.get('Packed Size', '0') or 0)
        except ValueError:
            raise ValueError('The archive contains invalid entry metadata.') from None
        if size < 0 or packed < 0:
            raise ValueError('The archive contains invalid entry metadata.')
        normalized.append({'name': name, 'size_bytes': size,
                           'compressed_bytes': packed,
                           'kind': 'directory' if entry.get('Folder') == '+' else 'file',
                           'encrypted': entry.get('Encrypted') == '+',
                           'modified_at': entry.get('Modified', '')[:64]})
    return normalized


def extract_archive(path, destination, check_cancel, pass_fds=(), timeout=300):
    binary = engine_path()
    if not binary:
        raise ValueError('The bundled archive engine is unavailable for this platform.')
    env = {'PATH': os.path.dirname(binary), 'LANG': 'C.UTF-8'}
    if os.name == 'nt':
        for key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP'):
            if os.environ.get(key):
                env[key] = os.environ[key]
    options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
               'stderr': subprocess.DEVNULL, 'shell': False, 'env': env}
    if os.name == 'nt':
        options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    elif pass_fds:
        options['pass_fds'] = tuple(pass_fds)
        options['start_new_session'] = True
    process = subprocess.Popen([binary, 'x', '-y', '-bd', '-bb0', f'-o{destination}', path], **options)
    started = time.monotonic()
    try:
        while process.poll() is None:
            check_cancel()
            if time.monotonic() - started > timeout:
                raise ValueError('Archive extraction took too long. The source archive remains unchanged.')
            time.sleep(0.1)
        if process.returncode != 0:
            raise ValueError('The archive could not be extracted. It may be damaged, encrypted or unsupported.')
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
