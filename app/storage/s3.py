"""S3-compatible evidence storage (MinIO or AWS S3), FORGE-X 2.0 Phase 9.

Same interface and guarantees as LocalStorage:
  * Object keys are <prefix><generated UUID>; the user's filename is never used.
  * Write-once: every write is conditional (If-None-Match: *), so S3 refuses
    to overwrite an existing object. Turn this off (S3_CONDITIONAL_WRITES=0)
    only for a server that doesn't support conditional writes.
  * The SHA-256 and size are computed while the upload is received, by
    streaming it into a temporary local file (so an over-limit upload is
    refused before anything reaches the bucket), then uploaded.
  * Private: FORGE-X never creates public or presigned URLs; downloads are
    streamed through the application (permission check, custody entry, audit).
    health() warns if the bucket policy is public.
  * Optional server-side encryption (S3_SSE, e.g. "AES256").
The client is injected, so the backend is testable without a server.
"""
import contextlib
import hashlib
import os
import stat
import tempfile
import uuid

from . import CHUNK, OBJECT_ID_RE, StorageError


def _error_code(err):
    response = getattr(err, "response", None) or {}
    return str(response.get("Error", {}).get("Code", ""))


class _Body:
    """File-like wrapper around an S3 response body (read/close/context manager)."""

    def __init__(self, body):
        self._body = body

    def read(self, amount=-1):
        return self._body.read(amount) if amount is not None and amount >= 0 else self._body.read()

    def close(self):
        with contextlib.suppress(Exception):
            self._body.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class S3Storage:
    name = "s3"

    def __init__(self, client, bucket, prefix="evidence/", sse=None, conditional=True, client_error=Exception):
        if not bucket:
            raise StorageError("S3 storage needs S3_BUCKET.")
        self.client, self.bucket, self.prefix = client, bucket, prefix
        self.sse, self.conditional, self.client_error = sse, conditional, client_error

    @classmethod
    def from_config(cls, config):
        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError as err:
            raise StorageError("S3 storage needs boto3: pip install boto3") from err
        client = boto3.client(
            "s3",
            endpoint_url=config.get("S3_ENDPOINT_URL") or None,
            aws_access_key_id=config.get("S3_ACCESS_KEY_ID") or None,
            aws_secret_access_key=config.get("S3_SECRET_ACCESS_KEY") or None,
            region_name=config.get("S3_REGION") or "us-east-1",
            verify=config.get("S3_VERIFY_TLS", True),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          retries={"max_attempts": 3, "mode": "standard"}),
        )
        return cls(client, config.get("S3_BUCKET"), config.get("S3_PREFIX", "evidence/"),
                   config.get("S3_SSE") or None, config.get("S3_CONDITIONAL_WRITES", True),
                   client_error=(ClientError, BotoCoreError))

    @property
    def container(self):
        return f"s3://{self.bucket}/{self.prefix}"

    def _key(self, object_id):
        if not OBJECT_ID_RE.match(object_id or ""):
            raise StorageError("Invalid stored-file identifier.")
        return self.prefix + object_id

    # -- writing ---------------------------------------------------------------
    def put(self, stream, max_bytes):
        return self.put_as(str(uuid.uuid4()), stream, max_bytes)

    def put_as(self, object_id, stream, max_bytes):
        key = self._key(object_id)
        digest, size = hashlib.sha256(), 0
        with tempfile.TemporaryFile() as spool:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise StorageError(f"Evidence files must be {max_bytes / (1024 * 1024):g} MB or smaller.")
                digest.update(chunk)
                spool.write(chunk)
            if size == 0:
                raise StorageError("The file is empty.")
            spool.seek(0)
            args = {"Bucket": self.bucket, "Key": key, "Body": spool, "ContentLength": size,
                    "ContentType": "application/octet-stream"}
            if self.conditional:
                args["IfNoneMatch"] = "*"                        # write-once: never replace an object
            if self.sse:
                args["ServerSideEncryption"] = self.sse
            try:
                self.client.put_object(**args)
            except self.client_error as err:
                if _error_code(err) in ("PreconditionFailed", "412"):
                    raise StorageError("An object with this identifier already exists; it was not replaced.") from err
                raise StorageError(f"Object storage refused the upload ({_error_code(err) or 'error'}).") from err
        return object_id, size, digest.hexdigest()

    # -- reading ---------------------------------------------------------------
    def open_read(self, object_id):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(object_id))
        except self.client_error as err:
            if _error_code(err) in ("NoSuchKey", "404", "NotFound"):
                raise StorageError("The stored file is missing from object storage.") from err
            raise StorageError(f"Object storage couldn't be read ({_error_code(err) or 'error'}).") from err
        return _Body(response["Body"])

    def sha256(self, object_id):
        digest, size = hashlib.sha256(), 0
        with self.open_read(object_id) as body:
            while True:
                chunk = body.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        return digest.hexdigest(), size

    def exists(self, object_id):
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(object_id))
            return True
        except self.client_error as err:
            if _error_code(err) in ("NoSuchKey", "404", "NotFound"):
                return False
            raise StorageError(f"Object storage couldn't be checked ({_error_code(err) or 'error'}).") from err

    @contextlib.contextmanager
    def materialize(self, object_id):
        """Download to a temporary, read-only local file for an isolated worker
        (YARA); the copy is deleted afterwards."""
        handle, path = tempfile.mkstemp(prefix="forgex-scan-")
        try:
            with os.fdopen(handle, "wb") as out, self.open_read(object_id) as body:
                while True:
                    chunk = body.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
            os.chmod(path, stat.S_IREAD)
            yield path
        finally:
            with contextlib.suppress(OSError):
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
                os.remove(path)

    def local_path(self, object_id):
        raise StorageError("Objects in object storage have no local path; use materialize().")

    # -- cleanup and health ------------------------------------------------------
    def discard_unrecorded(self, object_id):
        """Remove an object whose database record could NOT be created."""
        with contextlib.suppress(self.client_error):
            self.client.delete_object(Bucket=self.bucket, Key=self._key(object_id))

    def health(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except self.client_error as err:
            return False, f"bucket {self.bucket!r} not reachable ({_error_code(err) or 'error'})"
        message = f"{self.container}"
        try:
            status = self.client.get_bucket_policy_status(Bucket=self.bucket)
            if status.get("PolicyStatus", {}).get("IsPublic"):
                return False, f"{message}: the bucket policy is PUBLIC. Evidence buckets must be private."
        except self.client_error:
            pass                                                # no policy, or not supported by this server
        return True, message + (", server-side encryption " + self.sse if self.sse else "")
