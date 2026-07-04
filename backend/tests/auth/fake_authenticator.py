"""A minimal, real-crypto fake WebAuthn authenticator for tests.

Implements just enough of the WebAuthn ceremony (ES256 / "none" attestation) to produce
credentials/assertions that `py_webauthn`'s own `verify_registration_response` /
`verify_authentication_response` genuinely accept - no browser or hardware key involved,
but no verification logic is stubbed out either; the real signature checks run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

_UP = 0x01  # user present
_AT = 0x40  # attested credential data included


def _client_data_json(*, type_: str, challenge: bytes, origin: str) -> bytes:
    payload = {"type": type_, "challenge": bytes_to_base64url(challenge), "origin": origin}
    return json.dumps(payload).encode()


def _cose_p256_public_key(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    numbers = private_key.public_key().public_numbers()
    x = numbers.x.to_bytes(32, "big")
    y = numbers.y.to_bytes(32, "big")
    # COSE_Key map: kty=EC2(2), alg=ES256(-7), crv=P-256(1), x, y
    cose_key = {1: 2, 3: -7, -1: 1, -2: x, -3: y}
    return bytes(cbor2.dumps(cose_key))


@dataclass
class FakeAuthenticator:
    """A single fake platform authenticator holding one ES256 keypair."""

    credential_id: bytes
    private_key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )
    sign_count: int = 0

    @classmethod
    def generate(cls, credential_id: bytes) -> FakeAuthenticator:
        return cls(credential_id=credential_id)

    def _authenticator_data(self, rp_id: str, *, attested: bool) -> bytes:
        rp_id_hash = hashlib.sha256(rp_id.encode()).digest()
        flags = _UP | (_AT if attested else 0)
        self.sign_count += 1
        out = rp_id_hash + bytes([flags]) + self.sign_count.to_bytes(4, "big")
        if attested:
            aaguid = b"\x00" * 16
            out += (
                aaguid
                + len(self.credential_id).to_bytes(2, "big")
                + self.credential_id
                + _cose_p256_public_key(self.private_key)
            )
        return out

    def registration_response(self, *, challenge: bytes, rp_id: str, origin: str) -> dict[str, Any]:
        """Build a `RegistrationResponseJSON`-shaped dict as the browser would return it."""
        client_data = _client_data_json(
            type_="webauthn.create", challenge=challenge, origin=origin
        )
        auth_data = self._authenticator_data(rp_id, attested=True)
        attestation_object = bytes(
            cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        )
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation_object),
                "transports": ["internal"],
            },
            "type": "public-key",
            "authenticatorAttachment": "platform",
        }

    def authentication_response(
        self, *, challenge: bytes, rp_id: str, origin: str
    ) -> dict[str, Any]:
        """Build an `AuthenticationResponseJSON`-shaped dict as the browser would return it."""
        client_data = _client_data_json(type_="webauthn.get", challenge=challenge, origin=origin)
        auth_data = self._authenticator_data(rp_id, attested=False)
        signature_base = auth_data + hashlib.sha256(client_data).digest()
        signature = self.private_key.sign(signature_base, ec.ECDSA(hashes.SHA256()))
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
            },
            "type": "public-key",
        }
