"""Genera el hash de contraseña para .streamlit/secrets.toml.

Uso:  python generar_hash.py
Copie la línea resultante en [credentials] password_hash = "..."
"""
import base64
import getpass
import hashlib
import os

ITERACIONES = 600_000

pwd = getpass.getpass("Nueva contraseña: ")
if pwd != getpass.getpass("Repetir contraseña: "):
    raise SystemExit("Las contraseñas no coinciden.")
if len(pwd) < 10:
    raise SystemExit("Use al menos 10 caracteres.")

salt = os.urandom(16)
dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, ITERACIONES)
print(f'password_hash = "pbkdf2_sha256${ITERACIONES}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"')
