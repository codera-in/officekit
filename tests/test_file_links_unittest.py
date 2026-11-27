"""Engine tests for the symlink inspector (F11): synthetic temporary trees only.

Links are reported, never followed outside the selection. Nothing here touches Downloads or Trash.
"""

import contextlib
import errno
import logging
import os
import stat
from types import SimpleNamespace

import pytest

from officekit.engines import engine_file_inspect as inspect_module
from officekit.engines.engine_file_inspect import MAX_LINK_HOPS, symlink_links
from officekit.engines.engine_file_jobs import Cancelled, FileJobStore
from officekit.engines.engine_file_selections import FileSelectionStore

TOKEN = 'secret'


def deny_open(monkeypatch, name):
    """Make a no-follow open of one named folder raise PermissionError, so the denied branches run even as root."""
    real_open = os.open

    def denying_open(path, *args, **kwargs):
        if path == name and 'dir_fd' in kwargs:
            raise PermissionError(errno.EACCES, 'denied')
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, 'open', denying_open)


def deny_scandir(monkeypatch, suffix):
    """Make a path-based listing of one folder raise PermissionError (the descriptor-less walk)."""
    real_scandir = os.scandir

    def denying_scandir(path):
        if str(path).endswith(suffix):
            raise PermissionError(errno.EACCES, 'denied')
        return real_scandir(path)

    monkeypatch.setattr(os, 'scandir', denying_scandir)


@pytest.fixture
def stores():
    selections = FileSelectionStore(native_token=TOKEN)
    jobs = FileJobStore(selections, release_profile='development')
    yield selections, jobs
    jobs.close()
    selections.close()


def inspect(selections, root, include_subfolders=True, check=lambda: None):
    ref = selections.register_native([str(root)], credential=TOKEN)['id']
    return symlink_links(selections.get(ref).roots, check=check, include_subfolders=include_subfolders)


def by_path(result):
    return {row['relative_path']: row for row in result['links']}


def test_relative_and_absolute_links_inside_the_folder_resolve(stores, tmp_path):
    selections, _jobs = stores
    root = tmp_path / 'project'
    (root / 'src' / 'releases' / 'v2').mkdir(parents=True)
    (root / 'src' / 'current').symlink_to('releases/v2')
    (root / 'src' / 'absolute').symlink_to(root / 'src' / 'releases')
    result = inspect(selections, root)
    rows = by_path(result)
    assert rows['src/current'] == {'name': 'current', 'relative_path': 'src/current', 'points_to': 'releases/v2',
                                   'type': 'relative', 'state': 'inside', 'hops': 1}
    assert rows['src/absolute']['type'] == 'absolute'
    assert rows['src/absolute']['points_to'] == str(root / 'src' / 'releases')
    assert rows['src/absolute']['state'] == 'inside'
    assert result['total_links'] == 2
    assert result['resolves_inside'] == 2
    assert result['complete'] is True


def test_a_link_whose_target_is_missing_is_broken(stores, tmp_path):
    selections, _jobs = stores
    (tmp_path / 'old').symlink_to('archive/missing')
    rows = by_path(inspect(selections, tmp_path))
    assert rows['old']['state'] == 'broken'
    assert rows['old']['points_to'] == 'archive/missing'


def test_a_path_through_a_regular_file_is_broken(stores, tmp_path):
    selections, _jobs = stores
    (tmp_path / 'file.txt').write_text('x')
    (tmp_path / 'deep').symlink_to('file.txt/inside')
    rows = by_path(inspect(selections, tmp_path))
    assert rows['deep']['state'] == 'broken'


def test_an_intermediate_link_is_followed_inside_the_folder(stores, tmp_path):
    selections, _jobs = stores
    (tmp_path / 'real').mkdir()
    (tmp_path / 'real' / 'file.txt').write_text('x')
    (tmp_path / 'alias').symlink_to('real')
    (tmp_path / 'via').symlink_to('alias/file.txt')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'up').symlink_to('../real/file.txt')
    rows = by_path(inspect(selections, tmp_path))
    assert rows['via']['state'] == 'inside' and rows['via']['hops'] == 2
    assert rows['sub/up']['state'] == 'inside' and rows['sub/up']['hops'] == 1


def test_a_two_hop_cycle_is_circular_and_a_self_loop_is_one_hop(stores, tmp_path):
    selections, _jobs = stores
    (tmp_path / 'loop-a').symlink_to('loop-b')
    (tmp_path / 'loop-b').symlink_to('loop-a')
    (tmp_path / 'self').symlink_to('self')
    rows = by_path(inspect(selections, tmp_path))
    assert rows['loop-a']['state'] == 'circular' and rows['loop-a']['hops'] == 2
    assert rows['loop-b']['state'] == 'circular' and rows['loop-b']['hops'] == 2
    assert rows['self']['state'] == 'circular' and rows['self']['hops'] == 1


def test_an_absolute_link_to_the_selected_folder_itself_resolves(stores, tmp_path):
    selections, _jobs = stores
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'home').symlink_to(root)
    row = by_path(inspect(selections, root))['home']
    assert row['state'] == 'inside' and row['type'] == 'absolute' and row['hops'] == 1


def test_a_chain_of_forty_links_resolves_and_forty_one_is_too_many(stores, tmp_path):
    selections, _jobs = stores
    (tmp_path / 'target.txt').write_text('x')
    total = MAX_LINK_HOPS + 1
    for index in range(total):
        next_name = f'c{index + 1:02d}' if index + 1 < total else 'target.txt'
        (tmp_path / f'c{index:02d}').symlink_to(next_name)
    rows = by_path(inspect(selections, tmp_path))
    # c00 needs 41 links to reach the file, so it is refused; c01 needs 40 and resolves.
    assert rows['c00']['state'] == 'too-many-hops'
    assert rows['c01']['state'] == 'inside' and rows['c01']['hops'] == MAX_LINK_HOPS


def test_out_of_scope_targets_are_never_stat_or_opened(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    outside = tmp_path / 'outside-sentinel'
    outside.mkdir()
    (outside / 'secret.txt').write_text('x')
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'absolute').symlink_to(outside / 'secret.txt')
    (root / 'escape').symlink_to('../outside-sentinel/secret.txt')
    (root / 'nested').mkdir()
    (root / 'nested' / 'hop').symlink_to('../../outside-sentinel')
    (root / 'chain-a').symlink_to('chain-b')
    (root / 'chain-b').symlink_to('../outside-sentinel/secret.txt')
    touched = []

    def recorder(real):
        def spy(*args, **kwargs):
            # The path argument, positional or keyword, so a call relative to a held descriptor is still seen.
            touched.append(args[0] if args else kwargs.get('path', kwargs.get('name')))
            return real(*args, **kwargs)
        return spy

    for name in ('lstat', 'stat', 'open', 'scandir'):
        monkeypatch.setattr(os, name, recorder(getattr(os, name)))
    result = inspect(selections, root)
    rows = by_path(result)
    assert {row['state'] for row in rows.values()} == {'out-of-scope'}
    assert rows['chain-a']['hops'] == 2
    assert result['outside_selection'] == 5
    assert not [name for name in touched if isinstance(name, str) and 'outside-sentinel' in name]
    # No call names the parent of a folder, so the parent of the selected root is never stat'ed or opened.
    assert '..' not in touched


def test_a_denied_subfolder_makes_the_result_partial(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    (tmp_path / 'open').mkdir()
    (tmp_path / 'open' / 'ok-link').symlink_to('.')
    (tmp_path / 'locked').mkdir()
    (tmp_path / 'locked' / 'hidden-link').symlink_to('.')
    deny_open(monkeypatch, 'locked')
    result = inspect(selections, tmp_path)
    assert result['denied_folders'] == 1
    assert result['complete'] is False
    assert [row['relative_path'] for row in result['links']] == ['open/ok-link']


def test_a_target_that_cannot_be_read_inside_the_folder_is_not_checked(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    (tmp_path / 'locked').mkdir()
    (tmp_path / 'locked' / 'x.txt').write_text('x')
    (tmp_path / 'peek').symlink_to('locked/x.txt')
    deny_open(monkeypatch, 'locked')
    result = inspect(selections, tmp_path, include_subfolders=False)
    assert by_path(result)['peek']['state'] == 'denied'
    assert result['not_checked'] == 1
    assert result['complete'] is False


def test_subfolders_are_skipped_when_not_included(stores, tmp_path):
    selections, _jobs = stores
    (tmp_path / 'top').symlink_to('.')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'deep').symlink_to('.')
    result = inspect(selections, tmp_path, include_subfolders=False)
    assert [row['relative_path'] for row in result['links']] == ['top']
    assert result['scanned_items'] == 2


def test_an_empty_folder_reports_no_links_and_its_item_count(stores, tmp_path):
    selections, _jobs = stores
    (tmp_path / 'a.txt').write_text('x')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'b.txt').write_text('y')
    result = inspect(selections, tmp_path)
    assert result['links'] == [] and result['total_links'] == 0
    assert result['scanned_items'] == 3
    assert result['complete'] is True


def test_the_entry_cap_returns_a_partial_result(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    for index in range(5):
        (tmp_path / f'l{index}').symlink_to('nothing')
    monkeypatch.setattr(inspect_module, 'MAX_ENTRIES', 3)
    result = inspect(selections, tmp_path)
    assert result['entry_limit_reached'] is True
    assert result['entry_limit'] == 3
    assert result['complete'] is False
    assert len(result['links']) < 5


def test_resolution_steps_do_not_count_against_the_entry_cap(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    (tmp_path / 'a' / 'b' / 'c').mkdir(parents=True)
    (tmp_path / 'a' / 'b' / 'c' / 'file.txt').write_text('x')
    (tmp_path / 'deep').symlink_to('a/b/c/file.txt')
    monkeypatch.setattr(inspect_module, 'MAX_ENTRIES', 4)
    result = inspect(selections, tmp_path, include_subfolders=False)
    # Two listed entries fit under a cap of four; the five resolution steps for 'deep' do not count against it.
    assert result['entry_limit_reached'] is False
    assert by_path(result)['deep']['state'] == 'inside'


def test_relative_and_absolute_parent_hops_cross_an_in_root_link(stores, tmp_path):
    selections, _jobs = stores
    root = tmp_path / 'root'
    (root / 'real').mkdir(parents=True)
    (root / 'real' / 'file.txt').write_text('x')
    (root / 'alias').symlink_to('real')
    (root / 'relative-cross').symlink_to('alias/../real/file.txt')
    (root / 'absolute-cross').symlink_to(root / 'alias' / '..' / 'real' / 'file.txt')
    (root / 'relative-escape').symlink_to('alias/../../outside.txt')
    (root / 'absolute-escape').symlink_to(root / 'alias' / '..' / '..' / 'outside.txt')
    rows = by_path(inspect(selections, root))
    assert rows['relative-cross']['state'] == 'inside' and rows['relative-cross']['hops'] == 2
    assert rows['absolute-cross']['state'] == 'inside' and rows['absolute-cross']['hops'] == 2
    assert rows['relative-escape']['state'] == 'out-of-scope'
    assert rows['absolute-escape']['state'] == 'out-of-scope'


def test_a_listed_subfolder_swapped_for_an_outside_link_fails_closed(stores, tmp_path):
    # For a directory this small, scandir reads the whole batch before the check callback swaps the folder, so the
    # stale d_type still says directory in either order and the no-follow open then meets the link: FileExistsError.
    selections, _jobs = stores
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'leak').symlink_to('nothing')
    root = tmp_path / 'root'
    (root / 'sub').mkdir(parents=True)
    (root / 'plain.txt').write_text('y')
    swapped = []

    def swap_the_subfolder_during_the_listing():
        if not swapped:
            swapped.append(True)
            (root / 'sub').rmdir()
            (root / 'sub').symlink_to(outside)

    with pytest.raises(FileExistsError, match='Folder changed during scan'):
        inspect(selections, root, check=swap_the_subfolder_during_the_listing)
    assert swapped == [True]


@pytest.mark.parametrize(('code', 'outcome'), [(errno.ENOTDIR, 'broken'), (errno.ELOOP, 'fails-closed')])
def test_a_hop_whose_folder_fails_to_open_is_broken_or_fails_closed(stores, tmp_path, monkeypatch, code, outcome):
    selections, _jobs = stores
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'x').write_text('x')
    (tmp_path / 'a').symlink_to('sub/x')
    real_open = os.open

    def failing_open(path, *args, **kwargs):
        if path == 'sub' and 'dir_fd' in kwargs:
            raise OSError(code, os.strerror(code))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, 'open', failing_open)
    if outcome == 'fails-closed':
        with pytest.raises(FileExistsError, match='Folder changed during scan'):
            inspect(selections, tmp_path, include_subfolders=False)
    else:
        assert by_path(inspect(selections, tmp_path, include_subfolders=False))['a']['state'] == 'broken'


def test_cancellation_is_checked_at_every_entry_and_hop(stores, tmp_path):
    selections, _jobs = stores
    (tmp_path / 'chain').symlink_to('chain')
    calls = []

    def cancel_on_the_first_hop():
        calls.append(1)
        if len(calls) > 1:
            raise Cancelled()

    # One check for the listed entry, then the first hop of the link stops the scan.
    with pytest.raises(Cancelled):
        inspect(selections, tmp_path, check=cancel_on_the_first_hop)
    assert len(calls) == 2


def test_link_text_is_never_logged(stores, tmp_path, caplog):
    selections, _jobs = stores
    sentinel = 'sentinel-target-7f3'
    (tmp_path / 'probe').symlink_to(sentinel)
    with caplog.at_level(logging.DEBUG):
        result = inspect(selections, tmp_path)
    assert by_path(result)['probe']['points_to'] == sentinel
    assert sentinel not in caplog.text


def test_links_are_unsupported_where_descriptor_walks_are_unavailable(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    (tmp_path / 'plain.txt').write_text('x')
    (tmp_path / 'link').symlink_to('plain.txt')
    monkeypatch.setattr(inspect_module, 'DESCRIPTOR_WALK', False)
    result = inspect(selections, tmp_path)
    assert result['links'] == [{'name': 'link', 'relative_path': 'link', 'points_to': None, 'type': None,
                                'state': 'unsupported', 'hops': 0}]
    assert result['unsupported'] == 1 and result['scanned_items'] == 2


def test_an_unreadable_root_fails_the_scan(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    root = tmp_path / 'locked-root'
    root.mkdir()
    ref = selections.register_native([str(root)], credential=TOKEN)['id']
    deny_open(monkeypatch, 'locked-root')
    with pytest.raises(PermissionError):
        symlink_links(selections.get(ref).roots, check=lambda: None, include_subfolders=True)


def test_the_unsupported_walk_recurses_and_counts_a_denied_subfolder(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    (tmp_path / 'deep').mkdir()
    (tmp_path / 'deep' / 'nested-link').symlink_to('.')
    (tmp_path / 'locked').mkdir()
    (tmp_path / 'locked' / 'hidden-link').symlink_to('.')
    monkeypatch.setattr(inspect_module, 'DESCRIPTOR_WALK', False)
    deny_scandir(monkeypatch, 'locked')
    result = inspect(selections, tmp_path)
    assert [row['relative_path'] for row in result['links']] == ['deep/nested-link']
    assert result['denied_folders'] == 1 and result['complete'] is False


def test_the_unsupported_walk_refuses_an_unreadable_root(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    root = tmp_path / 'locked-root'
    root.mkdir()
    ref = selections.register_native([str(root)], credential=TOKEN)['id']
    monkeypatch.setattr(inspect_module, 'DESCRIPTOR_WALK', False)
    deny_scandir(monkeypatch, 'locked-root')
    with pytest.raises(PermissionError):
        symlink_links(selections.get(ref).roots, check=lambda: None, include_subfolders=True)


def test_a_windows_reparse_point_is_unsupported_even_when_it_is_not_a_symlink(stores, tmp_path, monkeypatch):
    selections, _jobs = stores

    class Junction:
        name = 'junction'

        def is_symlink(self):
            return False

        def is_dir(self, follow_symlinks=True):
            return False

        def stat(self, follow_symlinks=True):
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=inspect_module.WINDOWS_REPARSE_POINT)

    monkeypatch.setattr(inspect_module, 'DESCRIPTOR_WALK', False)
    monkeypatch.setattr(os, 'scandir', lambda _path: contextlib.nullcontext(iter([Junction()])))
    result = inspect(selections, tmp_path, include_subfolders=False)
    assert result['links'] == [{'name': 'junction', 'relative_path': 'junction', 'points_to': None, 'type': None,
                                'state': 'unsupported', 'hops': 0}]
    assert result['unsupported'] == 1


def test_unexpected_filesystem_errors_are_not_reported_as_links(stores, tmp_path, monkeypatch):
    selections, _jobs = stores
    (tmp_path / 'probe').symlink_to('nothing')
    real_stat = os.stat

    def failing_stat(path, *args, **kwargs):
        if 'dir_fd' in kwargs:
            raise OSError(errno.EIO, 'disk failure')
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, 'stat', failing_stat)
    with pytest.raises(OSError, match='disk failure'):
        inspect(selections, tmp_path)


def test_a_file_root_is_refused_with_the_fixed_message(stores, tmp_path):
    selections, _jobs = stores
    single = tmp_path / 'single.txt'
    single.write_text('x')
    ref = selections.register_native([str(single)], credential=TOKEN)['id']
    with pytest.raises(ValueError, match='Choose a folder to inspect links'):
        symlink_links(selections.get(ref).roots, check=lambda: None, include_subfolders=False)


def test_a_replaced_root_is_refused(stores, tmp_path):
    selections, _jobs = stores
    root = tmp_path / 'root'
    root.mkdir()
    ref = selections.register_native([str(root)], credential=TOKEN)['id']
    # Keep the granted folder alive under another name so the replacement cannot reuse its inode.
    root.rename(tmp_path / 'moved')
    root.mkdir()
    with pytest.raises(ValueError, match='Selected root changed'):
        symlink_links(selections.get(ref).roots, check=lambda: None, include_subfolders=True)
