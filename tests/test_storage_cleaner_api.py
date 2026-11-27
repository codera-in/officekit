"""Storage routes never derive filesystem authority from client paths."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app as api


@pytest.fixture
def storage_client(monkeypatch):
    service = Mock()
    monkeypatch.setattr(api, 'storage_cleaner', service)
    with TestClient(api.app) as client:
        yield client, service


def test_storage_scan_passes_only_validated_age_and_native_credential(storage_client):
    client, service = storage_client
    service.submit.return_value = {'id': 'scan', 'state': 'queued', 'progress': 0, 'entriesScanned': 0, 'candidateCount': 0, 'candidateBytes': 0, 'report': None, 'error': None}
    response = client.post('/api/storage-scans', json={'olderThanDays': 90},
                           headers={'X-OfficeKit-Native-Grant': 'test-native'})
    assert response.status_code == 201
    assert response.headers['location'] == '/api/storage-scans/scan'
    assert response.json() == service.submit.return_value
    service.submit.assert_called_once()
    body, credential = service.submit.call_args.args
    assert body.model_dump() == {'olderThanDays': 90}
    assert credential == 'test-native'


@pytest.mark.parametrize('body', [
    {'path': '/'}, {'olderThanDays': 0}, {'olderThanDays': 3651},
    {'olderThanDays': True}, {'olderThanDays': '90'}, {'olderThanDays': 90, 'tenant_id': 'other'},
])
def test_storage_scan_rejects_paths_coercion_and_bounds(storage_client, body):
    client, service = storage_client
    assert client.post('/api/storage-scans', json=body).status_code == 422
    service.submit.assert_not_called()


def test_storage_plan_is_explicit_selection_and_execution_requires_empty_body(storage_client):
    client, service = storage_client
    service.plan.return_value = {'id': 'plan', 'expiresAt': 1000.0, 'items': [], 'estimatedBytes': 0, 'impact': 'Review selected items.'}
    response = client.post('/api/storage-cleanup-plans', json={'scanId': 'scan', 'candidateIds': ['candidate']})
    assert response.status_code == 201
    assert response.headers['location'] == '/api/storage-cleanup-plans/plan'
    service.plan.assert_called_once()
    assert service.plan.call_args.args[0].model_dump() == {'scanId': 'scan', 'candidateIds': ['candidate']}
    for body in ({'path': '/private'}, {'command': 'rm'}, [], 'execute'):
        assert client.post('/api/storage-cleanup-plans/plan/execution', json=body).status_code == 422
    service.execute.assert_not_called()
    service.execute.side_effect = PermissionError('/private/sensitive')
    response = client.post('/api/storage-cleanup-plans/plan/execution', json={})
    assert response.status_code == 403
    assert '/private/sensitive' not in response.text
    service.execute.assert_called_once_with('plan', '')


@pytest.mark.parametrize('body', [
    {'scanId': 'scan', 'candidateIds': []},
    {'scanId': 'scan', 'candidateIds': ['id'] * 201},
    {'scanId': 'scan', 'candidateIds': [4]},
    {'scanId': 'scan', 'candidateIds': ['id'], 'paths': ['/']},
])
def test_storage_plan_rejects_unbounded_or_untyped_selection(storage_client, body):
    client, service = storage_client
    assert client.post('/api/storage-cleanup-plans', json=body).status_code == 422
    service.plan.assert_not_called()


@pytest.mark.parametrize('method,url,owner,body,args', [
    ('get', '/api/storage-scans/scan', 'status', None, ('scan',)),
    ('delete', '/api/storage-scans/scan', 'cancel', None, ('scan',)),
    ('post', '/api/storage-scans', 'submit', {'olderThanDays': 90}, None),
    ('post', '/api/storage-cleanup-plans', 'plan', {'scanId': 'scan', 'candidateIds': ['id']}, None),
    ('post', '/api/storage-cleanup-plans/plan/execution', 'execute', {}, ('plan', '')),
])
@pytest.mark.parametrize('failure,status', [
    (PermissionError, 403), (FileExistsError, 409), (FileNotFoundError, 404),
    (RuntimeError, 503), (ValueError, 422), (OSError, 422),
])
def test_storage_failures_are_sanitized_and_do_not_repeat_mutations(storage_client, method, url, owner, body, args, failure, status):
    client, service = storage_client
    target = getattr(service, owner)
    target.side_effect = failure('/private/secret/path')
    response = getattr(client, method)(url, **({'json': body} if body is not None else {}))
    assert response.status_code == status
    assert '/private/secret/path' not in response.text
    if args is None:
        target.assert_called_once()
    else:
        target.assert_called_once_with(*args)


def test_storage_status_and_cancellation_are_explicit(storage_client):
    client, service = storage_client
    service.status.return_value = {'id': 'scan', 'state': 'running', 'progress': 20, 'entriesScanned': 125, 'candidateCount': 4, 'candidateBytes': 4096, 'report': None, 'error': None}
    assert client.get('/api/storage-scans/scan').json() == service.status.return_value
    service.status.assert_called_once_with('scan')
    service.cancel.return_value = {'id': 'scan', 'cancellationRequested': True}
    response = client.delete('/api/storage-scans/scan')
    assert response.status_code == 200
    assert response.json() == service.cancel.return_value
    service.cancel.assert_called_once_with('scan')
