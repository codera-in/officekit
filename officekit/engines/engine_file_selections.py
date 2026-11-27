"""Process-local native grants. Inputs are never staged or copied."""

import contextlib
import ctypes
import errno
import hmac
import os
import stat
import sys
import threading
import time
import uuid
from dataclasses import dataclass

MAX_ROOTS = 10_000
MAX_ENTRIES = 100_000
MAX_SKIPPED_ROWS = 10_000
MAX_SESSIONS = 128
SELECTION_TTL = 1800
OUTPUT_TTL = 600


_SKIP_COUNTERS = {'link': 'skipped_links', 'special': 'special', 'denied': 'denied_folders'}


def _label_for(root, index, root_count, directory):
    """Selection-relative display name for a path under one selected root."""
    def label(path):
        relative = os.path.relpath(path, root) if directory else os.path.basename(path)
        name = relative.replace(os.sep, '/')
        return f'{index + 1}/{name}' if root_count > 1 else name
    return label


def _note_skip(stats, label, path, reason):
    """Count a skipped entry and keep its label up to MAX_SKIPPED_ROWS rows."""
    if stats is None:
        return
    counter = _SKIP_COUNTERS[reason]
    stats[counter] = stats.get(counter, 0) + 1
    rows = stats.setdefault('rows', [])
    if len(rows) < MAX_SKIPPED_ROWS:
        rows.append((label(path), reason))
    else:
        stats['rows_dropped'] = stats.get('rows_dropped', 0) + 1


def identity(value):
    birthtime = getattr(value, 'st_birthtime', None)
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
            int(birthtime * 1_000_000_000) if birthtime is not None else None)


def exclusive_rename(source, destination, parent_fd):
    """Atomic descriptor-relative rename that never replaces an existing name."""
    if parent_fd is None and os.name == 'nt':
        # Windows MoveFile semantics used by os.rename fail if the destination
        # already exists, preserving the no-replace contract.
        os.rename(source, destination)
        return
    if parent_fd is None or sys.platform not in {'darwin', 'linux'}:
        raise OSError(errno.ENOTSUP, 'Exclusive filesystem publication is unavailable')
    library = ctypes.CDLL(None, use_errno=True)
    symbol, flag = ('renameatx_np', 4) if sys.platform == 'darwin' else ('renameat2', 1)
    function = getattr(library, symbol, None)
    if function is None:
        raise OSError(errno.ENOTSUP, 'Exclusive filesystem publication is unavailable')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), flag) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def owned_identity(name, parent_fd, expected):
    try:
        value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return (value.st_dev, value.st_ino) == expected[:2]
    except OSError:
        return False


def remove_owned_file(name, parent_fd, expected):
    """Quarantine first, inspect the moved inode, then remove only our file."""
    quarantine = '.officekit-cleanup-' + str(uuid.uuid4())
    try:
        exclusive_rename(name, quarantine, parent_fd)
    except FileNotFoundError:
        return True
    if not owned_identity(quarantine, parent_fd, expected):
        try:
            exclusive_rename(quarantine, name, parent_fd)
        except OSError:
            pass
        return False
    os.unlink(quarantine, dir_fd=parent_fd)
    return True


def checked_path(path):
    if not isinstance(path, str) or not os.path.isabs(path) or '\x00' in path:
        raise ValueError('Native selection must be an absolute path')
    path = os.path.abspath(path)
    cursor = path
    while True:
        try:
            value = os.lstat(cursor)
        except FileNotFoundError:
            if cursor != path:
                raise
            value = None
        if (value is not None and (os.path.islink(cursor) or getattr(value, 'st_file_attributes', 0) & 0x400)):
            raise ValueError('Symbolic links are not supported')
        parent = os.path.dirname(cursor)
        if parent == cursor:
            return path
        cursor = parent


@contextlib.contextmanager
def open_parent(path):
    """Hold the parent directory while resolving every component without links."""
    if os.name == 'nt':
        checked_path(path)
        yield None
        return
    descriptor = os.open(os.path.sep, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in os.path.dirname(path).split(os.path.sep):
            if not component:
                continue
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class SelectedFile:
    selection_id: str
    root: str
    path: str
    name: str
    signature: tuple

    @property
    def id(self):
        return str(uuid.uuid5(uuid.UUID(self.selection_id), self.name))


@dataclass
class Selection:
    roots: tuple
    access: str
    expires: float
    pins: int = 0
    revoked: bool = False


@dataclass(frozen=True)
class OutputGrant:
    path: str
    kind: str
    job_kind: str
    overwrite: bool
    expires: float
    parent_identity: tuple
    destination_identity: tuple | None


class FileSelectionStore:
    def __init__(self, native_token=None, clock=time.monotonic):
        self.native_token = native_token if native_token is not None else os.environ.get('OFFICEKIT_NATIVE_GRANT_TOKEN', '')
        self.clock = clock
        self.selections = {}
        self.outputs = {}
        self.lock = threading.RLock()

    def authorize(self, credential):
        if not self.native_token or not isinstance(credential, str) or not hmac.compare_digest(self.native_token, credential):
            raise PermissionError('Native authorization required')

    def register_native(self, paths, access='read', credential=''):
        self.authorize(credential)
        if access not in {'read', 'read-write'} or not isinstance(paths, list) or not 1 <= len(paths) <= MAX_ROOTS:
            raise ValueError('Invalid selection bounds or access')
        roots = []
        for raw in paths:
            path = checked_path(raw)
            value = os.lstat(path)
            if not (stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode)):
                raise ValueError('Only regular files and directories are supported')
            roots.append((path, (value.st_dev, value.st_ino), stat.S_ISDIR(value.st_mode)))
        if len({root[0] for root in roots}) != len(roots):
            raise ValueError('Selection roots must be unique')
        with self.lock:
            self._prune()
            if len(self.selections) >= MAX_SESSIONS:
                raise ValueError('Too many active selections')
            key = str(uuid.uuid4())
            self.selections[key] = Selection(tuple(roots), access, self.clock() + SELECTION_TTL)
            return self.metadata(key)

    def _prune(self):
        now = self.clock()
        self.selections = {key: value for key, value in self.selections.items() if value.pins or (not value.revoked and value.expires > now)}
        self.outputs = {key: value for key, value in self.outputs.items() if value.expires > now}

    def get(self, key, write=False):
        with self.lock:
            value = self.selections.get(key)
            if value is None or value.revoked or (not value.pins and value.expires <= self.clock()):
                raise FileNotFoundError('Selection is unavailable')
            if write and value.access != 'read-write':
                raise PermissionError('Selection is read only')
            return value

    def metadata(self, key):
        value = self.get(key)
        return {'id': key, 'displayNames': [os.path.basename(root[0]) or 'Selected folder' for root in value.roots], 'access': value.access, 'expiresAt': value.expires}

    def pin(self, key):
        with self.lock:
            self.get(key).pins += 1

    def unpin(self, key):
        with self.lock:
            if key in self.selections:
                self.selections[key].pins = max(0, self.selections[key].pins - 1)
            self._prune()

    def revoke(self, key):
        with self.lock:
            value = self.get(key)
            value.revoked = True
            self._prune()

    def iter_files(self, key, include_subfolders=True, stats=None):
        selection = self.get(key)
        count = 0
        seen = set()
        for index, (root, root_id, directory) in enumerate(selection.roots):
            checked_path(root)
            current = os.lstat(root)
            if (current.st_dev, current.st_ino) != root_id:
                raise ValueError('Selected root changed')
            label = _label_for(root, index, len(selection.roots), directory)
            if directory:
                # Without a stats collector the call is exactly the historical one (tests stub _walk).
                extra = {} if stats is None else {'stats': stats, 'label': label}
                iterator = self._walk(root, include_subfolders=include_subfolders, **extra)
            else:
                iterator = iter([root])
            for path in iterator:
                self.get(key)
                count += 1
                if count > MAX_ENTRIES:
                    raise ValueError('Selection exceeds scan entry limit')
                if path in seen:
                    continue
                seen.add(path)
                value = os.lstat(path)
                if not stat.S_ISREG(value.st_mode):
                    continue
                yield SelectedFile(key, root, path, label(path), identity(value))

    def find_file(self, key, file_id):
        """Resolve a manifest ID without accepting a path from the caller."""
        try:
            parsed = uuid.UUID(file_id)
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Invalid selected file') from None
        if str(parsed) != file_id:
            raise ValueError('Invalid selected file')
        for item in self.iter_files(key):
            if str(uuid.uuid5(uuid.UUID(key), item.name)) == file_id:
                return item
        raise FileNotFoundError('Selected file is unavailable')

    def derive_files(self, key, file_ids):
        if not isinstance(file_ids, list) or not 1 <= len(file_ids) <= 30 or len(set(file_ids)) != len(file_ids):
            raise ValueError('Choose between one and 30 unique files')
        items = [self.find_file(key, file_id) for file_id in file_ids]
        roots = []
        for item in items:
            with self.open_file(item):
                pass
            value = os.lstat(item.path)
            if not stat.S_ISREG(value.st_mode) or identity(value) != item.signature:
                raise FileExistsError('Selected file changed')
            roots.append((item.path, (value.st_dev, value.st_ino), False))
        if len({root[0] for root in roots}) != len(roots):
            raise ValueError('Selected files must be unique')
        with self.lock:
            self._prune()
            if len(self.selections) >= MAX_SESSIONS:
                raise RuntimeError('Too many active selections')
            selection_id = str(uuid.uuid4())
            self.selections[selection_id] = Selection(tuple(roots), 'read', self.clock() + SELECTION_TTL)
        return self.metadata(selection_id)

    @staticmethod
    def _walk(root, include_subfolders=True, stats=None, label=None):
        pending = [root]
        entries = 0
        while pending:
            directory = checked_path(pending.pop())
            try:
                with os.scandir(directory) as iterator:
                    for item in iterator:
                        entries += 1
                        if entries > MAX_ENTRIES:
                            raise ValueError('Selection exceeds scan entry limit')
                        item_stat = item.stat(follow_symlinks=False)
                        if item.is_symlink() or getattr(item_stat, 'st_file_attributes', 0) & 0x400:
                            _note_skip(stats, label, item.path, 'link')
                            continue
                        if item.is_dir(follow_symlinks=False):
                            if include_subfolders:
                                pending.append(item.path)
                        elif item.is_file(follow_symlinks=False):
                            yield item.path
                        else:
                            _note_skip(stats, label, item.path, 'special')
            except PermissionError:
                if directory == root:
                    raise
                _note_skip(stats, label, directory, 'denied')

    @contextlib.contextmanager
    def open_file(self, item):
        self.get(item.selection_id)
        with open_parent(item.path) as parent:
            descriptor = os.open(os.path.basename(item.path) if parent is not None else checked_path(item.path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=parent)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or identity(before) != item.signature:
                raise ValueError('Selected file changed; select it again')
            yield stream
            if identity(os.fstat(stream.fileno())) != item.signature:
                raise ValueError('Selected file changed during processing')

    def manifest(self, key, offset=0, limit=200):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('Invalid pagination')
        files = []
        more = False
        for index, item in enumerate(self.iter_files(key)):
            if index < offset:
                continue
            if len(files) == limit:
                more = True
                break
            files.append({'id': item.id, 'name': item.name, 'size_bytes': item.signature[2]})
        return {**self.metadata(key), 'files': files, 'offset': offset, 'hasMore': more}

    def count_by_root(self, key, extensions):
        """Count the files with one of ``extensions`` per selected root, for a pre-run summary."""
        roots, other = {}, 0
        for item in self.iter_files(key):
            if os.path.splitext(item.name)[1].lower() in extensions:
                label = os.path.basename(item.root) or 'Selected folder'
                roots[label] = roots.get(label, 0) + 1
            else:
                other += 1
        return {'folders': [{'name': name, 'images': count} for name, count in roots.items()],
                'images': sum(roots.values()), 'skipped': other}

    def register_output(self, path, kind, job_kind, overwrite=False, credential=''):
        self.authorize(credential)
        path = checked_path(path)
        if kind not in {'file', 'directory'} or type(overwrite) is not bool:
            raise ValueError('Invalid output grant')
        if overwrite:
            raise ValueError('Existing destinations are never replaced')
        parent = os.stat(os.path.dirname(path))
        existing = os.lstat(path) if os.path.lexists(path) else None
        if existing:
            raise FileExistsError('Output already exists')
        with self.lock:
            self._prune()
            if len(self.outputs) >= MAX_SESSIONS:
                raise ValueError('Too many output grants')
            key = str(uuid.uuid4())
            self.outputs[key] = OutputGrant(path, kind, job_kind, overwrite, self.clock() + OUTPUT_TTL, (parent.st_dev, parent.st_ino), identity(existing) if existing else None)
            return {'id': key, 'displayName': os.path.basename(path), 'kind': kind, 'expiresAt': self.outputs[key].expires}

    def consume_output(self, key, job_kind):
        with self.lock:
            self._prune()
            grant = self.outputs.get(key)
            if grant is None:
                raise FileNotFoundError('Output grant is unavailable')
            if grant.job_kind != job_kind:
                raise PermissionError('Output grant does not allow this operation')
            self.validate_output(grant)
            del self.outputs[key]
            return grant

    @staticmethod
    def validate_output(grant):
        checked_path(grant.path)
        parent = os.stat(os.path.dirname(grant.path))
        existing = os.lstat(grant.path) if os.path.lexists(grant.path) else None
        if (parent.st_dev, parent.st_ino) != grant.parent_identity or (identity(existing) if existing else None) != grant.destination_identity:
            raise FileExistsError('Output destination changed')

    def close(self):
        with self.lock:
            self.selections.clear()
            self.outputs.clear()
