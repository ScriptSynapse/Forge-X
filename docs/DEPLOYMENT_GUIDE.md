# FORGE-X Deployment Guide

Three ways to run FORGE-X:

| Option | Best for | Section |
|---|---|---|
| **Docker Compose** | A clean, repeatable install on any machine with Docker | 1 |
| **Windows, without Docker** | Development and the viva demonstration (the original setup) | 2 |
| **Public access through Cloudflare Tunnel** | Showing FORGE-X to someone outside your network | 3 |

All data in FORGE-X is synthetic. It's an academic project, not a certified forensic tool.

---

## 1. Docker Compose

### What runs

| Service | Image | Network | Reachable from your machine |
|---|---|---|---|
| `app` | built from `Dockerfile` | `frontend` + `backend` | `http://127.0.0.1:8000` only |
| `db` | `mysql:8.4` | `backend` (internal) | **No** |
| `minio`, `minio-init` (optional, `--profile s3`) | `cgr.dev/chainguard/minio`, `minio-client` | `backend` (internal) | **No** |

**Network isolation:**
* `backend` is an *internal* network: no published ports and no route to the internet.
* The app is the only service on `frontend`, and its port is published on `127.0.0.1` only, not to your local network.

**Hardening of the app container:**
* runs as a non-root user (`forgex`);
* read-only root filesystem: only the evidence volume and `/tmp` are writable;
* all Linux capabilities dropped, and `no-new-privileges` set.

**The YARA worker** isn't a separate service. FORGE-X starts it as a restricted child process for each scan, inside the app container.

### First start

```cmd
copy .env.docker.example .env.docker
```

Edit `.env.docker` and change **every** value:

* `FORGE_X_SECRET_KEY`: generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.
* The database passwords: letters, digits and `- _ .` only.

The example values are refused, both by the app and by the database setup.

```cmd
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker exec app flask --app run create-admin paulson
docker compose --env-file .env.docker exec app flask --app run check-db
```

**What happens on the first start:**
1. MySQL runs `docker/mysql-init/10-forge-x.sh`. It builds `forge_x_db` from `database/*.sql` and creates the least-privilege account `forge_x_app@'%'`, with exactly the role grants in `database/app_user.sql`.
2. The app waits until the database health check passes. That check logs in **as the application account** over TCP, so it can't pass before the setup has finished.

Open http://127.0.0.1:8000 and log in as the administrator you created. Optionally, run `exec app flask --app run seed-mock` to add the demonstration data.

### Optional: MinIO object storage

In `.env.docker`, set `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` (letters and digits) and `EVIDENCE_STORAGE_BACKEND=s3`. Then add `--profile s3` to every command:

```cmd
docker compose --env-file .env.docker --profile s3 up -d --build
docker compose --env-file .env.docker --profile s3 exec app flask --app run check-db
```

* `minio-init` creates the bucket once, with versioning. New buckets are private, and FORGE-X never makes them public.
* **Image choice:** MinIO stopped publishing its free `minio/minio` image in October 2025, so the Compose file uses Chainguard's free, maintained MinIO images.
* **Migrating files** between local storage and MinIO: [OBJECT_STORAGE.md](OBJECT_STORAGE.md).

### Data, backups and restore

| Volume | Holds |
|---|---|
| `forge-x_mysql-data` | The database |
| `forge-x_evidence-files` | Stored evidence files (local backend) |
| `forge-x_minio-data` | MinIO objects (with `--profile s3`) |

**Back up the database and the evidence files together.** Each is incomplete without the other.

```cmd
docker compose --env-file .env.docker exec -T db sh -c "mysqldump -uroot -p\"$MYSQL_ROOT_PASSWORD\" --single-transaction --routines --triggers forge_x_db" > forge_x_db.sql
docker run --rm -v forge-x_evidence-files:/data -v "%cd%":/backup alpine tar czf /backup/evidence-files.tgz -C /data .
```

To restore, pipe the dump back with `exec -T db sh -c "mysql -uroot -p\"$MYSQL_ROOT_PASSWORD\" forge_x_db" < forge_x_db.sql`, and untar into the volume. Then run `check-db` and `pytest`. The consistency tests check that every recorded file exists and still matches its hash.

`docker compose down` keeps the volumes. **`down -v` deletes them**, including all evidence.

### Upgrading

1. Back up (above).
2. Pull the new code, then run `docker compose --env-file .env.docker up -d --build`.
3. **The MySQL setup script only runs on an empty volume.** For an existing database, apply each new migration once:
   ```cmd
   docker compose --env-file .env.docker exec -T db sh -c "mysql -uroot -p\"$MYSQL_ROOT_PASSWORD\"" < database/migrations/0NN_name.sql
   ```
   A new migration that grants privileges to `forge_x_app_role` applies to `forge_x_app@'%'` automatically.
4. Run `exec app flask --app run check-db`. It names any migration that's still missing.

Migrations are additive. There's no automatic migration on start-up, on purpose: a migration is run deliberately, after a backup.

---

## 2. Windows, without Docker

The original setup: Python virtual environment, MySQL 8 service and `.env`. Follow **Setup on Windows** in the [README](../README.md). The production server is `python serve.py` (Waitress); `flask --app run run` is for development only.

---

## 3. Public access through Cloudflare Tunnel

See [DEPLOY_CLOUDFLARE.md](DEPLOY_CLOUDFLARE.md). Use it with the **Windows setup**: FORGE-X then listens on `127.0.0.1`, which is what `TRUST_CLOUDFLARE=1` requires.

**With Docker, keep `TRUST_CLOUDFLARE=0`.** Inside a container the app listens on `0.0.0.0`, so it can't prove that only the tunnel reaches it, and `serve.py` refuses that combination. The tunnel still works, but every visitor appears with the tunnel's address, which weakens the per-address login limits.

Before going public:
* `FLASK_DEBUG=0`;
* `SESSION_COOKIE_SECURE=1`;
* real secrets;
* a recent backup.

Cloudflare's free plan limits uploads to 100 MB, which is why `EVIDENCE_MAX_MB` defaults to 100.

---

## 4. Continuous integration (GitHub Actions)

`.github/workflows/ci.yml` runs on every push and pull request. **It never deploys**, and needs no repository secrets, because every password is generated for that run.

| Job | What it does | Blocks on failure |
|---|---|---|
| Lint and format | `ruff`: syntax errors and undefined names block; full lint and formatting are advisory | Errors only |
| Tests on MySQL (Python 3.13 and 3.14) | Builds a throwaway `forge_x_test` database and the least-privilege account, creates an administrator, runs **every** test including the write tests through `tools/stability_report.py`, and uploads the generated stability report | Yes |
| Security checks | `pip-audit` (known vulnerabilities in dependencies) blocks; `bandit` static analysis is advisory, because SQL composition is already checked by `tests/test_security.py` | `pip-audit` |
| Docker build and smoke test | Validates the Compose file, builds and starts the stack, waits for every health check, runs `check-db`, confirms MySQL isn't reachable from the host, and tears everything down | Yes |

**To use it:** push the project to GitHub. The **Actions** tab shows the runs, and each test run's **stability report** is attached as an artifact.
