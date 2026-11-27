import pytest

from officekit.engines.engine_file_selections import FileSelectionStore


def test_native_authority_and_direct_read(tmp_path):
    source = tmp_path / 'original.txt'
    source.write_bytes(b'original')
    store = FileSelectionStore(native_token='secret')
    with pytest.raises(PermissionError):
        store.register_native([str(source)], credential='webview')
    selection = store.register_native([str(source)], credential='secret')
    assert selection['displayNames'] == ['original.txt']
    manifest = store.manifest(selection['id'])
    assert 'path' not in manifest['files'][0]
    item = next(store.iter_files(selection['id']))
    with store.open_file(item) as stream:
        assert stream.read() == b'original'
    assert list(tmp_path.iterdir()) == [source]
    store.revoke(selection['id'])
    with pytest.raises(FileNotFoundError):
        store.manifest(selection['id'])


def test_find_file_and_derived_subset_keep_paths_out_of_metadata(tmp_path):
    first = tmp_path / 'first.pdf'
    second = tmp_path / 'second.pdf'
    first.write_bytes(b'first')
    second.write_bytes(b'second')
    store = FileSelectionStore(native_token='secret')
    parent = store.register_native([str(first), str(second)], credential='secret')
    manifest = store.manifest(parent['id'])['files']

    selected = store.find_file(parent['id'], manifest[0]['id'])
    assert selected.path == str(first)
    child = store.derive_files(parent['id'], [manifest[1]['id']])
    assert child['displayNames'] == ['second.pdf']
    assert 'path' not in child
    assert [item['name'] for item in store.manifest(child['id'])['files']] == ['second.pdf']
    with pytest.raises(ValueError):
        store.derive_files(parent['id'], [manifest[0]['id'], manifest[0]['id']])
    with pytest.raises(FileNotFoundError):
        store.find_file(parent['id'], '00000000-0000-0000-0000-000000000000')


def test_symlinks_expiry_and_changed_files(tmp_path):
    now = [0.0]
    source = tmp_path / 'original'
    source.write_bytes(b'a')
    link = tmp_path / 'link'
    link.symlink_to(source)
    store = FileSelectionStore(native_token='secret', clock=lambda: now[0])
    with pytest.raises(ValueError):
        store.register_native([str(link)], credential='secret')
    selection = store.register_native([str(source)], credential='secret')
    item = next(store.iter_files(selection['id']))
    source.write_bytes(b'changed')
    with pytest.raises(ValueError):
        with store.open_file(item):
            pass
    now[0] = 1801
    with pytest.raises(FileNotFoundError):
        store.manifest(selection['id'])


def test_open_file_refuses_a_file_changed_before_reading(tmp_path):
    # Pre-read identity check (QA-10): a file that changed after selection is refused before any byte is read.
    source = tmp_path / 'a.txt'
    source.write_bytes(b'original')
    store = FileSelectionStore(native_token='secret')
    selection = store.register_native([str(source)], credential='secret')
    item = next(store.iter_files(selection['id']))
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='^Selected file changed; select it again$'):
        with store.open_file(item):
            pass


def test_open_file_refuses_a_file_changed_during_processing(tmp_path):
    # Post-read identity check (QA-10): a rewrite while the stream is open is refused when the stream closes.
    source = tmp_path / 'a.txt'
    source.write_bytes(b'original')
    store = FileSelectionStore(native_token='secret')
    selection = store.register_native([str(source)], credential='secret')
    item = next(store.iter_files(selection['id']))
    with pytest.raises(ValueError, match='^Selected file changed during processing$'):
        with store.open_file(item) as stream:
            assert stream.read() == b'original'
            source.write_bytes(b'rewritten while processing')


def test_output_grants_are_native_scoped_consumable(tmp_path):
    store = FileSelectionStore(native_token='secret')
    target = tmp_path / 'output.zip'
    grant = store.register_output(str(target), 'file', 'archive-create', False, 'secret')
    with pytest.raises(PermissionError):
        store.consume_output(grant['id'], 'split')
    consumed = store.consume_output(grant['id'], 'archive-create')
    assert consumed.path == str(target)
    with pytest.raises(FileNotFoundError):
        store.consume_output(grant['id'], 'archive-create')


def test_selection_bounds_paging_scopes_and_pinning(tmp_path):
    import os
    from officekit.engines import engine_file_selections as module
    now = [0.0]
    store = FileSelectionStore(native_token='secret', clock=lambda: now[0])
    nested = tmp_path / 'nested'
    nested.mkdir()
    (nested / 'a').write_bytes(b'a')
    (tmp_path / 'b').write_bytes(b'b')
    (tmp_path / 'link').symlink_to(nested)
    ref = store.register_native([str(tmp_path)], credential='secret')['id']
    assert len(list(store.iter_files(ref))) == 2
    assert store.manifest(ref, limit=1)['hasMore']
    assert len(store.manifest(ref, offset=1, limit=1)['files']) == 1
    with pytest.raises(ValueError):
        store.manifest(ref, offset=-1)
    with pytest.raises(PermissionError):
        store.get(ref, write=True)
    store.pin(ref)
    now[0] = 1801
    assert store.metadata(ref)['id'] == ref
    store.unpin(ref)
    with pytest.raises(FileNotFoundError):
        store.metadata(ref)
    for paths, access in [([], 'read'), ([str(tmp_path)], 'anything'), (['relative'], 'read'), ([str(tmp_path), str(tmp_path)], 'read')]:
        with pytest.raises(ValueError):
            store.register_native(paths, access, 'secret')
    store.close()
    assert store.selections == {}


def test_root_replacement_and_during_read_changes(tmp_path):
    source = tmp_path / 'original'
    source.write_bytes(b'a')
    store = FileSelectionStore(native_token='secret')
    ref = store.register_native([str(source)], credential='secret')['id']
    item = next(store.iter_files(ref))
    with pytest.raises(ValueError):
        with store.open_file(item):
            source.write_bytes(b'changed')
    source.rename(tmp_path / 'moved')
    source.write_bytes(b'new')
    with pytest.raises(ValueError):
        list(store.iter_files(ref))


def test_output_expiry_replacement_and_invalid_kind(tmp_path):
    now = [0.0]
    store = FileSelectionStore(native_token='secret', clock=lambda: now[0])
    target = tmp_path / 'output'
    with pytest.raises(ValueError):
        store.register_output(str(target), 'bad', 'split', credential='secret')
    grant = store.register_output(str(target), 'file', 'split', credential='secret')['id']
    now[0] = 601
    with pytest.raises(FileNotFoundError):
        store.consume_output(grant, 'split')
    target.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        store.register_output(str(target), 'file', 'split', credential='secret')
    with pytest.raises(ValueError, match='never replaced'):
        store.register_output(str(target), 'file', 'split', overwrite=True, credential='secret')


def test_scan_bounds_multiple_roots_and_session_caps(tmp_path, monkeypatch):
    import os
    from officekit.engines import engine_file_selections as module
    source = tmp_path / 'a'
    source.write_bytes(b'a')
    store = FileSelectionStore(native_token='secret')
    ref = store.register_native([str(tmp_path), str(source)], credential='secret')['id']
    assert [item.name for item in store.iter_files(ref)] == ['1/a']
    monkeypatch.setattr(module, 'MAX_ENTRIES', 0)
    with pytest.raises(ValueError):
        list(store.iter_files(ref))
    single = store.register_native([str(source)], credential='secret')['id']
    with pytest.raises(ValueError):
        list(store.iter_files(single))
    monkeypatch.setattr(module, 'MAX_SESSIONS', 0)
    with pytest.raises(ValueError):
        store.register_native([str(source)], credential='secret')
    with pytest.raises(ValueError):
        store.register_output(str(tmp_path / 'new'), 'file', 'split', credential='secret')
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    with pytest.raises(ValueError):
        store.register_native([str(fifo)], credential='secret')


def test_windows_parent_fallback_and_raced_nonregular_entry(tmp_path, monkeypatch):
    from officekit.engines import engine_file_selections as module
    store = FileSelectionStore(native_token='secret')
    ref = store.register_native([str(tmp_path)], credential='secret')['id']
    monkeypatch.setattr(store, '_walk', lambda root, include_subfolders=True: iter([str(tmp_path)]))
    assert list(store.iter_files(ref)) == []
    monkeypatch.setattr(module.os, 'name', 'nt')
    with module.open_parent(str(tmp_path / 'file')) as parent:
        assert parent is None
