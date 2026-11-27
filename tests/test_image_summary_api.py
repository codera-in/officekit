import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app as api
from officekit.engines.engine_file_jobs import FileJobStore
from officekit.engines.engine_file_selections import FileSelectionStore


@pytest.fixture
def client_and_selections(monkeypatch):
    selections = FileSelectionStore(native_token='native-test')
    jobs = FileJobStore(selections, release_profile='development')
    monkeypatch.setattr(api, 'file_selection_store', selections)
    monkeypatch.setattr(api, 'file_job_store', jobs)
    with TestClient(api.app) as client:
        yield client, selections, jobs
    jobs.close()
    selections.close()


def test_image_summary_counts_images_per_folder_and_reports_the_limit(client_and_selections, tmp_path):
    client, selections, _jobs = client_and_selections
    first, second = tmp_path / 'Pictures', tmp_path / 'Archive'
    (first / 'trip').mkdir(parents=True)
    second.mkdir()
    for path in (first / 'a.jpg', first / 'trip' / 'b.PNG', second / 'c.heic'):
        path.write_bytes(b'x')
    (first / 'notes.txt').write_bytes(b'x')
    (second / 'movie.mov').write_bytes(b'x')
    selection = selections.register_native([str(first), str(second)], credential='native-test')
    body = client.get(f"/api/file-selections/{selection['id']}/image-summary").json()
    assert body == {
        'folders': [{'name': 'Pictures', 'images': 2}, {'name': 'Archive', 'images': 1}],
        'images': 3, 'skipped': 2, 'limit': 10_000,
    }


def test_image_summary_for_unknown_selection_is_404(client_and_selections):
    client, _selections, _jobs = client_and_selections
    assert client.get('/api/file-selections/missing/image-summary').status_code == 404


def test_similar_images_job_reports_progress_total_and_uses_capture_times(client_and_selections, tmp_path):
    from tests.test_file_jobs_unittest import await_job

    client, selections, jobs = client_and_selections
    folder = tmp_path / 'photos'
    folder.mkdir()
    for name in ('one.png', 'two.png'):
        Image.new('RGB', (64, 64), 'blue').save(folder / name)
    selection = selections.register_native([str(folder)], credential='native-test')
    job = jobs.submit({'kind': 'similar-images', 'selectionIds': [selection['id']], 'options': {'threshold': 8}})
    done = await_job(jobs, job['id'])
    assert done['state'] == 'ready'
    assert done['total'] == 2 and done['progress'] == 2
    assert jobs.result(job['id'])['groups'] == [{'files': ['one.png', 'two.png']}]
