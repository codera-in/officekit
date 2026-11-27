"""HTTP validation and native-only provider authority."""
import io
import os
import struct
import threading
from unittest.mock import patch, Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from officekit.pdf_workspace_routes import create_pdf_router
from officekit.engines.engine_pdf_workspace import PdfWorkspace
from officekit.engines.engine_file_selections import FileSelectionStore
from tests.test_pdf_workspace_unittest import Editor, Signing
from tests.test_pdf_signing_unittest import material


def client_store():
    store = PdfWorkspace(editor=Editor(), signing=Signing(), isolated=False)
    app = FastAPI()
    app.include_router(create_pdf_router(store, FileSelectionStore(native_token='private')))
    return TestClient(app), store


def test_upload_revision_export_and_http_boundaries():
    client, store = client_store()
    try:
        response = client.post('/api/pdf-documents', files={'file': ('sample.pdf', b'%PDF-test')})
        assert response.status_code == 201
        doc = response.json()
        assert response.headers['location'].endswith(doc['id'])
        base = '/api/pdf-documents/' + doc['id']
        assert client.get(base).json()['revision'] == 0
        assert client.get(base + '/previews/1').content == b'png'
        assert client.get(base + '/objects').status_code == 200
        assert client.post(base + '/revisions', json={'base_revision': 0, 'operations': [], 'path': '/tmp/a'}).status_code == 422
        result = client.post(base + '/exports', json={'revision': 0})
        assert result.status_code == 202
        assert client.get('/api/pdf-workspace-artifacts/' + result.json()['result_ref']).content == b'%PDF-test'
        assert client.delete(base).status_code == 204
        assert client.get(base).status_code == 404
    finally:
        store.close()


def test_untrusted_library_paths_and_duplicate_sources_are_rejected():
    client, store = client_store()
    try:
        response = client.post('/api/pdf-signing-providers/native', json={'path': '/tmp/evil.dylib'})
        assert response.status_code == 403
        assert client.post('/api/pdf-documents', files={'file': ('x.pdf', b'%PDF-test')}, data={'selection_id': 'opaque'}).status_code == 422
        assert client.post('/api/pdf-documents').status_code == 422
        assert client.post('/api/pdf-signing-providers', data={'kind': 'pkcs11', 'path': '/tmp/evil'}).status_code == 422
    finally:
        store.close()


def test_actual_http_edit_annotate_export_sign_and_verify(material):
    from pypdf import PdfReader
    from officekit.engines.engine_pdf_signing import verify_pdf
    pdf, certificate = material
    store = PdfWorkspace(isolated=False)
    app = FastAPI()
    app.include_router(create_pdf_router(store,FileSelectionStore(native_token='private')))
    client = TestClient(app)
    try:
        response = client.post('/api/pdf-documents',files={'file':('original.pdf',pdf)})
        assert response.status_code == 201, response.text
        document = response.json()
        base = '/api/pdf-documents/' + document['id']
        listed = client.get(base+'/objects').json()
        text = next(obj for obj in listed['objects'] if obj['kind']=='text')
        rect = [text['x'],text['y'],text['x']+text['width'],text['y']+text['height']]
        edited = client.post(base+'/revisions',json={'base_revision':0,'operations':[
            {'kind':'replace_text','page':1,'object_id':text['id'],'rect':rect,'text':'Replacement content',
             'font':'Helvetica','font_size':12.0}]})
        assert edited.status_code == 201, edited.text
        assert edited.headers['location'].endswith('/revisions/1')
        annotated = client.post(base+'/revisions',json={'base_revision':1,'operations':[
            {'kind':'annotation','annotation_type':'rectangle','page':1,'rect':[50.0,50.0,200.0,100.0]}]})
        assert annotated.status_code == 201, annotated.text
        assert client.get(base+'/revisions/2').json()['revision'] == 2
        preview = client.get(base+'/previews/1?revision=2')
        assert preview.content.startswith(b'\x89PNG')
        assert preview.headers['content-type'] == 'image/png'
        exported = client.post(base+'/exports',json={'revision':2}).json()
        artifact = client.get('/api/pdf-workspace-artifacts/'+exported['result_ref'])
        assert artifact.headers['content-type'] == 'application/pdf'
        assert 'attachment;' in artifact.headers['content-disposition']
        reader = PdfReader(io.BytesIO(artifact.content))
        assert 'Replacement content' in reader.pages[0].extract_text()
        assert 'Original document content' not in reader.pages[0].extract_text()
        assert reader.pages[0]['/Annots'][0].get_object()['/Subtype'] == '/Square'
        # Undo creates a new head; edits can branch from it and a later undo
        # must still produce a signable immutable revision.
        undo = client.post(base+'/revisions',json={'base_revision':2,'restore_revision':0})
        assert undo.status_code == 201,undo.text
        assert undo.json()['revision'] == 3
        branch = client.post(base+'/revisions',json={'base_revision':3,'operations':[
            {'kind':'add_text','page':1,'rect':[40.0,640.0,180.0,670.0],'text':'Branch content'}]})
        assert branch.status_code == 201,branch.text
        undo_again = client.post(base+'/revisions',json={'base_revision':4,'restore_revision':0})
        assert undo_again.status_code == 201,undo_again.text
        assert undo_again.json()['revision'] == 5
        stale = client.post(base+'/revisions',json={'base_revision':4,'restore_revision':2})
        assert stale.status_code == 409
        wrong = client.post('/api/pdf-signing-providers',files={'file':('signer.p12',certificate)},data={'password':'private-wrong-password'})
        assert wrong.status_code == 422
        assert 'private-wrong-password' not in wrong.text
        provider = client.post('/api/pdf-signing-providers',files={'file':('signer.p12',certificate)},data={'password':'test-password'})
        assert provider.status_code == 201, provider.text
        provider = provider.json()
        certificate_id = provider['certificates'][0]['id']
        assert certificate_id == provider['certificates'][0]['fingerprint']
        signed = client.post(base+'/signatures',json={'revision':5,'provider_id':provider['id'],
            'certificate_id':certificate_id,'secret':'test-password',
            'placement':{'page':1,'x':50.0,'y':50.0,'width':150.0,'height':50.0}})
        assert signed.status_code == 202,signed.text
        store.wait(signed.json()['id'])
        result = client.get(base+'/signatures/'+signed.json()['id'])
        assert result.status_code == 200
        assert result.json()['state'] == 'ready', result.text
        assert 'test-password' not in result.text
        final = client.get('/api/pdf-workspace-artifacts/'+result.json()['result_ref'])
        assert final.content.startswith(client.get('/api/pdf-workspace-artifacts/'+client.post(base+'/exports',json={'revision':5}).json()['result_ref']).content)
        assert verify_pdf(final.content)[0]['integrity'] == 'valid'
        verify = client.post(base+'/verifications',json={'revision':5})
        assert verify.status_code == 202
        store.wait(verify.json()['id'])
        assert client.get('/api/pdf-workspace-jobs/'+verify.json()['id']).json()['state'] == 'ready'
        assert client.post(base+'/verifications',json={'revision':2,'network_consent':True}).status_code == 503
        assert client.post('/api/pdf-workspace-jobs/'+verify.json()['id']+'/cancellations',json={}).status_code == 409
    finally:
        store.close()


def test_native_source_grant_revalidates_original(tmp_path,monkeypatch):
    selections = FileSelectionStore(native_token='private')
    file = tmp_path/'original.pdf'
    file.write_bytes(b'%PDF-test')
    grant = selections.register_native([str(file)],credential='private')['id']
    store = PdfWorkspace(editor=Editor(),signing=Signing(),isolated=False)
    app = FastAPI()
    app.include_router(create_pdf_router(store,selections))
    client = TestClient(app)
    try:
        monkeypatch.setenv('OFFICEKIT_API_TOKEN','private-api')
        assert client.post('/api/pdf-documents',files={'file':('sample.pdf',b'%PDF-test')}).status_code == 403
        created = client.post('/api/pdf-documents',data={'selection_id':grant})
        assert created.status_code == 201,created.text
        base = '/api/pdf-documents/'+created.json()['id']
        file.write_bytes(b'%PDF-changed-content')
        assert client.get(base).status_code == 409
        assert client.post('/api/pdf-signing-providers',files={'file':('cert.p12',b'certificate')}).status_code == 403
        directory = selections.register_native([str(tmp_path)],credential='private')['id']
        assert client.post('/api/pdf-documents',data={'selection_id':directory}).status_code == 422
        assert client.post('/api/pdf-documents',data={'selection_id':'unknown'}).status_code in (404,422)
        file.unlink()
        assert client.post('/api/pdf-documents',data={'selection_id':grant}).status_code == 404
    finally:
        store.close()


def test_http_error_envelopes_and_all_missing_resources():
    client,store = client_store()
    try:
        endpoints = [('get','/api/pdf-documents/missing',None),
          ('get','/api/pdf-documents/missing/revisions/0',None),
          ('delete','/api/pdf-documents/missing',None),
          ('get','/api/pdf-documents/missing/previews/1',None),
          ('get','/api/pdf-documents/missing/objects',None),
          ('post','/api/pdf-documents/missing/revisions',{'base_revision':0,'operations':[{'kind':'add_text','page':1,'text':'x','rect':[0.0,0.0,20.0,20.0]}]}),
          ('post','/api/pdf-documents/missing/exports',{'revision':0}),
          ('post','/api/pdf-documents/missing/ocr-reviews',{'base_revision':0,'pages':[1]}),
          ('get','/api/pdf-documents/missing/ocr-reviews/missing',None),
          ('post','/api/pdf-documents/missing/signatures',{'revision':0,'provider_id':'p','certificate_id':'c','secret':'private-secret'}),
          ('get','/api/pdf-documents/missing/signatures/missing',None),
          ('post','/api/pdf-documents/missing/verifications',{'revision':0}),
          ('get','/api/pdf-workspace-jobs/missing',None),
          ('post','/api/pdf-workspace-jobs/missing/cancellations',{}),
          ('get','/api/pdf-workspace-artifacts/missing',None)]
        for method,url,body in endpoints:
            result = client.request(method,url,json=body) if body is not None else client.request(method,url)
            assert result.status_code == 404,(url,result.text)
            assert 'private-secret' not in result.text
        doc = client.post('/api/pdf-documents',files={'file':('x.pdf',b'%PDF-test')}).json()
        base = '/api/pdf-documents/'+doc['id']
        assert client.get(base+'/signatures/not-owned').status_code == 404
        assert client.post(base+'/signatures',json={'revision':0,'provider_id':'p','certificate_id':'c','secret':'x'*1025}).status_code == 422
        job = client.post(base+'/ocr-reviews',json={'base_revision':0,'pages':[1],'mode':'searchable'}).json()
        store.wait(job['id'])
        review = client.get('/api/pdf-workspace-jobs/'+job['id']).json()['result']
        result = client.get(base+'/ocr-reviews/'+review['review_id'])
        assert result.status_code == 200
        assert result.json()['result']['regions'][0]['text'] == 'scan'
        with patch.object(store,'MAX_BYTES',4):
            assert client.post('/api/pdf-documents',files={'file':('x.pdf',b'%PDF-test')}).status_code == 413
    finally:
        store.close()


def test_explicit_public_error_types_are_sanitized():
    from officekit.pdf_workspace_routes import public_error
    from officekit.engines.engine_pdf_editor import PdfEditorError
    from officekit.engines.engine_pdf_signing import PdfSigningError
    for error,status in [(PermissionError('private'),403),(FileNotFoundError('private'),404),
                         (PdfEditorError('OCR unavailable',503),503),
                         (PdfSigningError('wrong_password','Certificate could not be unlocked.'),422),
                         (RuntimeError('private'),422)]:
        actual = public_error(error)
        assert actual.status_code == status
        assert 'private' not in actual.detail


def test_certificate_native_grant_and_bounded_source(tmp_path):
    selections = FileSelectionStore(native_token='private')
    certificate = tmp_path/'cert.p12'
    certificate.write_bytes(b'certificate')
    grant = selections.register_native([str(certificate)],credential='private')['id']
    store = PdfWorkspace(editor=Editor(),signing=Signing(),isolated=False)
    app = FastAPI()
    app.include_router(create_pdf_router(store,selections))
    client = TestClient(app)
    try:
        response = client.post('/api/pdf-signing-providers',data={'selection_id':grant,'password':'secret'})
        assert response.status_code == 201,response.text
        assert response.json()['certificates'][0]['id']=='cert'
        original = tmp_path/'big.pdf'
        original.write_bytes(b'%PDF-too-big')
        grant = selections.register_native([str(original)],credential='private')['id']
        store.MAX_BYTES = 4
        assert client.post('/api/pdf-documents',data={'selection_id':grant}).status_code == 413
        certificate.write_bytes(b'x' * (2*1024*1024+1))
        grant = selections.register_native([str(certificate)],credential='private')['id']
        assert client.post('/api/pdf-signing-providers',data={'selection_id':grant,'password':'secret'}).status_code == 413
    finally:
        store.close()


def test_native_provider_checked_before_load_and_identity_rechecked(tmp_path):
    from officekit import pdf_workspace_routes as routes
    client,store = client_store()
    library = tmp_path/'provider.dylib'
    library.write_bytes(b'\xcf\xfa\xed\xfe'+struct.pack('<I',0x0100000C))
    library.chmod(0o600)
    headers = {'X-OfficeKit-Native-Grant':'private'}
    try:
        with patch.object(routes,'validate_provider_binary') as validate, \
             patch.object(store.signing,'enumerate_token_certificates',create=True,return_value=[{'id':'token'}]) as enumerate:
            response = client.post('/api/pdf-signing-providers/native',json={'path':str(library)},headers=headers)
            assert response.status_code == 201,response.text
            validate.assert_called_once_with(str(library))
            enumerate.assert_called_once_with(library)
        bad = tmp_path/'untrusted.txt'
        bad.write_bytes(b'anything')
        assert client.post('/api/pdf-signing-providers/native',json={'path':str(bad)},headers=headers).status_code == 422
        library.chmod(0o666)
        assert client.post('/api/pdf-signing-providers/native',json={'path':str(library)},headers=headers).status_code == 403
        library.chmod(0o600)
        def changed(path):
            path.write_bytes(b'changed provider')
            return []
        with patch.object(routes,'validate_provider_binary'), \
             patch.object(store.signing,'enumerate_token_certificates',create=True,side_effect=changed):
            response = client.post('/api/pdf-signing-providers/native',json={'path':str(library)},headers=headers)
            assert response.status_code == 409,response.text
            assert str(library) not in response.text
    finally:
        store.close()


@pytest.mark.parametrize('host,machine,header',[
    ('darwin','arm64',b'\xcf\xfa\xed\xfe'+struct.pack('<I',0x0100000C)),
    ('darwin','x86_64',b'\xcf\xfa\xed\xfe'+struct.pack('<I',0x01000007)),
    ('darwin','arm64',b'\xca\xfe\xba\xbe'+struct.pack('>I',1)+struct.pack('>I',0x0100000C)+bytes(16)),
    ('darwin','x86_64',b'\xca\xfe\xba\xbf'+struct.pack('>I',1)+struct.pack('>I',0x01000007)+bytes(28)),
    ('win32','x86_64',b'MZ'+bytes(58)+struct.pack('<I',64)+b'PE\0\0'+struct.pack('<H',0x8664)),
    ('win32','arm64',b'MZ'+bytes(58)+struct.pack('<I',64)+b'PE\0\0'+struct.pack('<H',0xAA64)),
    ('linux','x86_64',b'\x7fELF\x02\x01'+bytes(12)+struct.pack('<H',62)),
    ('linux','aarch64',b'\x7fELF\x02\x01'+bytes(12)+struct.pack('<H',183)),
])
def test_provider_binary_matches_host_before_loading(tmp_path,host,machine,header):
    from officekit import pdf_workspace_routes as routes
    library = tmp_path/'provider.bin'
    library.write_bytes(header)
    with patch.object(routes.sys,'platform',host),patch.object(routes.platform,'machine',return_value=machine):
        assert routes.validate_provider_binary(library) is None
        library.write_bytes(b'untrusted malformed binary')
        with pytest.raises(Exception,match='does not match'):
            routes.validate_provider_binary(library)


def test_http_queued_cancellation_success():
    client,store = client_store()
    entered,release = threading.Event(),threading.Event()
    def block():
        entered.set()
        assert release.wait(5)
    future = store.executor.submit(block)
    try:
        assert entered.wait(5)
        doc = client.post('/api/pdf-documents',files={'file':('sample.pdf',b'%PDF-test')}).json()
        job = client.post('/api/pdf-documents/'+doc['id']+'/verifications',json={'revision':0}).json()
        response = client.post('/api/pdf-workspace-jobs/'+job['id']+'/cancellations',json={})
        assert response.status_code == 202,response.text
        release.set()
        future.result(5)
        store.wait(job['id'])
        assert client.get('/api/pdf-workspace-jobs/'+job['id']).json()['state']=='cancelled'
    finally:
        release.set()
        store.close()
