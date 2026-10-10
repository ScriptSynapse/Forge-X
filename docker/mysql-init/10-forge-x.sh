#!/bin/bash
# Runs ONCE, on the MySQL container's first start (empty data volume), via
# /docker-entrypoint-initdb.d. Builds forge_x_db from the project's own SQL
# files (mounted read-only at /forge-x-db) and creates the application account.
#
# Works whether the entrypoint sources this file (not executable, e.g. a Windows
# checkout) or executes it: everything runs in a subshell with its own options,
# and the mysql client is called directly over the init server's socket.
(
  set -euo pipefail
  : "${FORGE_X_DB_APP_PASSWORD:?FORGE_X_DB_APP_PASSWORD must be set}"
  case "$FORGE_X_DB_APP_PASSWORD$MYSQL_ROOT_PASSWORD" in
    *change-me*) echo "FORGE-X: refusing to start with the example passwords from .env.docker.example" >&2; exit 1;;
  esac
  run_sql() { mysql --protocol=socket -uroot --password="$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4; }
  echo "FORGE-X: building forge_x_db"
  for f in schema triggers views procedures seed_reference; do
    echo "FORGE-X:   ${f}.sql"
    run_sql < "/forge-x-db/${f}.sql"
  done
  echo "FORGE-X: creating the application account (forge_x_app@'%', least privilege)"
  sh /forge-x-docker/app-user.sh forge_x_db '%' "$FORGE_X_DB_APP_PASSWORD" /forge-x-db/app_user.sql | run_sql
  echo "FORGE-X: database ready"
)
