from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import logging

logger = logging.getLogger(__name__)
# Generate private key
private_key = rsa.generate_private_key(
    public_exponent=65537, key_size=2048, backend=default_backend()
)

# Serialize private key to PEM format
private_key_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
)

# Save private key to a file
with open("private_key.pem", "wb") as f:
    f.write(private_key_pem)

# Generate public key
public_key = private_key.public_key()

# Serialize public key to PEM format
public_key_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

# Save public key to a file
with open("public_key.pem", "wb") as f:
    f.write(public_key_pem)

logger.info("RSA keys generated and saved as 'private_key.pem' and 'public_key.pem'")
