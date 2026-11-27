"""Private PDF lifecycle, immutable snapshots and native authority regressions."""
import io
import pytest
from unittest.mock import Mock, patch
import threading
from concurrent.futures import Future

from officekit.engines.engine_pdf_workspace import PdfWorkspace, PdfWorkspaceError


class Editor:
    def inspect_document(self, content):
        return {'page_count': 1, 'pages': [{'page': 1, 'width': 100.0, 'height': 200.0, 'rotation': 0, 'crop_box': [0, 0, 100, 200]}]}

    def render_page(self, content, page, scale=1):
        return b'png'

    def list_objects(self, content, page, revision=0, offset=0, limit=100):
        return {'revision': revision, 'page': page, 'objects': []}

    def apply_operations(self, content, operations, revision=0):
        return content + b' edited'

    def recognize_regions(self, content, pages, language='eng'):
        return [{'id': 'region', 'page': 1, 'rect': [1, 1, 11, 11], 'text': 'scan'}]


class Signing:
    signed = False

    def inspect_signatures(self, content):
        return {'signatures': [{'field': 'signature'}] if self.signed else [], 'content_editing_allowed': not self.signed, 'signing_allowed': True}

    def certificate_summary(self, content, password):
        assert password == 'secret'
        return {'fingerprint': 'cert', 'subject': 'Test'}

    def sign_pkcs12(self, content, certificate, secret, **kwargs):
        assert secret == 'secret'
        return content + b' signed'

    def verify_pdf(self, content):
        return [{'integrity': 'valid', 'trust': 'unknown'}]


@pytest.fixture
def workspace():
    store = PdfWorkspace(editor=Editor(), signing=Signing(), isolated=False)
    yield store
    store.close()


def test_immutable_revisions_exports_delete_and_expiry(workspace):
    doc = workspace.create(b'%PDF-test', 'original.pdf')
    assert doc['revision'] == 0
    first = workspace.revise(doc['id'], 0, [{'kind': 'add_text'}])
    assert first['revision'] == 1
    with pytest.raises(PdfWorkspaceError, match='changed'):
        workspace.revise(doc['id'], 0, [])
    assert workspace.content(doc['id'], 0) == b'%PDF-test'
    assert workspace.content(doc['id'], 1) == b'%PDF-test edited'
    exported = workspace.export(doc['id'], 1)
    assert workspace.artifact(exported['result_ref'])[0] == b'%PDF-test edited'
    assert workspace.preview(doc['id'], 1, 1, 1)[0] == b'png'
    assert workspace.objects(doc['id'], 1, 1)['objects'] == []
    workspace.delete(doc['id'])
    with pytest.raises(PdfWorkspaceError):
        workspace.artifact(exported['result_ref'])
    with pytest.raises(PdfWorkspaceError):
        workspace.get(doc['id'])
    clock = [0]
    workspace.clock = lambda: clock[0]
    doc = workspace.create(b'%PDF-expire', 'a.pdf')
    clock[0] = 1801
    with pytest.raises(PdfWorkspaceError):
        workspace.get(doc['id'])


def test_undo_restores_authoritative_head_without_accepting_stale_edits(workspace):
    doc = workspace.create(b'%PDF-original', 'a.pdf')
    workspace.revise(doc['id'], 0, [{'kind': 'add_text'}])
    restored = workspace.restore(doc['id'], 1, 0)
    assert restored['revision'] == 2
    assert workspace.content(doc['id'], 2) == b'%PDF-original'
    with pytest.raises(PdfWorkspaceError, match='changed'):
        workspace.restore(doc['id'], 1, 0)
    with pytest.raises(PdfWorkspaceError):
        workspace.restore(doc['id'], 2, 999)
    changed = workspace.revise(doc['id'], 2, [{'kind': 'add_text'}])
    assert changed['revision'] == 3
    assert workspace.content(doc['id'], 3) == b'%PDF-original edited'
    workspace.documents[doc['id']]['busy'] = True
    with pytest.raises(PdfWorkspaceError):
        workspace.restore(doc['id'], 3, 0)
    workspace.documents[doc['id']]['busy'] = False
    workspace.documents[doc['id']]['signatures']['signatures'] = [{'field': 's'}]
    with pytest.raises(PdfWorkspaceError):
        workspace.restore(doc['id'], 3, 0)
    workspace.documents[doc['id']]['signatures']['signatures'] = []
    workspace.documents[doc['id']]['revisions'].update({i: b'%PDF' for i in range(32)})
    with pytest.raises(PdfWorkspaceError):
        workspace.restore(doc['id'], 3, 0)


def test_signed_document_content_editing_is_blocked(workspace):
    workspace.signing.signed = True
    doc = workspace.create(b'%PDF-signed', 'signed.pdf')
    assert not doc['permissions']['can_edit']
    with pytest.raises(PdfWorkspaceError, match='signed'):
        workspace.revise(doc['id'], 0, [])


def test_input_and_aggregate_caps(workspace):
    for content in (b'', b'not pdf'):
        with pytest.raises(PdfWorkspaceError):
            workspace.create(content, 'bad.pdf')
    workspace.MAX_BYTES = 10
    with pytest.raises(PdfWorkspaceError):
        workspace.create(b'%PDF-' + b'x' * 10, 'big.pdf')
    workspace.MAX_TOTAL_BYTES = 12
    workspace.create(b'%PDF-one', 'a.pdf')
    with pytest.raises(PdfWorkspaceError):
        workspace.create(b'%PDF-two', 'b.pdf')


def test_jobs_signing_and_secret_exclusion(workspace):
    doc = workspace.create(b'%PDF-test', 'a.pdf')
    provider = workspace.provider_file(b'certificate', 'secret')
    job = workspace.sign(doc['id'], 0, provider['id'], 'cert', 'secret')
    workspace.wait(job['id'])
    result = workspace.job(job['id'])
    assert result['state'] == 'ready'
    assert b'signed' in workspace.artifact(result['result_ref'])[0]
    assert 'secret' not in str(result)
    verification = workspace.verify(doc['id'], 0)
    workspace.wait(verification['id'])
    assert workspace.job(verification['id'])['result'] == [{'integrity': 'valid', 'trust': 'unknown'}]


def test_ocr_is_revision_bound(workspace):
    doc = workspace.create(b'%PDF-test', 'a.pdf')
    job = workspace.ocr(doc['id'], 0, [1], 'eng', 'editable')
    workspace.wait(job['id'])
    result = workspace.job(job['id'])['result']
    assert result['regions'][0]['text'] == 'scan'
    assert workspace.ocr_review(doc['id'], result['review_id'])['base_revision'] == 0


def test_cancel_ready_job_is_conflict(workspace):
    doc = workspace.create(b'%PDF-test', 'a.pdf')
    job = workspace.verify(doc['id'], 0)
    workspace.wait(job['id'])
    with pytest.raises(PdfWorkspaceError):
        workspace.cancel(job['id'])


def test_revisions_permissions_and_region_binding(workspace):
    doc = workspace.create(b'%PDF-test', 'a.pdf')
    key = doc['id']
    for method in (workspace.get, workspace.content):
        with pytest.raises(PdfWorkspaceError, match='revision'):
            method(key, 99)
    with pytest.raises(PdfWorkspaceError, match='page'):
        workspace.preview(key, 9, 0, 1)
    with patch.object(workspace.editor, 'render_page', return_value=b'x' * (16 * 1024 * 1024 + 1)):
        with pytest.raises(PdfWorkspaceError, match='preview'):
            workspace.preview(key, 1, 0, 1)
    workspace.documents[key]['revisions'].update({n: b'pdf' for n in range(1,32)})
    with pytest.raises(PdfWorkspaceError, match='Revision limit'):
        workspace.revise(key, 0, [])
    workspace.documents[key]['revisions'] = {0: b'%PDF-test'}
    job = workspace.ocr(key, 0, [1], 'eng', 'searchable')
    workspace.wait(job['id'])
    review = workspace.job(job['id'])['result']
    op = {'kind': 'apply_ocr', 'review_id': review['review_id'], 'region_id': 'region',
          'page': 1, 'rect': [1,1,11,11], 'ocr_mode': 'searchable', 'text': 'corrected'}
    for changed in ({'ocr_mode': 'reconstruction'}, {'region_id': 'forged'}, {'rect': [0,0,10,10]}, {'page': 2}):
        with pytest.raises(PdfWorkspaceError):
            workspace.revise(key, 0, [{**op, **changed}])
    with patch.object(workspace.editor, 'apply_operations', wraps=workspace.editor.apply_operations) as apply:
        assert workspace.revise(key, 0, [op])['revision'] == 1
        apply.assert_called_once_with(b'%PDF-test', [op], revision=0)
    with pytest.raises(PdfWorkspaceError, match='earlier'):
        workspace.revise(key, 1, [op])
    with pytest.raises(PdfWorkspaceError, match='review'):
        workspace.ocr_review(key, 'unknown')
    for method in (workspace.verify, lambda k, r: workspace.ocr(k, r, [1], 'eng', 'searchable')):
        with pytest.raises(PdfWorkspaceError, match='changed'):
            method(key, 0)


def test_caps_providers_and_native_authority(workspace):
    workspace.MAX_SESSIONS = 1
    doc = workspace.create(b'%PDF-test', 'a.pdf')
    with pytest.raises(PdfWorkspaceError, match='Close a PDF'):
        workspace.create(b'%PDF-test', 'b.pdf')
    provider = workspace.provider_file(b'certificate', 'secret')
    assert provider['certificates'][0]['id'] == 'cert'
    with pytest.raises(PdfWorkspaceError, match='provider'):
        workspace.sign(doc['id'], 0, 'missing', 'cert', 'secret')
    with pytest.raises(PdfWorkspaceError, match='certificate'):
        workspace.sign(doc['id'], 0, provider['id'], 'bad', 'secret')
    for placement in ({'page': 2}, {'page': 1, 'x': 90, 'y': 0, 'width': 30, 'height': 10},
                      {'page': 1, 'x': float('nan'), 'y': 0, 'width': 1, 'height': 1}):
        with pytest.raises(PdfWorkspaceError):
            workspace.sign(doc['id'], 0, provider['id'], 'cert', 'secret', placement)
    with pytest.raises(PdfWorkspaceError, match='native file picker'):
        workspace.provider_native('/untrusted', None)
    check = Mock()
    with patch.object(workspace.signing, 'enumerate_token_certificates', create=True,
                      return_value=[{'id':'native','fingerprint':'native'}]) as enumerate:
        native = workspace.provider_native('/native-granted', check)
        assert check.call_count == 2
        enumerate.assert_called_once_with('/native-granted')
    with patch.object(workspace.signing, 'sign_pkcs11', create=True, return_value=b'%PDF-signed') as sign:
        job = workspace.sign(doc['id'], 0, native['id'], 'native', '1234',
                             {'page':1, 'x':1, 'y':1, 'width':10, 'height':10})
        workspace.wait(job['id'])
        assert workspace.job(job['id'])['state'] == 'ready'
        sign.assert_called_once_with(b'%PDF-test', '/native-granted', 'native', '1234', reason=None,
                                     page=0, box=(1,1,11,11))
        assert check.call_count == 4
    workspace.providers.update({str(n): {'data': b'', 'certificates': [], 'expires': float('inf')} for n in range(8)})
    with pytest.raises(PdfWorkspaceError, match='limit'):
        workspace.provider_file(b'certificate', 'secret')
    with pytest.raises(PdfWorkspaceError, match='limit'):
        workspace.provider_native('/native', check)


def test_async_failure_and_signature_integrity(workspace):
    from officekit.engines.engine_pdf_signing import PdfSigningError
    doc = workspace.create(b'%PDF-test', 'a.pdf')
    provider = workspace.provider_file(b'certificate', 'secret')
    with patch.object(workspace.signing, 'verify_pdf', return_value=[{'integrity':'invalid'}]):
        job = workspace.sign(doc['id'], 0, provider['id'], 'cert', 'secret')
        workspace.wait(job['id'])
        assert workspace.job(job['id'])['error_code'] == 'verification_failed'
        assert workspace.job(job['id'])['result_ref'] is None
    with patch.object(workspace.signing, 'verify_pdf', side_effect=PdfSigningError('wrong_password','Certificate could not be unlocked.')):
        job = workspace.verify(doc['id'], 0)
        workspace.wait(job['id'])
        assert workspace.job(job['id'])['error_code'] == 'wrong_password'
    with pytest.raises(PdfWorkspaceError, match='job'):
        workspace.job('missing')
    workspace.documents[doc['id']]['signatures']['signing_allowed'] = False
    assert not workspace.get(doc['id'])['permissions']['can_sign']
    with pytest.raises(PdfWorkspaceError, match='cannot be signed'):
        workspace.sign(doc['id'], 0, provider['id'], 'cert', 'secret')


def test_cancellation_queued_running_and_busy_guards(workspace):
    doc = workspace.create(b'%PDF-test', 'a.pdf')
    # Hold the executor queue deterministically without timing-based sleeps.
    entered, release = threading.Event(), threading.Event()
    def blocker():
        entered.set()
        assert release.wait(5)
    blocking = workspace.executor.submit(blocker)
    assert entered.wait(5)
    job = workspace.verify(doc['id'], 0)
    assert workspace.cancel(job['id'])['state'] == 'cancellation_requested'
    with pytest.raises(PdfWorkspaceError, match='before closing'):
        workspace.delete(doc['id'])
    with pytest.raises(PdfWorkspaceError, match='busy'):
        workspace.verify(doc['id'], 0)
    release.set()
    blocking.result(5)
    workspace.wait(job['id'])
    assert workspace.job(job['id'])['state'] == 'cancelled'
    entered.clear()
    release.clear()
    def recognition(*args, **kwargs):
        blocker()
        return []
    with patch.object(workspace.editor, 'recognize_regions', side_effect=recognition):
        job = workspace.ocr(doc['id'], 0, [1], 'eng', 'searchable')
        assert entered.wait(5)
        workspace.cancel(job['id'])
        release.set()
        workspace.wait(job['id'])
        assert workspace.job(job['id'])['state'] == 'cancelled'
        assert workspace.reviews == {}


def test_source_identity_rechecked_before_publish(workspace):
    check = Mock()
    doc = workspace.create(b'%PDF-test', 'a.pdf', source_check=check)
    def changed_source(content, operations, revision=0):
        check.side_effect = RuntimeError('private path')
        return b'%PDF-edited'
    with patch.object(workspace.editor, 'apply_operations', side_effect=changed_source):
        with pytest.raises(PdfWorkspaceError, match='Source PDF changed'):
            workspace.revise(doc['id'], 0, [])
    assert workspace.documents[doc['id']]['revision'] == 0


def test_engine_error_sanitization(workspace):
    from officekit.engines.engine_pdf_editor import PdfEditorError
    from officekit.engines.engine_pdf_signing import PdfSigningError
    for error, status in ((PdfEditorError('OCR unavailable',503),503),
                          (PdfSigningError('online_unavailable','Online verification is unavailable.'),503),
                          (RuntimeError('private secret'),500)):
        with patch.object(workspace.editor, 'inspect_document', side_effect=error):
            with pytest.raises(PdfWorkspaceError) as actual:
                workspace.create(b'%PDF-test', 'a.pdf')
            assert actual.value.status == status
            assert 'private' not in str(actual.value)


def test_dispatch_isolation_and_disposal():
    from officekit.engines import engine_pdf_workspace as module
    store = PdfWorkspace(isolated=False)
    try:
        with patch.object(module, '_call_engine', return_value={'safe':True}) as call:
            assert store._call('editor','inspect_document', b'pdf') == {'safe':True}
            call.assert_called_once_with('editor','inspect_document',(b'pdf',),{})
        process = Mock()
        process.submit.return_value.result.return_value = 'ok'
        store.process = process
        assert store._call('signing','inspect_signatures',b'pdf') == 'ok'
        process.submit.assert_called_once_with(module._call_engine,'signing','inspect_signatures',(b'pdf',),{})
        process.submit.return_value.result.assert_called_once_with(timeout=120)
    finally:
        store.close()
    process.shutdown.assert_called_once_with(wait=True,cancel_futures=True)
    with patch('officekit.engines.engine_pdf_editor.inspect_document',return_value='editor'):
        assert module._call_engine('editor','inspect_document',(b'pdf',),{}) == 'editor'
    with patch('officekit.engines.engine_pdf_signing.inspect_signatures',return_value='signing'):
        assert module._call_engine('signing','inspect_signatures',(b'pdf',),{}) == 'signing'


def test_job_unexpected_failure_budgets_and_protected_ocr(workspace):
    doc = workspace.create(b'%PDF-test','a.pdf')
    def unexpected():
        raise RuntimeError('SECRET')
    job = workspace._submit(doc['id'],'test',unexpected)
    workspace.wait(job['id'])
    assert workspace.job(job['id'])['error'] == 'The PDF operation failed.'
    assert 'SECRET' not in str(workspace.job(job['id']))
    workspace.reviews = {str(n): {'document':doc['id']} for n in range(8)}
    job = workspace.ocr(doc['id'],0,[1],'eng','searchable')
    workspace.wait(job['id'])
    assert workspace.job(job['id'])['state'] == 'failed'
    assert workspace.job(job['id'])['error'] == 'OCR review limit reached.'
    workspace.documents[doc['id']]['signatures']['signatures'] = [{'field':'signed'}]
    with pytest.raises(PdfWorkspaceError,match='protected'):
        workspace.ocr(doc['id'],0,[1],'eng','searchable')


def test_ocr_text_and_provider_metadata_count_toward_budget(workspace):
    doc = workspace.create(b'%PDF-test','a.pdf')
    workspace.MAX_TOTAL_BYTES = 100
    job = workspace.ocr(doc['id'],0,[1],'eng','searchable')
    workspace.wait(job['id'])
    assert workspace.job(job['id'])['state'] == 'failed'
    assert workspace.reviews == {}
    assert len(workspace.jobs) == 1
    workspace.jobs.clear()
    with patch.object(workspace.signing,'certificate_summary',return_value={'fingerprint':'cert','subject':'x'*100}):
        with pytest.raises(PdfWorkspaceError,match='memory limit'):
            workspace.provider_file(b'cert','secret')


def test_real_disposable_process_pdf_and_public_error():
    from reportlab.pdfgen.canvas import Canvas
    output = io.BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72,720,'Isolated signing boundary')
    canvas.save()
    store = PdfWorkspace()
    try:
        document = store.create(output.getvalue(),'isolated.pdf')
        assert document['page_count'] == 1
        job = store.verify(document['id'],0)
        store.wait(job['id'])
        assert store.job(job['id'])['state'] == 'ready'
        assert store.job(job['id'])['result'] == []
        with pytest.raises(PdfWorkspaceError,match='Certificate could not be unlocked') as error:
            store.provider_file(b'bad certificate','do-not-expose')
        assert error.value.code == 'wrong_password'
        assert 'do-not-expose' not in str(error.value)
    finally:
        store.close()


def test_worker_timeout_terminates_and_replaces_before_next_request(workspace):
    from officekit.engines import engine_pdf_workspace as module
    process = Mock()
    process.submit.return_value.result.side_effect = TimeoutError('secret')
    replacement = Mock()
    replacement.submit.return_value.result.return_value = []
    workspace.process = process
    with patch.object(module,'ProcessPoolExecutor',return_value=replacement) as factory:
        # Remove the injected service so the worker boundary is exercised.
        workspace.signing = None
        with pytest.raises(PdfWorkspaceError,match='time limit') as error:
            workspace._call('signing','verify_pdf',b'pdf')
        assert error.value.code == 'worker_unavailable'
        process.terminate_workers.assert_called_once_with()
        factory.assert_called_once_with(max_workers=1,max_tasks_per_child=1)
        assert workspace._call('signing','verify_pdf',b'pdf') == []
        replacement.submit.assert_called_once_with(module._call_engine,'signing','verify_pdf',(b'pdf',),{})


def test_worker_termination_python_legacy_fallback(workspace):
    from officekit.engines import engine_pdf_workspace as module
    for alive in (False,True):
        worker = Mock()
        worker.is_alive.return_value = alive
        pool = Mock(spec=['_processes','shutdown'])
        pool._processes = {1:worker}
        workspace.process = pool
        with patch.object(module,'ProcessPoolExecutor',return_value=Mock()):
            workspace._reset_process()
        pool.shutdown.assert_called_once_with(wait=False,cancel_futures=True)
        worker.terminate.assert_called_once_with()
        assert worker.join.call_count == (2 if alive else 1)
        if alive:
            worker.kill.assert_called_once_with()
