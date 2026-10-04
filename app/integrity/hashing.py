"""SHA-256 of an uploaded verification sample file.

The upload is read in 1 MiB chunks and fed to hashlib; FORGE-X never
saves it, never opens it with another program and never executes it.
(Werkzeug may buffer a large upload in a temporary file while the request
is processed; that file is deleted automatically when the request ends.)
"""
import hashlib
import os

from werkzeug.utils import secure_filename

CHUNK = 1024 * 1024

# Permitted sample-file types (forensic images, captures, logs, documents).
ALLOWED_EXTENSIONS = {
    ".bin", ".img", ".dd", ".raw", ".e01", ".ex01", ".aff", ".vhd", ".vmdk", ".iso",
    ".pcap", ".pcapng", ".cap", ".log", ".evtx", ".txt", ".csv", ".json", ".xml",
    ".eml", ".msg", ".pdf", ".docx", ".xlsx", ".pptx", ".jpg", ".jpeg", ".png", ".zip",
}


class SampleFileError(ValueError):
    """The upload can't be used; the message is safe to show."""


def check_extension(filename):
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise SampleFileError("That file type isn't accepted as a verification sample. Allowed: "
                              + ", ".join(sorted(ALLOWED_EXTENSIONS)) + ".")


def sha256_of_upload(storage, max_bytes):
    """Return (hex_digest, size_in_bytes, safe_file_name) for a Werkzeug FileStorage."""
    if storage is None or not getattr(storage, "filename", ""):
        raise SampleFileError("Choose a sample file.")
    name = secure_filename(storage.filename) or "sample"
    check_extension(name)
    digest, size = hashlib.sha256(), 0
    stream = storage.stream
    while True:
        chunk = stream.read(CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise SampleFileError(f"Sample files must be {max_bytes // (1024 * 1024)} MB or smaller.")
        digest.update(chunk)
    if size == 0:
        raise SampleFileError("The file is empty.")
    return digest.hexdigest(), size, name[:255]
