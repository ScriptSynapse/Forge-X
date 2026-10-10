"""FORGE-X 2.0 Phase 11: the deployment files keep their security properties (no Docker needed)."""
import pathlib
import re
import shutil
import subprocess

import pytest

# PyYAML is listed in requirements.txt. If it's missing, skip these tests with a clear reason
# instead of aborting collection of the whole suite.
yaml = pytest.importorskip("yaml", reason="PyYAML not installed: run pip install -r requirements.txt")

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
CI = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_database_and_object_store_are_never_published():
    services = COMPOSE["services"]
    for name in ("db", "minio", "minio-init"):
        assert "ports" not in services[name], f"{name} must not publish ports"
        assert services[name]["networks"] == ["backend"]
    assert COMPOSE["networks"]["backend"]["internal"] is True
    assert all(p.startswith("127.0.0.1:") for p in services["app"]["ports"])        # app: this machine only


def test_app_container_is_locked_down():
    app = COMPOSE["services"]["app"]
    assert app["read_only"] is True and "no-new-privileges:true" in app["security_opt"] and app["cap_drop"] == ["ALL"]
    assert app["depends_on"]["db"]["condition"] == "service_healthy"
    assert re.search(r"^USER forgex$", DOCKERFILE, re.M) and "HEALTHCHECK" in DOCKERFILE


def test_secrets_are_required_and_never_baked_into_the_image():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for var in ("FORGE_X_SECRET_KEY", "FORGE_X_DB_ROOT_PASSWORD", "FORGE_X_DB_APP_PASSWORD"):
        assert re.search(r"\$\{" + var + r":\?", text), f"{var} must be required"
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert ".env" in ignored and ".env.*" in ignored and "instance" in ignored
    assert ".env.docker" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()


def test_example_secrets_are_refused():
    from app.config import validate_config
    example = dict(line.split("=", 1) for line in (ROOT / ".env.docker.example").read_text(encoding="utf-8").splitlines()
                   if line and not line.startswith("#"))
    assert validate_config({"SECRET_KEY": example["FORGE_X_SECRET_KEY"], "TESTING": True})
    init = (ROOT / "docker" / "mysql-init" / "10-forge-x.sh").read_text(encoding="utf-8")
    assert "change-me" in init and "refusing" in init


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_network_app_user_gets_exactly_the_role_grants_of_app_user_sql():
    source = (ROOT / "database" / "app_user.sql").read_text(encoding="utf-8")
    expected = re.findall(r"^GRANT .* ON forge_x_db\..* TO 'forge_x_app_role';$", source, re.M)
    out = subprocess.run(["sh", str(ROOT / "docker" / "app-user.sh"), "forge_x_test", "%", "Pw_123-abc",
                          str(ROOT / "database" / "app_user.sql")], capture_output=True, text=True, check=True).stdout
    grants = [l for l in out.splitlines() if l.startswith("GRANT ") and "TO 'forge_x_app_role'" in l]
    assert grants == [g.replace("forge_x_db.", "forge_x_test.") for g in expected] and len(grants) > 30
    assert "DELETE ON forge_x_test.audit_logs" not in out and "ALL PRIVILEGES" not in out
    bad = subprocess.run(["sh", str(ROOT / "docker" / "app-user.sh"), "forge_x_db", "%", "x'; DROP USER root; --",
                          str(ROOT / "database" / "app_user.sql")], capture_output=True, text=True)
    assert bad.returncode != 0 and "DROP" not in bad.stdout


def test_ci_never_deploys_and_only_writes_to_a_throwaway_database():
    assert CI["permissions"] == {"contents": "read"}
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    commands = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert not re.search(r"\bdeploy|\bssh |\bscp |docker push|docker login|\$\{\{\s*secrets\.", commands, re.I)
    assert CI["jobs"]["test"]["env"]["MYSQL_DATABASE"] == "forge_x_test"
    assert "--with-write-tests" in text and "down -v" in text