from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv

load_dotenv()

# .env mein ENCRYPTION_KEY na ho to generate karke waha add karo (ek dafa generate karo, fixed rakho)
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise RuntimeError("ENCRYPTION_KEY not set in .env. Generate one with Fernet.generate_key() and add it.")

fernet = Fernet(ENCRYPTION_KEY.encode())


def encrypt_token(raw_token: str) -> str:
    return fernet.encrypt(raw_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    return fernet.decrypt(encrypted_token.encode()).decode()