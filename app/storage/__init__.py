"""Evidence file storage (FORGE-X 2.0 Phase 3, decision U1).

All access to stored evidence files goes through this module. Two backends
share one interface (FORGE-X 2.0 Phase 9):
  * LocalStorage  files on local disk (the default)
  * S3Storage     an S3-compatible object store such as MinIO or AWS S3
                  (app/storage/s3.py)
EVIDENCE_STORAGE_BACKEND chooses where NEW files go; every existing file is
read from where evidence_file_locations says it is (no row = local).

Local-disk backend guarantees:
  * Files live under EVIDENCE_STORAGE_DIR, outside the web folders; Flask
    never serves them directly. Downloads go through an authorised route.
  * Each file is named by a generated UUID (never the user's filename), in a
    two-character subfolder. Object IDs are validated before any path is built.
  * Write-once: files are created with exclusive-create mode (never
    overwritten) and made read-only after writing.
  * The SHA-256 and size are computed while the file is written, in 1 MiB
    chunks; an upload over the limit is removed and refused.
"""
import contextlib
import hashlib
import os
import re
import stat
import uuid

from flask import current_app

CHUNK = 1024 * 1024
OBJECT_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class StorageError(Exception):
    """A storage problem; the message is safe to show."""


class LocalStorage:
    name = "local"

    def __init__(self, base_dir):
        self.base_dir = os.path.abspath(base_dir)

    @property
    def container(self):
        return None

    def _path(self, object_id):
        if not OBJECT_ID_RE.match(object_id or ""):
            raise StorageError("Invalid stored-file identifier.")
        path = os.path.abspath(os.path.join(self.base_dir, object_id[:2], object_id))
        if os.path.dirname(os.path.dirname(path)) != self.base_dir:     # defence in depth
            raise StorageError("Invalid stored-file location.")
        return path

    def put(self, stream, max_bytes):
        """Write a new object from a binary stream. Returns (object_id, size, sha256)."""
        return self.put_as(str(uuid.uuid4()), stream, max_bytes)

    def put_as(self, object_id, stream, max_bytes):
        """Write an object under a given id (used when migrating between backends).
        Never overwrites: fails if the object already exists."""
        path = self._path(object_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        digest, size = hashlib.sha256(), 0
        try:
            with open(path, "xb") as out:                  # "x": fail rather than overwrite anything
                while True:
                    chunk = stream.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise StorageError(f"Evidence files must be {max_bytes / (1024 * 1024):g} MB or smaller.")
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if size == 0:
                raise StorageError("The file is empty.")
        except BaseException:
            self._remove(path)
            raise
        os.chmod(path, stat.S_IREAD)                       # read-only from now on (also on Windows)
        return object_id, size, digest.hexdigest()

    def open_read(self, object_id):
        path = self._path(object_id)
        if not os.path.isfile(path):
            raise StorageError("The stored file is missing from evidence storage.")
        return open(path, "rb")

    def sha256(self, object_id):
        """Re-hash a stored object, read-only. Returns (sha256, size)."""
        digest, size = hashlib.sha256(), 0
        with self.open_read(object_id) as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        return digest.hexdigest(), size

    @contextlib.contextmanager
    def materialize(self, object_id):
        """A path on local disk for read-only use by an isolated worker (YARA).
        Local files are used in place."""
        yield self.local_path(object_id)

    def local_path(self, object_id):
        """The validated on-disk path of a stored object, for read-only use by
        an isolated worker (YARA). A future object-storage backend would
        download the object to a temporary file here instead."""
        path = self._path(object_id)
        if not os.path.isfile(path):
            raise StorageError("The stored file is missing from evidence storage.")
        return path

    def exists(self, object_id):
        return os.path.isfile(self._path(object_id))

    def discard_unrecorded(self, object_id):
        """Remove a file whose database record could NOT be created (rollback
        of a failed registration). Never used for recorded evidence."""
        self._remove(self._path(object_id))

    def health(self):
        """(ok, message) for flask check-db."""
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            probe = os.path.join(self.base_dir, f".write-test-{uuid.uuid4().hex}")
            with open(probe, "xb") as f:
                f.write(b"ok")
            os.remove(probe)
        except OSError as err:
            return False, f"not writable: {self.base_dir} ({err.strerror})"
        free = _free_bytes(self.base_dir)
        return True, f"{self.base_dir} (free space {free // (1024 ** 3)} GB)" if free is not None else self.base_dir

    @staticmethod
    def _remove(path):
        try:
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            os.remove(path)
        except FileNotFoundError:
            pass


def _free_bytes(path):
    try:
        import shutil
        return shutil.disk_usage(path).free
    except OSError:
        return None


BACKENDS = ("local", "s3")


def get_storage(name=None):
    """A storage backend: `name` ("local" or "s3"), or by default the one new
    files go to (EVIDENCE_STORAGE_BACKEND)."""
    name = name or current_app.config.get("EVIDENCE_STORAGE_BACKEND", "local")
    if name == "local":
        return LocalStorage(current_app.config["EVIDENCE_STORAGE_DIR"])
    if name == "s3":
        from .s3 import S3Storage
        return S3Storage.from_config(current_app.config)
    raise StorageError(f"Unknown storage backend {name!r}.")


def storage_for(stored_file):
    """The backend where a recorded file currently is (its `backend` field)."""
    return get_storage(stored_file.get("backend") or "local")
