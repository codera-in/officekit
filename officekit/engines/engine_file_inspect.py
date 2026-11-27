"""Read-only inspection kinds for the files slice: file info, file age, empty files,
comparison of two single files, and empty folders.

Nothing here writes, renames or removes. Reads go through the selection store's
no-follow, identity-checked helpers, or through held parent descriptors for
metadata-only calls. Results carry selection-relative names; host paths never
leave this module except through reveal items.
"""

import codecs
import difflib
import errno
import hashlib
import os
import stat
from collections import Counter, deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .engine_file_selections import MAX_ENTRIES, SelectedFile, checked_path, identity, open_parent
from .engine_storage_cleaner import PROTECTED as PROTECTED_NAMES

CHUNK_BYTES = 1024 * 1024
DESCRIPTOR_WALK = os.name != 'nt'
MAX_COMPARE_TEXT_BYTES = 2 * 1024 * 1024
MAX_HUNKS = 200
MAX_HUNK_LINES = 40
MAX_LINE_CHARS = 500
MAX_DIFF_LINES = 20_000
BYTE_WINDOW = 16
MAX_EPOCH = 253_402_300_799
NANOSECONDS = 1_000_000_000
UF_HIDDEN = getattr(stat, 'UF_HIDDEN', 0x8000)
BOM = b'\xef\xbb\xbf'
BUNDLE_SUFFIXES = ('.app', '.bundle', '.framework')
BIRTH_LIMIT_NOTE = 'Created dates are unavailable where the platform does not report birth time.'

MAX_LINK_HOPS = 40
WINDOWS_REPARSE_POINT = 0x400
DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
INSPECT_KINDS = frozenset({'file-info', 'compare-files', 'file-age', 'empty-files', 'empty-folders', 'symlinks'})
DEVELOPMENT_ONLY_KINDS = INSPECT_KINDS


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, populate_by_name=True)


class SubfolderOptions(_StrictModel):
    include_subfolders: bool = Field(default=False, alias='includeSubfolders')


class FileAgeOptions(SubfolderOptions):
    date_field: Literal['modified', 'created'] = Field(default='modified', alias='dateField')
    not_before: int | None = Field(default=None, ge=0, le=MAX_EPOCH, alias='notBefore')
    not_after: int | None = Field(default=None, ge=0, le=MAX_EPOCH, alias='notAfter')

    @model_validator(mode='after')
    def validate_bounds(self):
        if self.not_before is None and self.not_after is None:
            raise ValueError('Choose a start date, an end date or both')
        if self.not_before is not None and self.not_after is not None and self.not_before > self.not_after:
            raise ValueError('Start date must not be after end date')
        return self


def _stat_selected(item):
    """Metadata for one selected file, without opening it. Changed files fail closed."""
    with open_parent(item.path) as parent:
        if parent is None:
            value = os.lstat(checked_path(item.path))
        else:
            value = os.stat(os.path.basename(item.path), dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISREG(value.st_mode) or identity(value) != item.signature:
        raise ValueError('Selected file changed; select it again')
    return value


def _is_hidden(basename, value):
    return basename.startswith('.') or bool(getattr(value, 'st_flags', 0) & UF_HIDDEN)


def _skipped_rows(stats):
    return [{'name': name, 'reason': reason} for name, reason in stats.get('rows', [])]


def _denied(stats):
    return stats.get('denied_folders', 0)


def file_info(items, stats, *, check, dates):
    rows, total_bytes, missing_birth = [], 0, False
    for item in items:
        check()
        value = _stat_selected(item)
        row_dates = dates(item)
        missing_birth = missing_birth or row_dates['created_at'] is None
        basename = os.path.basename(item.path)
        rows.append({
            'id': item.id,
            'name': item.name,
            'size_bytes': item.signature[2],
            **row_dates,
            'mode': stat.filemode(value.st_mode)[1:],
            'hidden': _is_hidden(basename, value),
            'hard_links': value.st_nlink,
            'extension': os.path.splitext(basename)[1].lower(),
        })
        total_bytes += item.signature[2]
    return {
        'files': rows,
        'skipped': _skipped_rows(stats),
        'skipped_truncated': stats.get('rows_dropped', 0),
        'total_files': len(rows),
        'total_bytes': total_bytes,
        'skipped_links': stats.get('skipped_links', 0),
        'denied_folders': _denied(stats),
        'platform_limits': [BIRTH_LIMIT_NOTE] if missing_birth else [],
        'complete': _denied(stats) == 0,
    }


def _date_ns(item, date_field):
    if date_field == 'created':
        return item.signature[5] if len(item.signature) > 5 else None
    return item.signature[3]


def file_age(items, stats, *, options, check, dates):
    date_field = options['date_field']
    not_before, not_after = options['not_before'], options['not_after']
    # Bounds are whole seconds and include the entire second they name.
    low_ns = None if not_before is None else not_before * NANOSECONDS
    high_ns = None if not_after is None else (not_after + 1) * NANOSECONDS
    files, scanned, matched_bytes, unavailable = [], 0, 0, 0
    for item in items:
        check()
        scanned += 1
        moment = _date_ns(item, date_field)
        if moment is None:
            unavailable += 1
            continue
        if (low_ns is not None and moment < low_ns) or (high_ns is not None and moment >= high_ns):
            continue
        files.append({'id': item.id, 'name': item.name, 'size_bytes': item.signature[2], **dates(item)})
        matched_bytes += item.signature[2]
    return {
        'files': files,
        'scanned': scanned,
        'matched': len(files),
        'matched_bytes': matched_bytes,
        'unavailable_dates': unavailable,
        'date_field': date_field,
        'not_before': not_before,
        'not_after': not_after,
        'complete': _denied(stats) == 0,
    }


class _Side:
    """Single pass over one file: digest, UTF-8/NUL gate, and bounded text retention."""

    def __init__(self):
        self.digest = hashlib.sha256()
        self.decoder = codecs.getincrementaldecoder('utf-8')()
        self.text_ok = True
        self.size = 0
        self.head = b''
        self.keep = bytearray()

    def feed(self, chunk):
        self.digest.update(chunk)
        self.size += len(chunk)
        if len(self.head) < len(BOM):
            self.head = (self.head + chunk[:len(BOM)])[:len(BOM)]
        if self.text_ok:
            if b'\x00' in chunk:
                self.text_ok = False
            else:
                try:
                    self.decoder.decode(chunk)
                except UnicodeDecodeError:
                    self.text_ok = False
        if self.keep is not None:
            if self.text_ok and self.size <= MAX_COMPARE_TEXT_BYTES:
                self.keep += chunk
            else:
                self.keep = None

    def finish(self):
        if self.text_ok:
            try:
                self.decoder.decode(b'', final=True)
            except UnicodeDecodeError:
                self.text_ok = False
                self.keep = None

    def encoding(self):
        if not self.text_ok:
            return 'binary'
        return 'utf-8-bom' if self.head == BOM else 'utf-8'


def _line_endings(text):
    crlf = text.count('\r\n')
    lf = text.count('\n') - crlf
    cr = text.count('\r') - crlf
    kinds = [name for name, count in (('crlf', crlf), ('lf', lf), ('cr', cr)) if count]
    if not kinds:
        return 'none'
    return kinds[0] if len(kinds) == 1 else 'mixed'


def _normalized_text(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _normalized_lines(text):
    if not text:
        return []
    normalized = _normalized_text(text)
    lines = normalized.split('\n')
    if normalized.endswith('\n'):
        lines.pop()
    return lines


def _text_hunks(left_text, right_text, check):
    left, right = _normalized_lines(left_text), _normalized_lines(right_text)
    if len(left) > MAX_DIFF_LINES or len(right) > MAX_DIFF_LINES:
        return [], True
    truncated = False
    hunks = []
    check()
    matcher = difflib.SequenceMatcher(None, left, right)
    for group in matcher.get_grouped_opcodes(3):
        check()
        if len(hunks) == MAX_HUNKS:
            truncated = True
            break
        lines = []
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                lines.extend((' ', line) for line in left[i1:i2])
            else:
                lines.extend(('-', line) for line in left[i1:i2])
                lines.extend(('+', line) for line in right[j1:j2])
        if len(lines) > MAX_HUNK_LINES:
            lines = lines[:MAX_HUNK_LINES]
            truncated = True
        first, last = group[0], group[-1]
        hunks.append({
            'a_start': first[1] + 1 if last[2] > first[1] else first[1],
            'a_lines': last[2] - first[1],
            'b_start': first[3] + 1 if last[4] > first[3] else first[3],
            'b_lines': last[4] - first[3],
            'lines': [{'op': op, 'text': text[:MAX_LINE_CHARS]} for op, text in lines],
        })
    return hunks, truncated


def compare_files(first, second, *, check, open_file):
    left, right = _Side(), _Side()
    first_difference = None
    offset = 0
    with open_file(first) as source_a, open_file(second) as source_b:
        while True:
            check()
            chunk_a = source_a.read(CHUNK_BYTES)
            chunk_b = source_b.read(CHUNK_BYTES)
            if not chunk_a and not chunk_b:
                break
            if first_difference is None:
                shared = min(len(chunk_a), len(chunk_b))
                if memoryview(chunk_a)[:shared] != memoryview(chunk_b)[:shared]:
                    first_difference = offset + next(index for index in range(shared) if chunk_a[index] != chunk_b[index])
                elif len(chunk_a) != len(chunk_b):
                    first_difference = offset + shared
            left.feed(chunk_a)
            right.feed(chunk_b)
            offset += max(len(chunk_a), len(chunk_b))
        window_a = window_b = None
        if first_difference is not None:
            source_a.seek(first_difference)
            window_a = source_a.read(BYTE_WINDOW).hex()
            source_b.seek(first_difference)
            window_b = source_b.read(BYTE_WINDOW).hex()
    left.finish()
    right.finish()
    both_text = left.text_ok and right.text_ok
    if not both_text:
        mode = 'binary'
    elif max(left.size, right.size) > MAX_COMPARE_TEXT_BYTES:
        mode = 'text-too-large'
    else:
        mode = 'text'
    text_a = text_b = None
    hunks, truncated = [], False
    ignoring_endings = None
    if mode == 'text':
        text_a = bytes(left.keep).decode('utf-8')
        text_b = bytes(right.keep).decode('utf-8')
        hunks, truncated = _text_hunks(text_a, text_b, check)
        ignoring_endings = _normalized_text(text_a) == _normalized_text(text_b)
    return {
        'equal': first_difference is None,
        'same_file': first.signature[:2] == second.signature[:2],
        'size_a': left.size,
        'size_b': right.size,
        'sha256_a': left.digest.hexdigest(),
        'sha256_b': right.digest.hexdigest(),
        'first_difference_offset': first_difference,
        'bytes_a': window_a,
        'bytes_b': window_b,
        'mode': mode,
        'encoding_a': left.encoding(),
        'encoding_b': right.encoding(),
        'line_endings_a': _line_endings(text_a) if text_a is not None else None,
        'line_endings_b': _line_endings(text_b) if text_b is not None else None,
        'equal_ignoring_line_endings': ignoring_endings,
        'hunks': hunks,
        'truncated': truncated,
        'complete': True,
    }


def _entry_stat(entry):
    return entry.stat(follow_symlinks=False)


def _display_name(prefix, root, path):
    if path == root:
        return prefix + (os.path.basename(root) or 'Selected folder')
    return prefix + os.path.relpath(path, root).replace(os.sep, '/')


class _FolderScan:
    def __init__(self, check):
        self.check = check
        self.entries = 0
        self.frames = 0
        self.seen = {}
        self.rows = []
        self.counts = {'links': 0, 'other_volume': 0, 'bundles': 0, 'protected': 0, 'denied': 0}

    def step(self):
        self.check()
        self.entries += 1
        if self.entries > MAX_ENTRIES:
            raise ValueError('Selection exceeds scan entry limit')


def _open_listed_folder(path, signature):
    """Open a folder by name under a no-follow parent, and fail closed if it is no longer the listed folder.

    A child swapped for a link (or replaced) after its parent was listed raises FileExistsError
    (P-026/P-027). The check compares only device, inode and the directory type: an entry written into
    the folder changes its mtime and ctime but does not make it a different folder (CR-8). A missing
    child fails the job with its own error; only an unreadable child is counted as denied (CR-10).
    Without descriptor-based opens (Windows, DESCRIPTOR_WALK false) the walk refuses, because junctions
    cannot be detected there (CR-9).
    """
    if not DESCRIPTOR_WALK:
        raise ValueError('Folder checks need macOS or Linux.')
    try:
        with open_parent(path) as parent:
            descriptor = os.open(os.path.basename(path), DIRECTORY_FLAGS, dir_fd=parent)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise FileExistsError('Folder changed during scan') from exc
        raise
    opened = os.fstat(descriptor)
    if (opened.st_dev, opened.st_ino) != (signature[0], signature[1]) or not stat.S_ISDIR(opened.st_mode):
        os.close(descriptor)
        raise FileExistsError('Folder changed during scan')
    return descriptor


def _open_folder(scan, path, root, prefix, root_device, depth, signature):
    """List one folder without following links. Children are resolved later, bottom-up."""
    frame = {'path': path, 'root': root, 'prefix': prefix, 'depth': depth, 'signature': signature,
             'visible': False, 'hidden': False, 'nested': 0, 'pending': []}
    scan.frames += 1
    try:
        descriptor = _open_listed_folder(path, signature)
        try:
            # Stat while the descriptor is open: DirEntry.stat is resolved against the listed folder.
            with os.scandir(descriptor) as iterator:
                entries = [(entry, _entry_stat(entry)) for entry in iterator]
        finally:
            os.close(descriptor)
    except PermissionError:
        if depth == 0:
            raise
        scan.counts['denied'] += 1
        frame['visible'] = True
        return frame
    for entry, value in entries:
        scan.step()
        name = entry.name
        if entry.is_symlink():
            scan.counts['links'] += 1
            frame['visible'] = True
            continue
        if stat.S_ISDIR(value.st_mode):
            if name in PROTECTED_NAMES:
                scan.counts['protected'] += 1
                frame['visible'] = True
            elif name.lower().endswith(BUNDLE_SUFFIXES):
                scan.counts['bundles'] += 1
                frame['visible'] = True
            elif value.st_dev != root_device:
                scan.counts['other_volume'] += 1
                frame['visible'] = True
            else:
                frame['pending'].append((os.path.join(path, name), identity(value)))
        elif stat.S_ISREG(value.st_mode) and name.startswith('.'):
            frame['hidden'] = True
        else:
            frame['visible'] = True
    return frame


def _absorb(parent, basename, result):
    """Fold a resolved child into its parent. Only empty or hidden-only children are transparent."""
    if result['state'] == 'empty':
        parent['nested'] += 1 + result['nested']
    elif result['state'] == 'hidden-files-only' and basename.startswith('.'):
        parent['hidden'] = True
        parent['nested'] += result['nested']
    else:
        parent['visible'] = True


def _finish(scan, frame):
    if frame['visible']:
        state = 'content'
    elif frame['hidden']:
        state = 'hidden-files-only'
    else:
        state = 'empty'
    result = {'state': state, 'nested': frame['nested'], 'depth': frame['depth'], 'path': frame['path'],
              'root': frame['root'], 'signature': frame['signature'],
              'name': _display_name(frame['prefix'], frame['root'], frame['path'])}
    if state != 'content':
        scan.rows.append(result)
    return result


def _scan_root(scan, root, root_signature, prefix):
    root_device = root_signature[0]
    stack = [_open_folder(scan, root, root, prefix, root_device, 0, root_signature)]
    while stack:
        frame = stack[-1]
        if frame['pending']:
            child_path, child_signature = frame['pending'].pop()
            if child_path in scan.seen:
                _absorb(frame, os.path.basename(child_path), scan.seen[child_path])
                continue
            stack.append(_open_folder(scan, child_path, root, prefix, root_device, frame['depth'] + 1, child_signature))
            continue
        stack.pop()
        result = _finish(scan, frame)
        scan.seen[frame['path']] = result
        if stack:
            _absorb(stack[-1], os.path.basename(frame['path']), result)


def empty_folders(roots, *, selection_id, check):
    """Bottom-up empty and hidden-only folders. Returns (result, reveal items); removes nothing."""
    if any(not directory for _root, _root_id, directory in roots):
        raise ValueError('Choose a folder to check for empty folders')
    scan = _FolderScan(check)
    for index, (raw_root, root_id, _directory) in enumerate(roots):
        root = checked_path(raw_root)
        value = os.lstat(root)
        if identity(value)[:2] != root_id:
            raise ValueError('Selected root changed')
        if os.path.basename(root) in PROTECTED_NAMES:
            raise ValueError('Protected folders cannot be checked')
        if root in scan.seen:
            continue
        prefix = f'{index + 1}/' if len(roots) > 1 else ''
        _scan_root(scan, root, identity(value), prefix)
    folders, items = [], []
    for row in sorted(scan.rows, key=lambda value: value['name'].casefold()):
        if identity(os.lstat(checked_path(row['path']))) != row['signature']:
            raise FileExistsError('Folder changed during scan')
        item = SelectedFile(selection_id, row['root'], row['path'], row['name'], row['signature'])
        items.append(item)
        folders.append({'id': item.id, 'name': row['name'], 'state': row['state'],
                        'nested_empty_folders': row['nested'], 'depth': row['depth']})
    counts = scan.counts
    return {
        'folders': folders,
        'scanned_folders': scan.frames,
        'skipped_links': counts['links'],
        'skipped_other_volume': counts['other_volume'],
        'skipped_bundles': counts['bundles'],
        'excluded_protected': counts['protected'],
        'denied_folders': counts['denied'],
        'complete': counts['denied'] == 0,
    }, items


class _LimitReached(Exception):
    """The entry cap stopped the scan; the links resolved so far are kept as a partial result."""


class _LinkScan:
    def __init__(self, check, root):
        self.check = check
        self.root = root
        self.root_fd = None
        self.entries = 0
        self.listed = 0
        self.denied = 0
        self.limit_reached = False
        self.rows = []

    def step(self):
        """Count one listed entry against the cap; every step also runs the cancellation check."""
        self.check()
        self.entries += 1
        if self.entries > MAX_ENTRIES:
            raise _LimitReached()


def _below_root(root, target):
    """The components of an absolute target below the selected root, or None when it lies outside.

    The target is not normalised: a '..' in it is walked physically, the same as a relative link.
    """
    if target == root:
        return ''
    prefix = root.rstrip('/') + '/'
    return target[len(prefix):] if target.startswith(prefix) else None


def _follow(scan, parts):
    """Follow one link hop by hop and return (state, hops, first link text).

    Every component is looked up with a no-follow stat under a held descriptor, and a
    directory is only descended into by a no-follow open. The target itself is never
    opened or read. A target that leaves the selected root stops the walk at that hop.
    Resolution steps are not listed entries, so they only run the cancellation check.
    """
    stack, owned, visited = [scan.root_fd], [], []
    pending, points_to = deque(parts), None
    try:
        while pending:
            scan.check()
            name = pending.popleft()
            if name in ('', '.'):
                continue
            if name == '..':
                if len(stack) == 1:
                    return 'out-of-scope', len(visited), points_to
                os.close(owned.pop())
                stack.pop()
                continue
            value = os.stat(name, dir_fd=stack[-1], follow_symlinks=False)
            if stat.S_ISLNK(value.st_mode):
                key = (value.st_dev, value.st_ino)
                if key in visited:
                    return 'circular', len(visited), points_to
                if len(visited) >= MAX_LINK_HOPS:
                    return 'too-many-hops', len(visited), points_to
                visited.append(key)
                target = os.readlink(name, dir_fd=stack[-1])
                points_to = target if points_to is None else points_to
                if target.startswith('/'):
                    below = _below_root(scan.root, target)
                    if below is None:
                        return 'out-of-scope', len(visited), points_to
                    while len(stack) > 1:
                        os.close(owned.pop())
                        stack.pop()
                    target = below
                pending.extendleft(reversed(target.split('/')))
                continue
            if not pending:
                return 'inside', len(visited), points_to
            if not stat.S_ISDIR(value.st_mode):
                return 'broken', len(visited), points_to
            child = os.open(name, DIRECTORY_FLAGS, dir_fd=stack[-1])
            owned.append(child)
            stack.append(child)
        return 'inside', len(visited), points_to
    except PermissionError:
        return 'denied', len(visited), points_to
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return 'broken', len(visited), points_to
        if exc.errno == errno.ELOOP:
            # The name was a directory a moment ago and is a link now: the folder changed during the scan.
            raise FileExistsError('Folder changed during scan') from exc
        raise
    finally:
        for descriptor in owned:
            os.close(descriptor)


def _link_row(scan, parts, points_to, state, hops):
    kind = None if points_to is None else ('absolute' if points_to.startswith('/') else 'relative')
    row = {'name': parts[-1], 'relative_path': '/'.join(parts), 'points_to': points_to, 'type': kind,
           'state': state, 'hops': hops}
    scan.rows.append(row)


def _list_links(scan, descriptor, parts, include_subfolders, pending):
    with os.scandir(descriptor) as iterator:
        for entry in iterator:
            scan.step()
            scan.listed += 1
            child = (*parts, entry.name)
            if entry.is_symlink():
                state, hops, points_to = _follow(scan, child)
                _link_row(scan, child, points_to, state, hops)
            elif include_subfolders and entry.is_dir(follow_symlinks=False):
                value = entry.stat(follow_symlinks=False)
                pending.append((child, (value.st_dev, value.st_ino)))


def _walk_links(scan, root_id, include_subfolders):
    """List the root through the descriptor symlink_links already holds, then each listed subfolder by no-follow open."""
    pending = [((), root_id)]
    while pending:
        parts, signature = pending.pop()
        if not parts:
            _list_links(scan, scan.root_fd, parts, include_subfolders, pending)
            continue
        try:
            descriptor = _open_listed_folder(os.path.join(scan.root, *parts), signature)
        except PermissionError:
            scan.denied += 1
            continue
        try:
            _list_links(scan, descriptor, parts, include_subfolders, pending)
        finally:
            os.close(descriptor)


def _list_without_descriptors(scan, include_subfolders):
    """Platforms without descriptor walks cannot follow or check a link safely: each one is reported unsupported."""
    pending = [()]
    while pending:
        parts = pending.pop()
        try:
            with os.scandir(os.path.join(scan.root, *parts)) as iterator:
                for entry in iterator:
                    scan.step()
                    scan.listed += 1
                    child = (*parts, entry.name)
                    reparse = getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0) & WINDOWS_REPARSE_POINT
                    if entry.is_symlink() or reparse:
                        _link_row(scan, child, None, 'unsupported', 0)
                    elif include_subfolders and entry.is_dir(follow_symlinks=False):
                        pending.append(child)
        except PermissionError:
            if not parts:
                raise
            scan.denied += 1


def symlink_links(roots, *, check, include_subfolders):
    """Report every link inside one selected folder and where it points, without following it outside the selection.

    Returns a report with per-link states and counts. Removes nothing and never stats a target outside the roots.
    """
    if len(roots) != 1 or not roots[0][2]:
        raise ValueError('Choose a folder to inspect links')
    raw_root, root_id, _directory = roots[0]
    root = checked_path(raw_root)
    if identity(os.lstat(root))[:2] != root_id:
        raise ValueError('Selected root changed')
    scan = _LinkScan(check, root)
    try:
        if DESCRIPTOR_WALK:
            scan.root_fd = _open_listed_folder(root, root_id)
            try:
                _walk_links(scan, root_id, include_subfolders)
            finally:
                os.close(scan.root_fd)
        else:
            _list_without_descriptors(scan, include_subfolders)
    except _LimitReached:
        scan.limit_reached = True
    rows = sorted(scan.rows, key=lambda row: row['relative_path'].casefold())
    states = Counter(row['state'] for row in rows)
    return {
        'links': rows,
        'total_links': len(rows),
        'resolves_inside': states['inside'],
        'broken_or_circular': states['broken'] + states['circular'] + states['too-many-hops'],
        'outside_selection': states['out-of-scope'],
        'not_checked': states['denied'],
        'unsupported': states['unsupported'],
        'scanned_items': scan.listed,
        'denied_folders': scan.denied,
        'entry_limit': MAX_ENTRIES,
        'entry_limit_reached': scan.limit_reached,
        'complete': scan.denied == 0 and not scan.limit_reached and states['denied'] == 0,
    }


def empty_files(items, stats, *, check, dates):
    files, scanned = [], 0
    for item in items:
        check()
        scanned += 1
        if item.signature[2] == 0:
            files.append({'id': item.id, 'name': item.name, 'modified_at': dates(item)['modified_at']})
    return {
        'files': files,
        'scanned': scanned,
        'skipped_links': stats.get('skipped_links', 0),
        'denied_folders': _denied(stats),
        'complete': _denied(stats) == 0,
    }
