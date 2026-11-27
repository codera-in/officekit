"""Local certificate signatures. Call only in a disposable signing worker.

Provider paths are trusted native-grant resolutions, never HTTP parameters.
No networking, credential persistence, PIN retries or vendor diagnostic exposure.
"""
from io import BytesIO
import math
from pathlib import Path
from uuid import uuid4

from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_CERTIFICATE_BYTES = 4 * 1024 * 1024


class PdfSigningError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

    def __reduce__(self):
        return type(self), (self.code, str(self))


def _reader(pdf: bytes):
    if not isinstance(pdf, bytes) or not 0 < len(pdf) <= MAX_PDF_BYTES:
        raise PdfSigningError("pdf_limit", "PDF exceeds the signing input limit.")
    try:
        reader = PdfFileReader(BytesIO(pdf), strict=True)
        if reader.encrypted:
            raise PdfSigningError("encrypted_pdf", "Unlock the PDF before signing.")
        if not 0 < int(reader.root['/Pages']['/Count']) <= 2000:
            raise PdfSigningError("pdf_limit", "PDF page count exceeds the limit.")
        return reader
    except PdfSigningError:
        raise
    except Exception:
        raise PdfSigningError("malformed_pdf", "PDF could not be inspected.") from None


def inspect_signatures(pdf: bytes) -> dict:
    reader = _reader(pdf)
    try:
        signatures = [{"field": s.field_name,
                       "permission": s.docmdp_level.name if s.docmdp_level else None}
                      for s in reader.embedded_signatures]
        return {"signatures": signatures, "content_editing_allowed": not signatures,
                "signing_allowed": all(s["permission"] != "NO_CHANGES" for s in signatures)}
    except Exception:
        raise PdfSigningError("malformed_pdf", "PDF signatures could not be inspected.") from None


def verify_pdf(pdf: bytes, *, network_consent: bool = False) -> list[dict]:
    if network_consent:
        # ponytail: safe bounded online revocation/timestamp transport is deferred.
        raise PdfSigningError("online_unavailable", "Online verification is unavailable.")
    reader = _reader(pdf)
    results = []
    try:
        for signature in reader.embedded_signatures:
            # The signer is a temporary anchor solely to check mathematical validity;
            # it is never presented as trusted. No system roots or fetchers are used.
            context = ValidationContext(trust_roots=[signature.signer_cert], allow_fetching=False)
            status = validate_pdf_signature(signature, signer_validation_context=context)
            results.append({"field": signature.field_name,
                            "integrity": "valid" if status.intact and status.valid else "invalid",
                            "trust": "unknown", "revocation": "not_checked",
                            "timestamp": "present_unverified" if status.timestamp_validity else "not_verified",
                            "modification_permissions": status.docmdp_ok,
                            "coverage": status.coverage.name if status.coverage else "unknown"})
        return results
    except Exception:
        raise PdfSigningError("verification_failed", "PDF signature verification failed.") from None


def _pkcs12(data: bytes, password: str):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_CERTIFICATE_BYTES:
        raise PdfSigningError("certificate_limit", "Certificate file exceeds the input limit.")
    if not isinstance(password, str) or len(password) > 1024:
        raise PdfSigningError("invalid_secret", "Invalid certificate password.")
    try:
        return signers.SimpleSigner.load_pkcs12_data(data, (), passphrase=password.encode())
    except Exception:
        raise PdfSigningError("wrong_password", "Certificate could not be unlocked.") from None


def _certificate(cert) -> dict:
    return {"subject": cert.subject.human_friendly,
            "issuer": cert.issuer.human_friendly,
            "serial": str(cert.serial_number),
            "fingerprint": cert.sha256.hex(),
            "valid_from": cert['tbs_certificate']['validity']['not_before'].native.isoformat(),
            "valid_until": cert['tbs_certificate']['validity']['not_after'].native.isoformat()}


def certificate_summary(pkcs12_data: bytes, password: str) -> dict:
    return _certificate(_pkcs12(pkcs12_data, password).signing_cert)


def _sign(pdf: bytes, signer, *, page=0, box=None, reason=None) -> bytes:
    permissions = inspect_signatures(pdf)
    if not permissions['signing_allowed']:
        raise PdfSigningError("permission_denied", "Document permissions prohibit signing.")
    reader = _reader(pdf)
    count = int(reader.root['/Pages']['/Count'])
    if type(page) is not int or not 0 <= page < count:
        raise PdfSigningError("invalid_placement", "Signature page is invalid.")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 256):
        raise PdfSigningError("invalid_reason", "Signature reason exceeds the limit.")
    if box is not None:
        if (not isinstance(box, (tuple, list)) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                or not (0 <= box[0] < box[2] and 0 <= box[1] < box[3])):
            raise PdfSigningError("invalid_placement", "Signature rectangle is invalid.")
        page_obj = reader.find_page_for_modification(page)[0].get_object()
        bounds = page_obj.get('/CropBox', page_obj['/MediaBox'])
        if not (bounds[0] <= box[0] < box[2] <= bounds[2]
                and bounds[1] <= box[1] < box[3] <= bounds[3]):
            raise PdfSigningError("invalid_placement", "Signature rectangle lies outside the page.")
    try:
        field = "OfficeKit_" + uuid4().hex
        writer = IncrementalPdfFileWriter(BytesIO(pdf))
        result = signers.PdfSigner(
            signers.PdfSignatureMetadata(field_name=field, reason=reason, md_algorithm='sha256'),
            signer=signer,
            new_field_spec=fields.SigFieldSpec(field, on_page=page, box=box),
        ).sign_pdf(writer).getvalue()
        checks = verify_pdf(result)
        if (not result.startswith(pdf) or len(result) > MAX_PDF_BYTES
                or not checks or any(c['integrity'] != 'valid' or c['modification_permissions'] is False
                                     for c in checks)):
            raise PdfSigningError("verification_failed", "Signed output failed verification.")
        return result
    except PdfSigningError:
        raise
    except Exception:
        raise PdfSigningError("signing_failed", "Certificate signing failed.") from None


def sign_pkcs12(pdf: bytes, pkcs12_data: bytes, password: str, **placement) -> bytes:
    return _sign(pdf, _pkcs12(pkcs12_data, password), **placement)


def enumerate_token_certificates(provider_path: Path) -> list[dict]:
    """Native caller must validate provider identity/architecture before this call."""
    try:
        from asn1crypto import x509
        from pkcs11 import Attribute, ObjectClass
        from pyhanko.sign.pkcs11 import open_pkcs11_session
        with open_pkcs11_session(str(provider_path)) as session:
            result = []
            for obj in session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}):
                if len(result) >= 64:
                    break
                cert = x509.Certificate.load(obj[Attribute.VALUE])
                result.append({**_certificate(cert), "id": bytes(obj[Attribute.ID]).hex()})
            return result
    except Exception:
        raise PdfSigningError("token_unavailable", "Token is unavailable or requires authentication.") from None


def sign_pkcs11(pdf: bytes, provider_path: Path, certificate_id: str, pin: str, **placement) -> bytes:
    """One login attempt only; a disposable worker must own this provider exclusively."""
    try:
        if not isinstance(pin, str) or not 0 < len(pin) <= 1024:
            raise ValueError()
        cert_id = bytes.fromhex(certificate_id)
        if not 0 < len(cert_id) <= 128:
            raise ValueError()
    except (ValueError, TypeError):
        raise PdfSigningError("invalid_token_input", "Invalid token certificate or PIN.") from None
    try:
        from pyhanko.sign.pkcs11 import PKCS11Signer, open_pkcs11_session
        with open_pkcs11_session(str(provider_path), user_pin=pin) as session:
            signer = PKCS11Signer(session, cert_id=cert_id, key_id=cert_id)
            return _sign(pdf, signer, **placement)
    except PdfSigningError:
        raise
    except Exception:
        raise PdfSigningError("token_signing_failed", "Token signing failed; check the token and PIN before retrying.") from None
