import base64

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def get_pem_from_jwks(jwk):
    modulus_b64 = jwk["n"]
    exponent_b64 = jwk["e"]

    modulus = int.from_bytes(base64.urlsafe_b64decode(modulus_b64 + "=="), "big")
    exponent = int.from_bytes(base64.urlsafe_b64decode(exponent_b64 + "=="), "big")

    public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key(default_backend())
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem
