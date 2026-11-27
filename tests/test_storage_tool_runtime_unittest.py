"""Optional installed-tool integration: only disposable cache fixtures mutate."""
import sys
from pathlib import Path
import shutil

import pytest

from officekit.engines.engine_file_selections import identity
from officekit.engines.engine_storage_cleaner import StorageCleaner


@pytest.mark.parametrize('name', ['npm', 'pip', 'uv'])
def test_real_package_cache_cleanup_in_disposable_fixture(tmp_path, name):
    if sys.platform != 'darwin':
        pytest.skip('Native cache quarantine currently requires macOS')
    executable = shutil.which(name) or (shutil.which('pip3') if name == 'pip' else None)
    if not executable:
        pytest.skip(f'{name} is not installed')
    cache = tmp_path / name
    relative = {'npm': '_cacache/tmp/fixture', 'pip': 'wheels/sample/fixture-1.0-py3-none-any.whl', 'uv': 'wheels-v5/fixture'}[name]
    fixture = cache / relative
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b'disposable cache fixture')
    args = {'npm': ['cache', 'clean', '--force', '--cache'],
            'pip': ['cache', 'purge', '--cache-dir'], 'uv': ['cache', 'clean', '--cache-dir']}[name]
    service = StorageCleaner(home=str(tmp_path), platform='darwin')
    service._clean_tool({'id': name, 'cachePath': str(cache), 'scopeIdentity': identity(cache.stat()),
                         'command': [str(Path(executable).resolve()), *args, str(cache)]})
    assert not fixture.exists()
    assert cache.is_dir()
    assert list(tmp_path.iterdir()) == [cache]
