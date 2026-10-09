"""FORGE-X 2.0 Phase 3: the evidence storage layer, tested on a real temporary folder (no MySQL)."""
import hashlib
import io
import os
import stat

import pytest

from app.storage import LocalStorage, StorageError


@pytest.fixture
def store(tmp_path):
    return LocalStorage(tmp_path)


def _files(root):
    return sum(len(names) for _, _, names in os.walk(root))


def test_put_hashes_while_writing_and_makes_the_file_read_only(store, tmp_path):
    data = b"synthetic evidence " * 100_000                  # several 1 MiB chunks
    object_id, size, sha256 = store.put(io.BytesIO(data), 10 * 1024 * 1024)
    assert (size, sha256) == (len(data), hashlib.sha256(data).hexdigest())
    path = tmp_path / object_id[:2] / object_id
    assert path.exists() and not os.stat(path).st_mode & stat.S_IWUSR
    assert store.sha256(object_id) == (sha256, size)


def test_every_object_gets_a_new_identifier(store):
    ids = {store.put(io.BytesIO(b"same content"), 1024)[0] for _ in range(5)}
    assert len(ids) == 5                                       # never overwrites, even for identical content


@pytest.mark.parametrize("payload,limit,message", [(b"x" * 2048, 1024, "or smaller"), (b"", 1024, "empty")])
def test_refused_uploads_leave_nothing_behind(store, tmp_path, payload, limit, message):
    with pytest.raises(StorageError, match=message):
        store.put(io.BytesIO(payload), limit)
    assert _files(tmp_path) == 0


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a" * 36, "", "ABCDEF00-0000-0000-0000-000000000000"])
def test_crafted_identifiers_are_refused(store, bad):
    with pytest.raises(StorageError):
        store.open_read(bad)


def test_tampering_on_disk_is_detected_by_rehashing(store, tmp_path):
    object_id, _, sha256 = store.put(io.BytesIO(b"original bytes"), 1024)
    path = tmp_path / object_id[:2] / object_id
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    path.write_bytes(b"changed bytes")
    assert store.sha256(object_id)[0] != sha256


def test_missing_file_and_cleanup(store):
    object_id, _, _ = store.put(io.BytesIO(b"to be discarded"), 1024)
    store.discard_unrecorded(object_id)
    with pytest.raises(StorageError, match="missing"):
        store.open_read(object_id)
    assert store.health()[0]
