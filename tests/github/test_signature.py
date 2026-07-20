from app.github.signature import verify_signature

SECRET = "test-secret"
PAYLOAD = b'{"zen": "Keep it logically awesome."}'
VALID_SIGNATURE = "sha256=8769ade185bd581e6ddc7d3b8cfa13bf11176025b06a154752c9bec4be31a63c"


def test_verify_signature_valid():
    assert verify_signature(PAYLOAD, VALID_SIGNATURE, SECRET) is True


def test_verify_signature_invalid_hash():
    bad_signature = "sha256=" + "0" * 64
    assert verify_signature(PAYLOAD, bad_signature, SECRET) is False


def test_verify_signature_wrong_secret():
    assert verify_signature(PAYLOAD, VALID_SIGNATURE, "wrong-secret") is False


def test_verify_signature_tampered_payload():
    tampered = PAYLOAD.replace(b"awesome", b"terrible")
    assert verify_signature(tampered, VALID_SIGNATURE, SECRET) is False


def test_verify_signature_missing_prefix():
    raw_hex = VALID_SIGNATURE.removeprefix("sha256=")
    assert verify_signature(PAYLOAD, raw_hex, SECRET) is False


def test_verify_signature_empty_header():
    assert verify_signature(PAYLOAD, "", SECRET) is False
