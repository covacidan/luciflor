#!/bin/bash
# Runs once, on the first start of an empty Postgres volume.
# Creates a dedicated database + user for Keycloak, separate from the app database.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE USER "${KEYCLOAK_DB_USER}" WITH PASSWORD '${KEYCLOAK_DB_PASSWORD}';
  CREATE DATABASE "${KEYCLOAK_DB}" OWNER "${KEYCLOAK_DB_USER}";
EOSQL

# unaccent lets order search match "Stefan" to "Ștefan".
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "CREATE EXTENSION IF NOT EXISTS unaccent;"
