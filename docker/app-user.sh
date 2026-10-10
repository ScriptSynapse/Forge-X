#!/bin/sh
# Print the SQL that creates FORGE-X's least-privilege application account for a
# server reached over the network (Docker, CI). Same role and grants as
# database/app_user.sql; only the user's host and the database name differ.
#
#   sh docker/app-user.sh <database> <host> <password> <path-to-app_user.sql>  | mysql ...
set -eu
DB="$1"; HOST="$2"; PW="$3"; SRC="$4"
case "$PW" in *"'"*|*'\'*|"") echo "app-user.sh: the password must be non-empty and contain no quote or backslash" >&2; exit 1;; esac
case "$DB" in *[!a-z0-9_]*|"") echo "app-user.sh: bad database name" >&2; exit 1;; esac
echo "CREATE ROLE IF NOT EXISTS 'forge_x_app_role';"
# Every role grant from app_user.sql, pointed at the chosen database.
grep -E "^GRANT .* ON forge_x_db\..* TO 'forge_x_app_role';" "$SRC" | sed "s/forge_x_db\./${DB}./"
echo "CREATE USER IF NOT EXISTS 'forge_x_app'@'${HOST}' IDENTIFIED BY '${PW}';"
echo "GRANT 'forge_x_app_role' TO 'forge_x_app'@'${HOST}';"
echo "SET DEFAULT ROLE 'forge_x_app_role' TO 'forge_x_app'@'${HOST}';"
