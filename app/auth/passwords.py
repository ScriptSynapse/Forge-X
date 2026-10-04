"""Password rules and hashing.

Hashing uses Werkzeug's scrypt-based generate_password_hash: a random salt
is generated for every password and the result is slow to brute-force.
Only the hash is stored (users.password_hash or account_requests.password_hash).
"""
from werkzeug.security import check_password_hash, generate_password_hash

MIN_LENGTH = 12
MAX_LENGTH = 128   # long inputs make hashing slow; cap them

# A short list of passwords that technically meet the rules but are guessable.
COMMON_PASSWORDS = {
    "password1234", "password12345", "password@123", "passw0rd1234", "123456789abc",
    "qwerty123456", "qwertyuiop12", "welcome12345", "letmein12345", "admin1234567",
    "administrator1", "forgex123456", "forge-x12345", "changeme1234", "iloveyou1234",
}

_dummy_hash = None


def password_problems(password, username=None):
    """Return a list of human-readable problems (empty list = acceptable)."""
    problems = []
    password = password or ""
    if len(password) < MIN_LENGTH:
        problems.append(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        problems.append(f"Use {MAX_LENGTH} characters or fewer.")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        problems.append("Include at least one letter and one number.")
    if username and len(username) >= 3 and username.lower() in password.lower():
        problems.append("Don't include your username in the password.")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("That password is too common. Choose another.")
    return problems


def hash_password(password):
    return generate_password_hash(password)


def verify_password(stored_hash, password):
    try:
        return bool(stored_hash) and check_password_hash(stored_hash, password or "")
    except (ValueError, TypeError):
        return False


def burn_time(password):
    """Spend about as long as a real check, so response time does not reveal
    whether an account exists."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = generate_password_hash("forge-x-timing-equalizer-0")
    check_password_hash(_dummy_hash, password or "")
