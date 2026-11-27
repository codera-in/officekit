"""Bounded, native-authorized invoice libraries in user-selected folders.

Only the repository accesses invoice files. Descriptor-relative operations never
follow a supplied link; revisions and byte digests reject external overwrites.
"""

import contextlib
import copy
import errno
import hashlib
import json
import os
import re
import sqlite3
import stat
import uuid
import io
import zipfile
from datetime import datetime, timezone, date

from officekit.engines.engine_file_selections import checked_path, open_parent, exclusive_rename

MAX_LIBRARY_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 5 * 1024 * 1024
MAX_DATABASE_BYTES = 256 * 1024 * 1024
MAX_BACKUP_BYTES = 512 * 1024 * 1024
MAX_BACKUP_FILES = 10000
MAX_PDF_BYTES = 20 * 1024 * 1024
COLLECTION_LIMITS = {
    'businesses': 50, 'currencies': 5000, 'tax_profiles': 2500,
    'templates': 100, 'clients': 5000, 'items': 5000, 'documents': 5000,
    'payments': 50000, 'schedules': 500, 'conversions': 10000,
}
ROOT_NAME = 'officekit-invoices'


def invoice_bindings_path(default_data_directory):
    """Keep invoice folder bindings inside an explicitly configured app data root."""
    data_directory = os.path.realpath(os.environ.get('OFFICEKIT_DATA_DIR') or os.fspath(default_data_directory))
    return os.path.join(data_directory, 'invoice-folder-bindings.json')


class InvoiceStorageError(ValueError):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@contextlib.contextmanager
def _storage_errors():
    try:
        yield
    except OSError as error:
        if error.errno == errno.ENOSPC:
            raise InvoiceStorageError('DISK_FULL', 'The invoice folder has no space for this save.', 507) from None
        raise InvoiceStorageError('FOLDER_UNAVAILABLE', 'The invoice folder is unavailable or cannot be accessed safely.', 503) from None


def _identity(metadata):
    return metadata.st_dev, metadata.st_ino


def _encode(value, maximum):
    try:
        result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
    except (TypeError, ValueError, UnicodeError):
        raise InvoiceStorageError('INVALID_LIBRARY', 'The invoice data is not valid JSON.') from None
    if len(result) > maximum:
        raise InvoiceStorageError('LIBRARY_CAPACITY', 'The invoice data exceeds this library’s capacity.', 413)
    return result


def _validate(state):
    fields = set(COLLECTION_LIMITS) | {'schema_version', 'library_id', 'revision'}
    if not isinstance(state, dict) or set(state) != fields:
        raise InvoiceStorageError('INVALID_LIBRARY', 'The invoice library has an invalid structure.')
    if type(state['schema_version']) is not int or state['schema_version'] != 1 or type(state['revision']) is not int or state['revision'] < 0:
        raise InvoiceStorageError('INVALID_LIBRARY', 'The invoice library version or revision is unsupported.')
    try:
        if str(uuid.UUID(state['library_id'])) != state['library_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise InvoiceStorageError('INVALID_LIBRARY', 'The invoice library identity is invalid.') from None
    for name, maximum in COLLECTION_LIMITS.items():
        entries = state[name]
        if not isinstance(entries, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in entries.items()):
            raise InvoiceStorageError('INVALID_LIBRARY', 'The invoice library records are invalid.')
        if len(entries) > maximum:
            raise InvoiceStorageError('LIBRARY_CAPACITY', 'The invoice library has too many saved records.', 413)
    return state


def _read_file(directory, name, maximum, expected_identity=None):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if expected_identity is not None and _identity(metadata) != tuple(expected_identity):
            raise InvoiceStorageError('BACKUP_CHANGED', 'The selected backup changed. Choose it again.', 409)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise InvoiceStorageError('UNSAFE_FILE', 'The invoice file is not a safe regular file.', 503)
        if metadata.st_size > maximum:
            raise InvoiceStorageError('LIBRARY_CAPACITY', 'The invoice file exceeds the supported size.', 413)
        data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise InvoiceStorageError('LIBRARY_CAPACITY', 'The invoice file exceeds the supported size.', 413)
        return data


def _decode(data):
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        raise InvoiceStorageError('INVALID_LIBRARY', 'The invoice file is incomplete or invalid. Reconnect or recover a verified copy.') from None


def _atomic(directory, name, data, replace=True, expected_data=None):
    """Publish only complete bytes; a failed write leaves its target untouched."""
    temporary = '.invoice-' + str(uuid.uuid4())
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    owned = _identity(os.fstat(descriptor))
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            if expected_data is not None and _read_file(directory, name, MAX_DATABASE_BYTES) != expected_data:
                raise InvoiceStorageError('REVISION_CONFLICT', 'The invoice library changed while saving. Reload before saving.', 409)
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            exclusive_rename(temporary, name, directory)
        os.fsync(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            current = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
            if _identity(current) == owned:
                os.unlink(temporary, dir_fd=directory)


@contextlib.contextmanager
def _lock(directory):
    import fcntl

    descriptor = os.open('.invoice.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise InvoiceStorageError('UNSAFE_FILE', 'The invoice lock is not a regular file.', 503)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _database(data=None):
    connection = sqlite3.connect(':memory:')
    try:
        if data is None:
            connection.executescript('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);'
                                     'CREATE TABLE records (collection TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(collection,id));'
                                     'CREATE TABLE history (revision INTEGER PRIMARY KEY, changed_at TEXT NOT NULL, snapshot TEXT NOT NULL, event_json TEXT NOT NULL);')
        else:
            connection.deserialize(data)
        connection.execute('PRAGMA trusted_schema=OFF')
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise InvoiceStorageError('INVALID_DATABASE', 'The invoice database failed its integrity check.')
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1").fetchone() is not None:
            raise InvoiceStorageError('INVALID_DATABASE', 'The invoice database contains an unsupported schema object.')
        expected = {'meta': ['key', 'value'], 'records': ['collection', 'id', 'payload'],
                    'history': ['revision', 'changed_at', 'snapshot', 'event_json']}
        if {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} != set(expected):
            raise InvoiceStorageError('INVALID_DATABASE', 'The invoice database tables are invalid.')
        for table, names in expected.items():
            if [row[1] for row in connection.execute('PRAGMA table_info(' + table + ')')] != names:
                raise InvoiceStorageError('INVALID_DATABASE', 'The invoice database columns are invalid.')
        return connection
    except (sqlite3.Error, InvoiceStorageError):
        connection.close()
        raise InvoiceStorageError('INVALID_DATABASE', 'The invoice database is incomplete or invalid.') from None


def _state_from_database(data):
    connection = _database(data)
    try:
        state = {key: _decode(value) for key, value in connection.execute('SELECT key,value FROM meta')}
        state.update({key: {} for key in COLLECTION_LIMITS})
        for collection, key, value in connection.execute('SELECT collection,id,payload FROM records'):
            if collection not in COLLECTION_LIMITS:
                raise InvoiceStorageError('INVALID_DATABASE', 'The invoice database contains unsupported records.')
            state[collection][key] = _decode(value)
        _validate(state)
        _encode(state, MAX_LIBRARY_BYTES)
        return state
    except sqlite3.Error:
        raise InvoiceStorageError('INVALID_DATABASE', 'The invoice database schema is invalid.') from None
    finally:
        connection.close()


def _event(event):
    event = {} if event is None else event
    if not isinstance(event, dict) or set(event) - {'action', 'business_id', 'document_id'}:
        raise InvoiceStorageError('INVALID_EVENT', 'The invoice history event is invalid.')
    action = event.get('action', 'saved')
    if not isinstance(action, str) or re.fullmatch('[a-z][a-z0-9_-]{0,79}', action) is None:
        raise InvoiceStorageError('INVALID_EVENT', 'The invoice history action is invalid.')
    result = {'action': action, 'business_id': event.get('business_id'), 'document_id': event.get('document_id')}
    for field in ('business_id', 'document_id'):
        value = result[field]
        if value is not None:
            try:
                if str(uuid.UUID(value)) != value:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise InvoiceStorageError('INVALID_EVENT', 'The invoice history identity is invalid.') from None
    return result


def _state_database(state, previous=None, event=None):
    _validate(state)
    snapshot = _encode(state, MAX_LIBRARY_BYTES).decode('utf-8')
    connection = _database(previous)
    try:
        with connection:
            connection.executemany('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)',
                                   [(key, json.dumps(state[key])) for key in ('schema_version', 'library_id', 'revision')])
            connection.execute('DELETE FROM records')
            connection.executemany('INSERT INTO records(collection,id,payload) VALUES (?,?,?)',
                                   [(collection, key, _encode(value, MAX_LIBRARY_BYTES).decode('utf-8'))
                                    for collection in COLLECTION_LIMITS for key, value in state[collection].items()])
            connection.execute('INSERT INTO history(revision,changed_at,snapshot,event_json) VALUES (?,?,?,?)',
                               (state['revision'], datetime.now(timezone.utc).isoformat(), snapshot, _encode(_event(event), 1024).decode('utf-8')))
        result = connection.serialize()
        if len(result) > MAX_DATABASE_BYTES:
            raise InvoiceStorageError('LIBRARY_CAPACITY', 'The invoice database history exceeds the supported capacity.', 413)
        return result
    except sqlite3.Error:
        raise InvoiceStorageError('INVALID_DATABASE', 'The invoice database history is inconsistent.') from None
    finally:
        connection.close()


@contextlib.contextmanager
def _child(directory, name, create=False):
    if create:
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, 0o700, dir_fd=directory)
    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        yield child
    finally:
        os.close(child)


def _archive_path(name):
    return (name == 'config/officekit.sqlite3' or
            re.fullmatch(r'assets/logos/[0-9a-f]{64}\.png', name) is not None or
            re.fullmatch(r'data/[0-9]{4}/(?:0[1-9]|1[0-2])/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf', name) is not None)


def _collect(directory, prefix):
    files = {}
    for name in sorted(os.listdir(directory)):
        path = prefix + '/' + name
        metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            if re.fullmatch(r'assets/logos|data/[0-9]{4}|data/[0-9]{4}/(?:0[1-9]|1[0-2])', path) is None:
                raise InvoiceStorageError('INVALID_BACKUP', 'The invoice archive folder contains an unsupported directory.')
            with _child(directory, name) as child:
                files.update(_collect(child, path))
        else:
            if not _archive_path(path):
                raise InvoiceStorageError('INVALID_BACKUP', 'The invoice archive folder contains an unsupported file.')
            files[path] = _read_file(directory, name, MAX_PDF_BYTES)
        if len(files) > MAX_BACKUP_FILES or sum(map(len, files.values())) > MAX_BACKUP_BYTES:
            raise InvoiceStorageError('BACKUP_CAPACITY', 'The invoice backup exceeds the supported capacity.', 413)
    return files


def _unpack_backup(data):
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_BACKUP_BYTES:
        raise InvoiceStorageError('BACKUP_CAPACITY', 'The invoice backup exceeds the supported capacity.', 413)
    files, total = {}, 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_BACKUP_FILES:
                raise InvoiceStorageError('BACKUP_CAPACITY', 'The invoice backup contains too many files.', 413)
            for entry in entries:
                mode = entry.external_attr >> 16
                if not _archive_path(entry.filename) or entry.filename in files or entry.flag_bits & 1 or stat.S_ISLNK(mode):
                    raise InvoiceStorageError('INVALID_BACKUP', 'The invoice backup contains an unsafe or repeated entry.')
                total += entry.file_size
                if total > MAX_BACKUP_BYTES:
                    raise InvoiceStorageError('BACKUP_CAPACITY', 'The invoice backup expands beyond the supported capacity.', 413)
                maximum = MAX_DATABASE_BYTES if entry.filename.startswith('config/') else (MAX_ASSET_BYTES if entry.filename.startswith('assets/') else MAX_PDF_BYTES)
                if entry.file_size > maximum:
                    raise InvoiceStorageError('BACKUP_CAPACITY', 'A file in the invoice backup exceeds the supported size.', 413)
                content = archive.read(entry)
                if entry.filename.startswith('assets/') and hashlib.sha256(content).hexdigest() != entry.filename.rsplit('/', 1)[1][:-4]:
                    raise InvoiceStorageError('INVALID_BACKUP', 'A logo in the invoice backup failed its integrity check.')
                if entry.filename.startswith('data/') and not content.startswith(b'%PDF-'):
                    raise InvoiceStorageError('INVALID_BACKUP', 'An archived invoice in the backup is invalid.')
                files[entry.filename] = content
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError):
        raise InvoiceStorageError('INVALID_BACKUP', 'The invoice backup is incomplete or invalid.') from None
    if 'config/officekit.sqlite3' not in files:
        raise InvoiceStorageError('INVALID_BACKUP', 'The invoice backup has no database.')
    _state_from_database(files['config/officekit.sqlite3'])
    return files


class LibraryRepository:
    def __init__(self, parent, parent_identity, root_identity=None, create=True):
        self.parent = os.fspath(parent)
        self.parent_identity = tuple(parent_identity)
        self.root_identity = None if root_identity is None else tuple(root_identity)
        self._state = None
        self._digest = None
        with _storage_errors(), self._directory(create) as root, _child(root, 'config', create) as directory, _lock(directory):
            try:
                data = _read_file(directory, 'officekit.sqlite3', MAX_DATABASE_BYTES)
            except FileNotFoundError:
                if not create:
                    raise
                state = {key: {} for key in COLLECTION_LIMITS}
                state.update(schema_version=1, library_id=str(uuid.uuid4()), revision=0)
                data = _state_database(state)
                _atomic(directory, 'officekit.sqlite3', data, replace=False)
            self._adopt(data)

    @property
    def library_id(self):
        return self._state['library_id']

    @contextlib.contextmanager
    def _directory(self, create=False):
        if os.open not in os.supports_dir_fd or not hasattr(os, 'O_NOFOLLOW'):
            raise InvoiceStorageError('UNSUPPORTED_FILESYSTEM', 'Safe invoice folder access is unavailable on this platform.', 503)
        with open_parent(os.path.join(self.parent, '.invoice-parent')) as parent:
            if _identity(os.fstat(parent)) != self.parent_identity:
                raise InvoiceStorageError('FOLDER_CHANGED', 'The selected invoice folder changed. Choose it again.', 409)
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(ROOT_NAME, 0o700, dir_fd=parent)
            directory = os.open(ROOT_NAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                identity = _identity(os.fstat(directory))
                if self.root_identity is not None and identity != self.root_identity:
                    raise InvoiceStorageError('FOLDER_CHANGED', 'The invoice library directory changed. Choose it again.', 409)
                self.root_identity = identity
                yield directory
                if _identity(os.stat(ROOT_NAME, dir_fd=parent, follow_symlinks=False)) != identity:
                    raise InvoiceStorageError('FOLDER_CHANGED', 'The invoice library directory changed during access.', 409)
            finally:
                os.close(directory)

    def _adopt(self, data):
        state = _state_from_database(data)
        if self._state is not None and state['library_id'] != self.library_id:
            raise InvoiceStorageError('LIBRARY_CHANGED', 'The folder contains a different invoice library.', 409)
        self._state = state
        self._digest = hashlib.sha256(data).digest()

    def _unchanged(self, directory):
        with self._directory():
            pass
        data = _read_file(directory, 'officekit.sqlite3', MAX_DATABASE_BYTES)
        if hashlib.sha256(data).digest() != self._digest:
            raise InvoiceStorageError('REVISION_CONFLICT', 'The invoice library changed outside OfficeKit. Reload before saving.', 409)
        return data

    def read(self):
        with _storage_errors(), self._directory() as root, _child(root, 'config') as directory:
            self._unchanged(directory)
            return copy.deepcopy(self._state)

    def reload(self):
        with _storage_errors(), self._directory() as root, _child(root, 'config') as directory, _lock(directory):
            self._adopt(_read_file(directory, 'officekit.sqlite3', MAX_DATABASE_BYTES))
            return copy.deepcopy(self._state)

    def transaction(self, expected_revision, mutate, event=None):
        with _storage_errors(), self._directory() as root, _child(root, 'config') as directory, _lock(directory):
            previous = self._unchanged(directory)
            if type(expected_revision) is not int or expected_revision != self._state['revision']:
                raise InvoiceStorageError('REVISION_CONFLICT', 'The invoice library changed. Reload before saving.', 409)
            state = copy.deepcopy(self._state)
            result = mutate(state)
            state['revision'] = expected_revision + 1
            _validate(state)
            if state['library_id'] != self.library_id:
                raise InvoiceStorageError('LIBRARY_CHANGED', 'An invoice transaction cannot change library identity.', 409)
            data = _state_database(state, previous, event)
            self._unchanged(directory)
            _atomic(directory, 'officekit.previous.sqlite3', previous)
            self._unchanged(directory)
            _atomic(directory, 'officekit.sqlite3', data, expected_data=previous)
            self._adopt(data)
            if isinstance(result, dict):
                result = copy.deepcopy(result)
                result['library_revision'] = state['revision']
            return result

    def put_asset(self, data):
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_ASSET_BYTES:
            raise InvoiceStorageError('ASSET_CAPACITY', 'The invoice logo exceeds the supported size.', 413)
        digest = hashlib.sha256(data).hexdigest()
        with _storage_errors(), self._directory() as directory:
            with _child(directory, 'assets', True) as asset_root, _child(asset_root, 'logos', True) as assets:
                name = digest + '.png'
                try:
                    existing = _read_file(assets, name, MAX_ASSET_BYTES)
                except FileNotFoundError:
                    _atomic(assets, name, data, replace=False)
                else:
                    if existing != data:
                        raise InvoiceStorageError('ASSET_CHANGED', 'The saved invoice logo failed its integrity check.', 409)
        return digest

    def read_asset(self, digest):
        if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
            raise InvoiceStorageError('INVALID_ASSET', 'The invoice logo identifier is invalid.')
        with _storage_errors(), self._directory() as directory:
            with _child(directory, 'assets') as asset_root, _child(asset_root, 'logos') as assets:
                data = _read_file(assets, digest + '.png', MAX_ASSET_BYTES)
            if hashlib.sha256(data).hexdigest() != digest:
                raise InvoiceStorageError('ASSET_CHANGED', 'The saved invoice logo failed its integrity check.', 409)
            return data

    def history(self):
        with _storage_errors(), self._directory() as root, _child(root, 'config') as config:
            connection = _database(self._unchanged(config))
            try:
                rows = []
                for revision, changed_at, event_json in connection.execute('SELECT revision,changed_at,event_json FROM history ORDER BY revision'):
                    event = _event(_decode(event_json))
                    rows.append({'revision': revision, 'changed_at': changed_at, **event,
                                 'summary': event['action'].replace('_', ' ').replace('-', ' ')})
                return rows
            finally:
                connection.close()

    def archive_document(self, document_id, issue_date, data):
        try:
            if str(uuid.UUID(document_id)) != document_id:
                raise ValueError()
            issued = date.fromisoformat(issue_date)
        except (ValueError, TypeError, AttributeError):
            raise InvoiceStorageError('INVALID_ARCHIVE', 'The invoice archive identity or date is invalid.') from None
        if not isinstance(data, bytes) or not data.startswith(b'%PDF-') or len(data) > MAX_PDF_BYTES:
            raise InvoiceStorageError('INVALID_ARCHIVE', 'The invoice archive requires a supported PDF.')
        year, month, name = f'{issued.year:04d}', f'{issued.month:02d}', document_id + '.pdf'
        with _storage_errors(), self._directory() as root, _child(root, 'data', True) as folder, _child(folder, year, True) as years, _child(years, month, True) as months:
            try:
                previous = _read_file(months, name, MAX_PDF_BYTES)
            except FileNotFoundError:
                _atomic(months, name, data, replace=False)
            else:
                if previous != data:
                    raise InvoiceStorageError('ARCHIVE_CHANGED', 'This issued invoice already has a different archived PDF.', 409)
        return f'data/{year}/{month}/{name}'

    def backup(self):
        with _storage_errors(), self._directory() as root, _child(root, 'config') as config, _lock(config):
            source = _database(self._unchanged(config))
            target = _database()
            try:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise InvoiceStorageError('INVALID_DATABASE', 'The invoice backup failed database verification.')
                files = {'config/officekit.sqlite3': target.serialize()}
            finally:
                target.close()
                source.close()
            for name in ('assets', 'data'):
                try:
                    with _child(root, name) as child:
                        files.update(_collect(child, name))
                except FileNotFoundError:
                    continue
            if len(files) > MAX_BACKUP_FILES or sum(map(len, files.values())) > MAX_BACKUP_BYTES:
                raise InvoiceStorageError('BACKUP_CAPACITY', 'The invoice backup exceeds the supported capacity.', 413)
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
                for name, content in files.items():
                    archive.writestr(name, content)
            data = output.getvalue()
            _unpack_backup(data)
            self._unchanged(config)
            with _child(root, 'backups', True) as backups:
                _atomic(backups, 'officekit-' + str(uuid.uuid4()) + '.zip', data, replace=False)
            return data


class InvoiceLibraries:
    def __init__(self, selections, settings_path):
        self.selections = selections
        self.settings_path = os.path.abspath(os.fspath(settings_path))
        self.repositories = {}
        self.bindings = {}
        self._bindings_error = None
        try:
            self._load_bindings()
        except InvoiceStorageError as error:
            self._bindings_error = error

    def _load_bindings(self):
        if os.path.lexists(self.settings_path):
            with _storage_errors(), open_parent(self.settings_path) as directory:
                bindings = _decode(_read_file(directory, os.path.basename(self.settings_path), 1024 * 1024))
            if not isinstance(bindings, dict) or len(bindings) > 100:
                raise InvoiceStorageError('INVALID_BINDINGS', 'The saved invoice folders are invalid.')
            for key, binding in bindings.items():
                if not isinstance(binding, dict) or set(binding) != {'parent', 'parent_identity', 'root_identity', 'label'}:
                    raise InvoiceStorageError('INVALID_BINDINGS', 'The saved invoice folder record is invalid.')
                if not isinstance(binding['parent'], str) or not os.path.isabs(binding['parent']):
                    raise InvoiceStorageError('INVALID_BINDINGS', 'The saved invoice folder path is invalid.')
                for field in ('parent_identity', 'root_identity'):
                    identity = binding[field]
                    if not isinstance(identity, list) or len(identity) != 2 or not all(type(part) is int and part >= 0 for part in identity):
                        raise InvoiceStorageError('INVALID_BINDINGS', 'The saved invoice folder identity is invalid.')
                if not isinstance(binding['label'], str) or not 1 <= len(binding['label']) <= 160:
                    raise InvoiceStorageError('INVALID_BINDINGS', 'The saved invoice folder label is invalid.')
                self.bindings[key] = binding

    def _bindings_ready(self):
        if self._bindings_error is not None:
            raise self._bindings_error

    def _save_bindings(self):
        data = _encode(self.bindings, 1024 * 1024)
        parent = os.path.dirname(self.settings_path)
        with _storage_errors():
            checked_path(parent)
            os.makedirs(parent, mode=0o700, exist_ok=True)
            with open_parent(self.settings_path) as directory:
                _atomic(directory, os.path.basename(self.settings_path), data)

    def attach(self, selection_id):
        self._bindings_ready()
        try:
            selection = self.selections.get(selection_id, write=True)
        except (PermissionError, FileNotFoundError):
            raise InvoiceStorageError('SELECTION_UNAVAILABLE', 'Choose an invoice folder with read and write access.', 403) from None
        if len(selection.roots) != 1 or not selection.roots[0][2]:
            raise InvoiceStorageError('INVALID_FOLDER', 'Choose one folder for the invoice library.')
        parent, identity, _ = selection.roots[0]
        repo = LibraryRepository(parent, identity)
        binding = {'parent': parent, 'parent_identity': list(identity), 'root_identity': list(repo.root_identity), 'label': (os.path.basename(parent) or 'Invoice library')[:160]}
        if repo.library_id not in self.bindings and len(self.bindings) >= 100:
            raise InvoiceStorageError('BINDING_CAPACITY', 'There are already 100 remembered invoice folders.', 413)
        self.bindings[repo.library_id] = binding
        self._save_bindings()
        self.repositories[repo.library_id] = repo
        return self._metadata(repo)

    def reconnect(self, library_id, credential):
        self._bindings_ready()
        self.selections.authorize(credential)
        if library_id not in self.bindings:
            raise InvoiceStorageError('LIBRARY_NOT_FOUND', 'The remembered invoice folder is unavailable.', 404)
        binding = self.bindings[library_id]
        repo = LibraryRepository(binding['parent'], binding['parent_identity'], binding['root_identity'], create=False)
        if repo.library_id != library_id:
            raise InvoiceStorageError('LIBRARY_CHANGED', 'The folder contains a different invoice library.', 409)
        self.repositories[library_id] = repo
        return self._metadata(repo)

    def get(self, library_id):
        if library_id not in self.repositories:
            raise InvoiceStorageError('LIBRARY_NOT_FOUND', 'Choose or reconnect the invoice folder first.', 404)
        return self.repositories[library_id]

    def _metadata(self, repo):
        state = repo.read()
        return {'id': repo.library_id, 'library_id': repo.library_id, 'label': self.bindings[repo.library_id]['label'],
                'status': 'ready', 'revision': state['revision'], 'businesses': list(state['businesses'].values()),
                'capabilities': {'write': True, 'direct_folder': True, 'sync': False}}

    def list_bindings(self):
        self._bindings_ready()
        return [{'id': key, 'library_id': key, 'label': value['label'], 'status': 'reconnect-required'} for key, value in self.bindings.items()]

    def restore(self, destination_selection_id, backup_selection_id):
        try:
            destination = self.selections.get(destination_selection_id, write=True)
            selected_backup = self.selections.get(backup_selection_id)
        except (PermissionError, FileNotFoundError):
            raise InvoiceStorageError('SELECTION_UNAVAILABLE', 'Choose a backup file and a writable destination folder.', 403) from None
        if len(destination.roots) != 1 or not destination.roots[0][2] or len(selected_backup.roots) != 1 or selected_backup.roots[0][2]:
            raise InvoiceStorageError('INVALID_FOLDER', 'Choose one backup file and one destination folder.')
        backup_path, backup_identity, _ = selected_backup.roots[0]
        parent_path, parent_identity, _ = destination.roots[0]
        with _storage_errors(), open_parent(backup_path) as directory:
            if _identity(os.stat(os.path.basename(backup_path), dir_fd=directory, follow_symlinks=False)) != tuple(backup_identity):
                raise InvoiceStorageError('BACKUP_CHANGED', 'The selected backup changed. Choose it again.', 409)
            files = _unpack_backup(_read_file(directory, os.path.basename(backup_path), MAX_BACKUP_BYTES, backup_identity))
        with _storage_errors(), open_parent(os.path.join(parent_path, '.invoice-parent')) as parent:
            if _identity(os.fstat(parent)) != tuple(parent_identity):
                raise InvoiceStorageError('FOLDER_CHANGED', 'The selected restore folder changed. Choose it again.', 409)
            try:
                os.mkdir(ROOT_NAME, 0o700, dir_fd=parent)
            except FileExistsError:
                raise InvoiceStorageError('RESTORE_DESTINATION_EXISTS', 'Choose a new destination without an invoice library.', 409) from None
            with _child(parent, ROOT_NAME) as root:
                for name, content in files.items():
                    parts = name.split('/')
                    with contextlib.ExitStack() as stack:
                        target = root
                        for part in parts[:-1]:
                            target = stack.enter_context(_child(target, part, True))
                        _atomic(target, parts[-1], content, replace=False)
        return self.attach(destination_selection_id)
