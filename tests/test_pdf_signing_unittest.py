"""Real certificate/PDF acceptance checks for local signing."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch
from pathlib import Path
from types import SimpleNamespace
import pickle

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from reportlab.pdfgen.canvas import Canvas

from officekit.engines import engine_pdf_signing as signing


@pytest.fixture
def material():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OfficeKit test signer")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=30))
            .sign(key, hashes.SHA256()))
    bundle = pkcs12.serialize_key_and_certificates(b"test", key, cert, None,
                 serialization.BestAvailableEncryption(b"test-password"))
    out = BytesIO()
    canvas = Canvas(out)
    canvas.drawString(72, 720, "Original document content")
    canvas.save()
    return out.getvalue(), bundle


def test_real_pkcs12_incremental_signatures(material):
    pdf, bundle = material
    assert signing.certificate_summary(bundle, "test-password")["subject"] == "Common Name: OfficeKit test signer"
    assert signing.inspect_signatures(pdf)["signatures"] == []
    signed = signing.sign_pkcs12(pdf, bundle, "test-password", box=(50, 50, 250, 100))
    assert signed.startswith(pdf)
    summary = signing.verify_pdf(signed)
    assert len(summary) == 1
    assert summary[0]["integrity"] == "valid"
    assert summary[0]["trust"] == "unknown"
    twice = signing.sign_pkcs12(signed, bundle, "test-password")
    assert twice.startswith(signed)
    assert all(item["integrity"] == "valid" for item in signing.verify_pdf(twice))


def test_safe_failures(material):
    pdf, bundle = material
    with pytest.raises(signing.PdfSigningError, match="Certificate could not be unlocked"):
        signing.sign_pkcs12(pdf, bundle, "secret-wrong")
    for invalid in (b"not PDF", b"%PDF-1.7\ninvalid"):
        with pytest.raises(signing.PdfSigningError):
            signing.inspect_signatures(invalid)
    with pytest.raises(signing.PdfSigningError, match="Online verification is unavailable"):
        signing.verify_pdf(pdf, network_consent=True)
    with pytest.raises(signing.PdfSigningError):
        signing.sign_pkcs12(pdf, bundle, "test-password", page=999)
    with pytest.raises(signing.PdfSigningError):
        signing.sign_pkcs12(pdf, bundle, "test-password", box=(0, 0, float("nan"), 100))


def test_public_signing_error_survives_worker_serialization():
    error = pickle.loads(pickle.dumps(signing.PdfSigningError('wrong_password','Certificate could not be unlocked.')))
    assert error.code == 'wrong_password'
    assert str(error) == 'Certificate could not be unlocked.'


def test_limits_and_bad_fields(material):
    pdf, bundle = material
    for value in (b"", "bad"):
        with pytest.raises(signing.PdfSigningError):
            signing.inspect_signatures(value)
        with pytest.raises(signing.PdfSigningError):
            signing.certificate_summary(value, "")
    for password in (None, "x" * 1025):
        with pytest.raises(signing.PdfSigningError):
            signing.certificate_summary(bundle, password)
    for placement in ({"reason": "x" * 257}, {"box": (-1, 0, 10, 20)},
                      {"box": (0, 0, 10000, 10000)}, {"page": True}):
        with pytest.raises(signing.PdfSigningError):
            signing.sign_pkcs12(pdf, bundle, "test-password", **placement)


def test_encrypted_and_invalid_page_counts(material):
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter(clone_from=PdfReader(BytesIO(material[0])))
    writer.encrypt("secret")
    out = BytesIO()
    writer.write(out)
    with pytest.raises(signing.PdfSigningError, match="Unlock"):
        signing.inspect_signatures(out.getvalue())
    with patch.object(signing, "PdfFileReader", return_value=SimpleNamespace(encrypted=False, root={'/Pages': {'/Count': 0}})):
        with pytest.raises(signing.PdfSigningError, match="page count"):
            signing.inspect_signatures(material[0])


def test_permission_and_verification_guards(material):
    from pyhanko.sign import fields, signers
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    pdf, bundle = material
    signer = signing._pkcs12(bundle, "test-password")
    locked = signers.PdfSigner(signers.PdfSignatureMetadata(field_name='Locked', certify=True,
                               docmdp_permissions=fields.MDPPerm.NO_CHANGES), signer=signer).sign_pdf(
                                   IncrementalPdfFileWriter(BytesIO(pdf))).getvalue()
    assert signing.inspect_signatures(locked)['signing_allowed'] is False
    with pytest.raises(signing.PdfSigningError, match="prohibit"):
        signing.sign_pkcs12(locked, bundle, "test-password")
    signed = signing.sign_pkcs12(pdf, bundle, "test-password")
    with patch.object(signing, 'validate_pdf_signature', side_effect=RuntimeError('private')):
        with pytest.raises(signing.PdfSigningError, match="verification failed"):
            signing.verify_pdf(signed)
    with patch.object(signing, 'verify_pdf', return_value=[]):
        with pytest.raises(signing.PdfSigningError, match="failed verification"):
            signing.sign_pkcs12(pdf, bundle, "test-password")
    with patch.object(signing.signers, 'PdfSigner', side_effect=RuntimeError('private')):
        with pytest.raises(signing.PdfSigningError, match="signing failed"):
            signing.sign_pkcs12(pdf, bundle, "test-password")
    with patch.object(signing, '_reader', return_value=SimpleNamespace(embedded_signatures=[object()])):
        with pytest.raises(signing.PdfSigningError, match="could not be inspected"):
            signing.inspect_signatures(pdf)


def test_token_login_once_and_sanitized(material):
    from pyhanko.sign import pkcs11
    provider = Path('/native-granted/provider.dylib')
    with patch.object(pkcs11, 'open_pkcs11_session', side_effect=RuntimeError('PIN SECRET')) as open_session:
        with pytest.raises(signing.PdfSigningError, match="check the token and PIN") as error:
            signing.sign_pkcs11(material[0], provider, '01', '1234')
        assert 'SECRET' not in str(error.value)
        open_session.assert_called_once_with(str(provider), user_pin='1234')
    with patch.object(pkcs11, 'open_pkcs11_session', side_effect=RuntimeError('private')) as open_session:
        with pytest.raises(signing.PdfSigningError, match="unavailable"):
            signing.enumerate_token_certificates(provider)
        open_session.assert_called_once_with(str(provider))
    for cert_id, pin in [('xyz', '1'), ('', '1'), ('01', ''), ('01', None)]:
        with pytest.raises(signing.PdfSigningError, match="Invalid token"):
            signing.sign_pkcs11(material[0], provider, cert_id, pin)


def test_token_adapter_success_and_cleanup(material):
    from pyhanko.sign import pkcs11
    from pkcs11 import Attribute, ObjectClass
    provider = Path('/native/provider')
    cert = signing._pkcs12(material[1], 'test-password').signing_cert
    session = MagicMock()
    session.get_objects.return_value = [{Attribute.VALUE: cert.dump(), Attribute.ID: b'\x01'}] * 65
    context = MagicMock()
    context.__enter__.return_value = session
    with patch.object(pkcs11, 'open_pkcs11_session', return_value=context):
        result = signing.enumerate_token_certificates(provider)
        assert len(result) == 64
        assert result[0]['id'] == '01'
        session.get_objects.assert_called_once_with({Attribute.CLASS: ObjectClass.CERTIFICATE})
    context.reset_mock()
    with patch.object(pkcs11, 'open_pkcs11_session', return_value=context) as opening, \
         patch.object(pkcs11, 'PKCS11Signer', return_value='signer') as signer, \
         patch.object(signing, '_sign', return_value=b'output') as sign:
        assert signing.sign_pkcs11(material[0], provider, '01', '1234', page=0) == b'output'
        opening.assert_called_once_with(str(provider), user_pin='1234')
        signer.assert_called_once_with(session, cert_id=b'\x01', key_id=b'\x01')
        sign.assert_called_once_with(material[0], 'signer', page=0)
        context.__exit__.assert_called_once()
    with patch.object(pkcs11, 'open_pkcs11_session', return_value=context), \
         patch.object(pkcs11, 'PKCS11Signer', side_effect=signing.PdfSigningError('permission', 'denied')):
        with pytest.raises(signing.PdfSigningError, match='denied'):
            signing.sign_pkcs11(material[0], provider, '01', '1234')
