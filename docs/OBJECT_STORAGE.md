# FORGE-X Object Storage (FORGE-X 2.0 Phase 9)

FORGE-X stores evidence files on **local disk** by default (`EVIDENCE_STORAGE_DIR`). Optionally, it can use an **S3-compatible object store**: MinIO on your own machine, or AWS S3. Metadata always stays in MySQL. Nothing about the evidence records changes.

## 1. How it works

* **Two backends, one interface** (`app/storage/`): `LocalStorage` and `S3Storage`.
* **New files:** `EVIDENCE_STORAGE_BACKEND` (`local` or `s3`) decides where new files go.
* **Existing files** are read from where they actually are. Every placement is a row in **`evidence_file_locations`**, which is append-only; a file's latest row is its current location. Files stored before Phase 9 have no row, so they're local.
* **The same guarantees on both backends:**
  * generated UUID object names;
  * **write-once**: exclusive create on disk, a conditional write (`If-None-Match: *`) on S3;
  * the SHA-256 is computed while the file arrives;
  * the size limit is enforced before anything is stored.
* **Private:** FORGE-X never creates public or presigned URLs. Downloads stream through FORGE-X, so they keep the permission check, the *Exported* custody entry and the audit row. `flask check-db` fails if the bucket policy is public.
* **YARA:** objects in S3 are downloaded to a read-only temporary file for the isolated worker, and deleted afterwards.
* **Encryption:** optional server-side encryption via `S3_SSE` (for example `AES256`).

## 2. Setting up MinIO (local) or S3

1. **Install boto3:** `pip install boto3` (it's in `requirements.txt`).
2. **Run an S3-compatible server.** For MinIO, follow its own installation instructions. It usually listens on `http://127.0.0.1:9000`.
3. **Create a bucket**, for example `forgex-evidence`. **Keep it private**: no anonymous or public policy. Enable versioning and object locking if your server supports them; they add protection on top of FORGE-X's own write-once rule.
4. **Create an access key** limited to that bucket. FORGE-X needs only:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        "Resource": "arn:aws:s3:::forgex-evidence/evidence/*"},
       {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketPolicyStatus"],
        "Resource": "arn:aws:s3:::forgex-evidence"}
     ]
   }
   ```
   `DeleteObject` is used **only** to remove an upload whose database record could not be created, and a copy that failed verification. FORGE-X never deletes recorded evidence.
5. **Set `.env`:**
   ```
   EVIDENCE_STORAGE_BACKEND=s3
   S3_ENDPOINT_URL=http://127.0.0.1:9000      (leave empty for AWS S3)
   S3_BUCKET=forgex-evidence
   S3_ACCESS_KEY_ID=…
   S3_SECRET_ACCESS_KEY=…
   S3_SSE=                                    (AES256 if the server supports it)
   ```
6. **Check:** `flask --app run check-db` should pass *Object storage for new evidence files (S3)*. Then `pytest tests\test_storage_s3.py` with `set FORGE_X_S3_TESTS=1` runs a real round trip against the bucket.

## 3. Migrating existing files

```cmd
flask --app run storage-status
flask --app run storage-migrate --to s3 --by paulson --dry-run
flask --app run storage-migrate --to s3 --by paulson
flask --app run storage-status
```

For each file not yet on the target, the tool:

1. **Hashes the source copy.** It must equal the SHA-256 recorded when the file was stored. If not, the file is **not moved**; that's reported and audited, and you should verify the item.
2. **Copies it** to the target under the same object ID, write-once. If a verified copy is already there, it isn't copied again.
3. **Hashes the copy.** On a mismatch, the copy is removed and nothing is recorded.
4. **Records the new location**, with the SHA-256 before and after, plus an `evidence.storage_move` audit row. MySQL refuses a location row whose two hashes differ.

**The source copy is never deleted.** A migration that stops halfway leaves every file readable from wherever its latest location row points. `--dry-run` checks every source hash and copies nothing. `--limit N` moves a batch.

## 4. Rolling back

Run the same command towards the other backend:

```cmd
flask --app run storage-migrate --to local --by paulson
```

Because the local copies were never deleted, each file is verified in place (*"verified copy already present"*) and a new location row points back to local. Then set `EVIDENCE_STORAGE_BACKEND=local` so new files go to local disk again.

## 5. Deleting the old copies (optional, manual)

FORGE-X never deletes evidence copies. Once you're satisfied with the migration, have run `pytest` (which includes `test_stored_files_match_a_recorded_hash_and_exist` against each file's current backend), and have backed up the bucket, an administrator *may* remove old local copies by hand. **Rollback then needs a copy back from S3, which the same command does, with the same verification.**

## 6. Backups

Back up MySQL **and** wherever your files are: the `EVIDENCE_STORAGE_DIR` folder and/or the bucket. Each is incomplete without the other.
