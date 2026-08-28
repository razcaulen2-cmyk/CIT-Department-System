"""Generate a password hash for an admin password.

Tries to use Werkzeug's `generate_password_hash`. If Werkzeug is not
available, falls back to a compatible PBKDF2-SHA256 implementation so
the script can run without installing external packages.
"""
import os
import binascii
import hashlib
from getpass import getpass

try:
	from werkzeug.security import generate_password_hash  # type: ignore
except Exception:
	def generate_password_hash(password: str, method: str = "pbkdf2:sha256", salt_length: int = 8) -> str:
		if method.startswith("pbkdf2:"):
			# method format: pbkdf2:sha256
			_, algo = method.split(":", 1)
			iterations = 260000
			salt = binascii.hexlify(os.urandom(salt_length)).decode("ascii")
			dk = hashlib.pbkdf2_hmac(algo.split(":")[-1], password.encode("utf-8"), salt.encode("ascii"), iterations)
			hashed = binascii.hexlify(dk).decode("ascii")
			return f"pbkdf2:{algo}:{iterations}${salt}${hashed}"
		# fallback simple sha256 (not recommended for production)
		return hashlib.sha256(password.encode("utf-8")).hexdigest()


def main() -> None:
	password = getpass("Admin password: ")
	hashed_password = generate_password_hash(password)
	print(hashed_password)


if __name__ == "__main__":
	main()