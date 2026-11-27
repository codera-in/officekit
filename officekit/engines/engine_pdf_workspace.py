"""Bounded, private PDF documents and immutable output snapshots."""
import atexit
import io
import json
import math
import os
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool


class PdfWorkspaceError(ValueError):
    def __init__(self, message, status=422, code='invalid_request'):
        super().__init__(message)
        self.status = status
        self.code = code


def _call_engine(kind, method, args, kwargs):
    if kind == 'editor':
        from . import engine_pdf_editor as module
    else:
        from . import engine_pdf_signing as module
    return getattr(module, method)(*args, **kwargs)


class PdfWorkspace:
    MAX_BYTES = 64 * 1024 * 1024
    MAX_TOTAL_BYTES = 256 * 1024 * 1024
    MAX_SESSIONS = 4
    MAX_JOBS = 32
    TTL = 1800
    WORKER_TIMEOUT = 120

    def __init__(self, editor=None, signing=None, isolated=True, clock=time.monotonic):
        self.editor, self.signing, self.clock = editor, signing, clock
        self.documents, self.providers, self.artifacts, self.jobs, self.reviews = {}, {}, {}, {}, {}
        self.lock = threading.RLock()
        self.process_lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='officekit-pdf-jobs')
        self.process = ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1) if isolated else None

    def _call(self, kind, method, *args, **kwargs):
        service = self.editor if kind == 'editor' else self.signing
        try:
            if service is not None:
                return getattr(service, method)(*args, **kwargs)
            if self.process:
                with self.process_lock:
                    try:
                        return self.process.submit(_call_engine, kind, method, args, kwargs).result(timeout=self.WORKER_TIMEOUT)
                    except (TimeoutError, BrokenProcessPool):
                        self._reset_process()
                        raise PdfWorkspaceError('PDF worker stopped after exceeding its time limit or becoming unavailable.',
                                                503, 'worker_unavailable') from None
            return _call_engine(kind, method, args, kwargs)
        except Exception as error:
            if isinstance(error, PdfWorkspaceError):
                raise
            from .engine_pdf_signing import PdfSigningError
            from .engine_pdf_editor import PdfEditorError
            if isinstance(error, PdfSigningError):
                status = 503 if error.code in {'token_unavailable', 'online_unavailable'} else 422
                raise PdfWorkspaceError(str(error), status, error.code) from None
            if isinstance(error, PdfEditorError):
                raise PdfWorkspaceError(error.public_message, error.status_code, 'pdf_processing_failed') from None
            raise PdfWorkspaceError('The PDF operation failed.', 500, 'operation_failed') from None

    def _reset_process(self):
        """Called under process_lock: terminate before a replacement accepts work."""
        pool = self.process
        if hasattr(pool, 'terminate_workers'):
            pool.terminate_workers()
        else:
            # Python 3.11–3.13 lack the public termination API. Snapshot managed
            # workers before shutdown clears the registry, then reap every PID.
            workers = list(pool._processes.values())
            pool.shutdown(wait=False, cancel_futures=True)
            for worker in workers:
                worker.terminate()
                worker.join(timeout=1)
                if worker.is_alive():
                    worker.kill()
                    worker.join(timeout=1)
        self.process = ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1)

    @staticmethod
    def _id():
        return str(uuid.uuid4())

    def _prune(self):
        expired = [key for key, doc in self.documents.items() if doc['expires'] <= self.clock() and not doc['busy']]
        for key in expired:
            self._delete(key)
        self.providers = {key: value for key, value in self.providers.items() if value['expires'] > self.clock()}
        self.jobs = {key: value for key, value in self.jobs.items() if value['state'] in {'queued', 'running'} or value['expires'] > self.clock()}

    def _used(self):
        return (sum(len(data) for d in self.documents.values() for data in d['revisions'].values())
                + sum(len(a['data']) for a in self.artifacts.values())
                + sum(len(p.get('data', b'')) + len(json.dumps(p['certificates']).encode()) for p in self.providers.values())
                + sum(len(json.dumps(r).encode()) for r in self.reviews.values())
                + sum(len(json.dumps(j.get('result')).encode()) for j in self.jobs.values()))

    def _budget(self, size):
        if size > self.MAX_BYTES or size + self._used() > self.MAX_TOTAL_BYTES:
            raise PdfWorkspaceError('PDF workspace exceeds its memory limit. Close a document and try again.', 413)

    def _doc(self, key):
        self._prune()
        doc = self.documents.get(key)
        if doc is None:
            raise PdfWorkspaceError('PDF document is unavailable. Choose it again.', 404)
        if doc['source_check']:
            try:
                doc['source_check']()
            except Exception:
                raise PdfWorkspaceError('Source PDF changed. Choose it again.', 409, 'source_changed') from None
        doc['expires'] = self.clock() + self.TTL
        return doc

    def create(self, data, name, source_check=None):
        with self.lock:
            self._prune()
            if not isinstance(data, bytes) or not data.startswith(b'%PDF-'):
                raise PdfWorkspaceError('Choose a valid PDF file.')
            self._budget(len(data))
            if len(self.documents) >= self.MAX_SESSIONS:
                raise PdfWorkspaceError('Close a PDF before opening another.', 409)
            info = self._call('editor', 'inspect_document', data)
            signatures = self._call('signing', 'inspect_signatures', data)
            key = self._id()
            doc = {'id': key, 'name': os.path.basename(name)[:255], 'revision': 0, 'revisions': {0: data}, 'info': info,
                   'signatures': signatures, 'expires': self.clock() + self.TTL, 'busy': False, 'source_check': source_check}
            self.documents[key] = doc
            return self.get(key)

    def get(self, key, revision=None):
        with self.lock:
            doc = self._doc(key)
            revision = doc['revision'] if revision is None else revision
            if revision not in doc['revisions']:
                raise PdfWorkspaceError('PDF revision is unavailable.', 404)
            sig = doc['signatures']
            entries = sig.get('signatures', [])
            can_edit = not entries and sig.get('content_editing_allowed', True)
            return {**doc['info'], 'id': key, 'name': doc['name'], 'revision': revision,
                    'signatures': entries, 'permissions': {'can_edit': can_edit, 'can_sign': sig.get('signing_allowed', True)},
                    'capabilities': {'edit': can_edit, 'annotate': can_edit, 'ocr': can_edit, 'sign': sig.get('signing_allowed', True)},
                    'expires_at': doc['expires']}

    def content(self, key, revision):
        with self.lock:
            doc = self._doc(key)
            if revision not in doc['revisions']:
                raise PdfWorkspaceError('PDF revision is unavailable.', 404)
            return doc['revisions'][revision]

    def preview(self, key, page, revision, scale):
        with self.lock:
            data = self.content(key, revision)
            info = self.get(key, revision)
            if not 1 <= page <= info['page_count']:
                raise PdfWorkspaceError('Choose a valid page.')
            image = self._call('editor', 'render_page', data, page, scale=scale)
            if len(image) > 16 * 1024 * 1024:
                raise PdfWorkspaceError('Page preview exceeds its limit.', 413)
            return image, info['pages'][page - 1]

    def objects(self, key, page, revision, offset=0, limit=100):
        with self.lock:
            return self._call('editor', 'list_objects', self.content(key, revision), page, revision=revision, offset=offset, limit=limit)

    def revise(self, key, base_revision, operations):
        with self.lock:
            doc = self._doc(key)
            if doc['busy'] or base_revision != doc['revision']:
                raise PdfWorkspaceError('PDF changed or is busy. Refresh its revision.', 409)
            if not self.get(key)['permissions']['can_edit']:
                raise PdfWorkspaceError('This signed or protected PDF cannot be edited. Use a separate unsigned document.', 409)
            if len(doc['revisions']) >= 32:
                raise PdfWorkspaceError('Revision limit reached. Export and reopen the PDF to continue.', 413)
            prepared = []
            for operation in operations:
                op = operation.model_dump() if hasattr(operation, 'model_dump') else dict(operation)
                if op.get('kind') == 'apply_ocr':
                    review = self.ocr_review(key, op['review_id'])
                    if review['base_revision'] != base_revision or review['mode'] != op['ocr_mode']:
                        raise PdfWorkspaceError('OCR review belongs to an earlier revision.', 409)
                    region = next((r for r in review['regions'] if r['id'] == op.get('region_id')), None)
                    if region is None or region['page'] != op['page'] or region['rect'] != op['rect']:
                        raise PdfWorkspaceError('OCR correction does not match its reviewed region.', 409)
                prepared.append(op)
            output = self._call('editor', 'apply_operations', doc['revisions'][base_revision], prepared, revision=base_revision)
            self._budget(len(output))
            info = self._call('editor', 'inspect_document', output)
            self._doc(key)
            doc['revision'] += 1
            doc['revisions'][doc['revision']] = output
            doc['info'] = info
            return self.get(key)

    def restore(self, key, base_revision, restore_revision):
        """Undo/redo changes the head with optimistic locking, never accepts a stale edit."""
        with self.lock:
            doc = self._doc(key)
            if doc['busy'] or base_revision != doc['revision']:
                raise PdfWorkspaceError('PDF changed or is busy. Refresh its revision.', 409)
            if not self.get(key)['permissions']['can_edit']:
                raise PdfWorkspaceError('This signed or protected PDF cannot be edited.', 409)
            if len(doc['revisions']) >= 32:
                raise PdfWorkspaceError('Revision limit reached. Export and reopen the PDF to continue.', 413)
            data = self.content(key, restore_revision)
            self._budget(len(data))
            info = self._call('editor', 'inspect_document', data)
            self._doc(key)
            doc['revision'] += 1
            doc['revisions'][doc['revision']] = data
            doc['info'] = info
            return self.get(key)

    def _artifact(self, key, data, name):
        self._budget(len(data))
        artifact_id = self._id()
        self.artifacts[artifact_id] = {'document': key, 'data': data, 'name': name}
        return artifact_id

    def export(self, key, revision):
        with self.lock:
            data = self.content(key, revision)
            artifact_id = self._artifact(key, data, 'edited.pdf')
            return {'id': artifact_id, 'state': 'ready', 'phase': 'complete', 'result_ref': artifact_id}

    def artifact(self, key):
        with self.lock:
            self._prune()
            value = self.artifacts.get(key)
            if value is None:
                raise PdfWorkspaceError('PDF output is unavailable.', 404)
            self._doc(value['document'])
            return value['data'], value['name']

    def _delete(self, key):
        self.documents.pop(key, None)
        self.artifacts = {k: a for k, a in self.artifacts.items() if a['document'] != key}
        self.reviews = {k: a for k, a in self.reviews.items() if a['document'] != key}
        self.jobs = {k: a for k, a in self.jobs.items() if a['document'] != key}

    def delete(self, key):
        with self.lock:
            if self._doc(key)['busy']:
                raise PdfWorkspaceError('Wait for signing or cancel the current job before closing.', 409)
            self._delete(key)

    def provider_file(self, data, password):
        with self.lock:
            self._prune()
            self._budget(len(data))
            if len(self.providers) >= 8:
                raise PdfWorkspaceError('Certificate selection limit reached. Restart the workspace.', 413)
            summary = self._call('signing', 'certificate_summary', data, password)
            summary = {**summary, 'id': summary['fingerprint']}
            self._budget(len(data) + len(json.dumps([summary]).encode()))
            key = self._id()
            self.providers[key] = {'kind': 'pkcs12', 'data': data, 'certificates': [summary], 'expires': self.clock() + self.TTL}
            return {'id': key, 'kind': 'pkcs12', 'certificates': [summary]}

    def provider_native(self, path, source_check):
        with self.lock:
            self._prune()
            if len(self.providers) >= 8:
                raise PdfWorkspaceError('Provider selection limit reached.', 413)
            if not callable(source_check):
                raise PdfWorkspaceError('Choose a provider using the native file picker.', 403)
            source_check()
            summaries = self._call('signing', 'enumerate_token_certificates', path)
            source_check()
            self._budget(len(json.dumps(summaries).encode()))
            key = self._id()
            self.providers[key] = {'kind': 'pkcs11', 'path': path, 'source_check': source_check, 'certificates': summaries, 'expires': self.clock() + self.TTL}
            return {'id': key, 'kind': 'pkcs11', 'certificates': summaries}

    def _submit(self, key, phase, operation, signing=False):
        with self.lock:
            self._prune()
            doc = self._doc(key)
            if doc['busy'] or len(self.jobs) >= self.MAX_JOBS or sum(j['state'] in {'queued', 'running'} for j in self.jobs.values()) >= 4:
                raise PdfWorkspaceError('PDF workspace is busy. Wait for the current job.', 409)
            job_id = self._id()
            job = {'id': job_id, 'document': key, 'state': 'queued', 'phase': phase, 'error': None, 'result_ref': None,
                   'result': None, 'error_code': None, 'cancel': threading.Event(), 'signing': signing, 'expires': self.clock() + self.TTL}
            self.jobs[job_id] = job
            doc['busy'] = True
            def run():
                try:
                    with self.lock:
                        if job['cancel'].is_set():
                            job['state'] = 'cancelled'
                            return
                        job['state'] = 'running'
                    result, artifact_data = operation()
                    with self.lock:
                        if job['cancel'].is_set():
                            job['state'] = 'cancelled'
                        else:
                            self._doc(key)
                            result_size = len(json.dumps(result).encode())
                            self._budget(result_size * (2 if phase == 'recognising' else 1)
                                         + (len(artifact_data) if artifact_data else 0))
                            if artifact_data:
                                job['result_ref'] = self._artifact(key, artifact_data, 'signed.pdf')
                            if phase == 'recognising':
                                if len(self.reviews) >= 8:
                                    raise PdfWorkspaceError('OCR review limit reached.', 413)
                                self.reviews[result['review_id']] = result
                            job.update(state='ready', phase='complete', result=result)
                except Exception as error:
                    # Never retain raw exceptions: crypto/provider errors may contain secrets.
                    with self.lock:
                        if isinstance(error, PdfWorkspaceError):
                            job.update(state='failed', error=str(error), error_code=error.code)
                        else:
                            job.update(state='failed', error='The PDF operation failed.', error_code='operation_failed')
                finally:
                    with self.lock:
                        doc['busy'] = False
                        job['expires'] = self.clock() + self.TTL
            job['future'] = self.executor.submit(run)
            return self.job(job_id)

    def job(self, key):
        with self.lock:
            self._prune()
            job = self.jobs.get(key)
            if job is None:
                raise PdfWorkspaceError('PDF job is unavailable.', 404)
            return {k: job[k] for k in ('id', 'state', 'phase', 'error', 'error_code', 'result_ref', 'result')}

    def wait(self, key):
        self.jobs[key]['future'].result(timeout=180)

    def cancel(self, key):
        with self.lock:
            self.job(key)
            job = self.jobs[key]
            if job['state'] not in {'queued', 'running'} or (job['signing'] and job['state'] == 'running'):
                raise PdfWorkspaceError('This operation has already completed or cannot safely be cancelled.', 409)
            job['cancel'].set()
            return {'id': key, 'state': 'cancellation_requested'}

    def sign(self, key, revision, provider_id, certificate_id, secret, placement=None, reason=None):
        with self.lock:
            data = self.content(key, revision)
            doc = self._doc(key)
            if revision != doc['revision'] or not self.get(key)['permissions']['can_sign']:
                raise PdfWorkspaceError('This PDF revision cannot be signed.', 409)
            provider = self.providers.get(provider_id)
            if provider is None or provider['expires'] <= self.clock():
                raise PdfWorkspaceError('Signing provider is unavailable. Choose it again.', 404)
            if certificate_id not in {c['id'] for c in provider['certificates']}:
                raise PdfWorkspaceError('Choose a certificate from this provider.')
            kwargs = {'reason': reason}
            if placement:
                p = placement.model_dump() if hasattr(placement, 'model_dump') else placement
                if type(p.get('page')) is not int or not 1 <= p['page'] <= doc['info']['page_count']:
                    raise PdfWorkspaceError('Choose a valid signature page.')
                geom = doc['info']['pages'][p['page'] - 1]
                bounds = geom.get('crop_box', [0, 0, geom['width'], geom['height']])
                if (any(type(p.get(k)) not in (int, float) or not math.isfinite(p[k]) for k in ('x', 'y', 'width', 'height'))
                        or p['width'] <= 0 or p['height'] <= 0
                        or not (bounds[0] <= p['x'] < p['x'] + p['width'] <= bounds[2])
                        or not (bounds[1] <= p['y'] < p['y'] + p['height'] <= bounds[3])):
                    raise PdfWorkspaceError('Signature rectangle lies outside the page.')
                kwargs.update(page=p['page'] - 1, box=(p['x'], p['y'], p['x'] + p['width'], p['y'] + p['height']))
            def operation():
                if provider['kind'] == 'pkcs12':
                    output = self._call('signing', 'sign_pkcs12', data, provider['data'], secret, **kwargs)
                else:
                    provider['source_check']()
                    output = self._call('signing', 'sign_pkcs11', data, provider['path'], certificate_id, secret, **kwargs)
                    provider['source_check']()
                checks = self._call('signing', 'verify_pdf', output)
                if not checks or any(c.get('integrity') != 'valid' or c.get('modification_permissions') is False for c in checks):
                    raise PdfWorkspaceError('Signed output failed verification.', 422, 'verification_failed')
                return checks, output
            return self._submit(key, 'signing', operation, signing=True)

    def verify(self, key, revision):
        with self.lock:
            data = self.content(key, revision)
            if revision != self._doc(key)['revision']:
                raise PdfWorkspaceError('PDF changed. Refresh its revision.', 409)
            return self._submit(key, 'verification', lambda: (self._call('signing', 'verify_pdf', data), None))

    def ocr(self, key, revision, pages, language, mode):
        with self.lock:
            data = self.content(key, revision)
            if revision != self._doc(key)['revision']:
                raise PdfWorkspaceError('PDF changed. Refresh its revision.', 409)
            if not self.get(key)['permissions']['can_edit']:
                raise PdfWorkspaceError('This signed or protected PDF cannot be reconstructed.', 409)
            def operation():
                regions = self._call('editor', 'recognize_regions', data, pages, language=language)
                review_id = self._id()
                review = {'review_id': review_id, 'document': key, 'base_revision': revision, 'mode': mode, 'regions': regions}
                return review, None
            return self._submit(key, 'recognising', operation)

    def ocr_review(self, key, review_id):
        with self.lock:
            self._doc(key)
            review = self.reviews.get(review_id)
            if not review or review['document'] != key:
                raise PdfWorkspaceError('OCR review is unavailable.', 404)
            return review

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
        if self.process:
            self.process.shutdown(wait=True, cancel_futures=True)
        self.documents.clear()
        self.providers.clear()
        self.artifacts.clear()
        self.reviews.clear()
        self.jobs.clear()
