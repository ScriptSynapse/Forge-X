"""FORGE-X 2.0 Phase 9: the S3 backend and the verified migration tool (no MySQL, no S3 server:
an in-memory stand-in for the boto3 client). A real MinIO/S3 test is at the end (opt-in)."""
import contextlib
import hashlib
import io
import os
import stat

import pytest

from app.storage import LocalStorage, StorageError
from app.storage import migrate as mig
from app.storage.s3 import S3Storage
from tests._fake_s3 import FakeClientError, FakeS3


def _s3(client=None, bucket="evidence", **kw):
    return S3Storage(client or FakeS3(), bucket, client_error=FakeClientError, **kw)


def test_s3_put_hashes_and_writes_once_with_encryption():
    client = FakeS3()
    st = _s3(client, sse="AES256")
    data = b"synthetic evidence " * 50_000
    oid, size, sha = st.put(io.BytesIO(data), 10 * 1024 * 1024)
    assert (size, sha) == (len(data), hashlib.sha256(data).hexdigest()) and st.sha256(oid) == (sha, size)
    assert client.calls[-1][2:] == ("*", "AES256")                      # conditional write + SSE on every put
    with pytest.raises(StorageError, match="already exists"):
        st.put_as(oid, io.BytesIO(b"replacement"), 1024)
    assert client.objects["evidence/" + oid] == data


@pytest.mark.parametrize("payload,limit,message", [(b"x" * 2048, 1024, "or smaller"), (b"", 1024, "empty")])
def test_s3_refused_uploads_never_reach_the_bucket(payload, limit, message):
    client = FakeS3()
    with pytest.raises(StorageError, match=message):
        _s3(client).put(io.BytesIO(payload), limit)
    assert client.objects == {}


def test_s3_materialize_is_read_only_and_temporary():
    st = _s3()
    oid, _, _ = st.put(io.BytesIO(b"scan me"), 1024)
    with st.materialize(oid) as path:
        assert open(path, "rb").read() == b"scan me" and not os.stat(path).st_mode & stat.S_IWUSR
    assert not os.path.exists(path)
    for bad in ("../../x", "A" * 36, ""):
        with pytest.raises(StorageError):
            st.open_read(bad)


def test_s3_health_reports_public_or_missing_buckets():
    assert _s3().health()[0]
    assert not _s3(FakeS3(public=True)).health()[0]
    assert not _s3(bucket="missing").health()[0]
    with pytest.raises(StorageError):
        _s3(bucket="")


def test_storage_backend_setting_is_validated(monkeypatch):
    from app.config import Config
    monkeypatch.setenv("EVIDENCE_STORAGE_BACKEND", "ftp")
    with pytest.raises(RuntimeError):
        Config()
    monkeypatch.setenv("EVIDENCE_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "")
    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        Config()


@pytest.fixture
def migration(app, tmp_path, monkeypatch):
    """Real local storage in tmp_path, the S3 stand-in, and a fake database."""
    local, client = LocalStorage(tmp_path), FakeS3()
    monkeypatch.setitem(app.config, "EVIDENCE_STORAGE_DIR", str(tmp_path))
    files = []
    for i, data in enumerate((b"file one", b"file two", b"file three"), 1):
        oid, size, sha = local.put(io.BytesIO(data), 1024)
        files.append({"file_id": i, "object_id": oid, "sha256": sha, "size_bytes": size,
                      "evidence_code": f"FX-EV-2026-0000{i}", "backend": "local"})
    rows, audits = [], []

    class Cursor:
        def execute(self, sql, params=()):
            rows.append(params)
            files[params[0] - 1]["backend"] = params[1]

    @contextlib.contextmanager
    def fake_transaction():
        yield Cursor()

    monkeypatch.setattr(mig, "get_storage", lambda name=None: local if name in (None, "local") else _s3(client))
    monkeypatch.setattr(mig, "status", lambda: [dict(f) for f in files])
    monkeypatch.setattr(mig, "transaction", fake_transaction)
    monkeypatch.setattr(mig.audit, "record", lambda *a, **k: audits.append((a[2], k.get("outcome", "Success"))))

    def run(target, **kw):
        with app.app_context():
            return mig.migrate(target, 1, log=lambda *_: None, **kw)
    return {"run": run, "files": files, "rows": rows, "audits": audits, "local": local, "client": client, "dir": tmp_path}


def test_migration_verifies_records_and_keeps_the_source(migration):
    m = migration
    damaged = m["dir"] / m["files"][1]["object_id"][:2] / m["files"][1]["object_id"]
    os.chmod(damaged, stat.S_IREAD | stat.S_IWRITE)
    with open(damaged, "ab") as f:
        f.write(b"!")
    # A dry run already checks source hashes (and reports the damaged one) but copies and records nothing.
    assert m["run"]("s3", dry_run=True) == {"moved": 0, "already_there": 0, "skipped": 1, "failed": 0}
    assert m["rows"] == [] and m["client"].objects == {}
    counts = m["run"]("s3")
    assert counts == {"moved": 2, "already_there": 0, "skipped": 1, "failed": 0}
    assert all(r[3] == r[4] for r in m["rows"])                          # hash before == after
    assert "evidence/" + m["files"][1]["object_id"] not in m["client"].objects   # damaged source not copied
    assert all(m["local"].exists(f["object_id"]) for f in m["files"])     # sources never deleted
    assert ("FX-EV-2026-00002", "Failure") in m["audits"]
    m["rows"].clear()
    assert m["run"]("local")["already_there"] == 2 and len(m["rows"]) == 2   # rollback: verified, nothing copied


def test_migration_never_overwrites_or_keeps_a_bad_copy(migration):
    m = migration
    conflict = "evidence/" + m["files"][0]["object_id"]
    m["client"].objects[conflict] = b"something else"
    original = m["client"].put_object

    def corrupting_put(**kw):                                              # the copy gets damaged in transit
        data = kw.pop("Body").read() + b"corrupted"
        kw["ContentLength"] = len(data)
        original(Body=io.BytesIO(data), **kw)
    m["client"].put_object = corrupting_put
    counts = m["run"]("s3")
    assert counts["moved"] == 0 and counts["failed"] == 3 - counts["skipped"]
    assert m["client"].objects == {conflict: b"something else"}            # conflict untouched, bad copies removed
    assert m["rows"] == []


# --- a real S3 / MinIO server (opt-in) ---------------------------------------------------
REAL = os.getenv("FORGE_X_S3_TESTS") == "1"


@pytest.mark.skipif(not REAL, reason="set FORGE_X_S3_TESTS=1 with S3_* settings to test against a real MinIO/S3 bucket")
def test_real_s3_round_trip(app):
    st = S3Storage.from_config(app.config)
    ok, message = st.health()
    assert ok, message
    data = os.urandom(256 * 1024)
    oid, size, sha = st.put(io.BytesIO(data), 1024 * 1024)
    try:
        assert st.sha256(oid) == (sha, size) and st.exists(oid)
        with st.open_read(oid) as body:
            assert body.read() == data
        if app.config.get("S3_CONDITIONAL_WRITES", True):
            with pytest.raises(StorageError, match="already exists"):
                st.put_as(oid, io.BytesIO(b"replacement"), 1024)
        with st.materialize(oid) as path:
            assert hashlib.sha256(open(path, "rb").read()).hexdigest() == sha
    finally:
        st.discard_unrecorded(oid)                                           # test object only
    assert not st.exists(oid)
