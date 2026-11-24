#!/usr/bin/env bash
# TLS demo smoke test — run by hand during the defense demo. NOT part of pytest.
#
# Prereqs:
#   bash scripts/tls/gen_certs.sh
#   docker compose -f infra/docker-compose.dev.yml --profile tls-demo up -d target-postgres-tls
#
# 3 checks (PASS = matches expectation):
#   1. sslmode=verify-full + client cert      -> must connect (TLS + mTLS OK)
#   2. wrong CA (sslrootcert=server.crt)      -> must fail (client rejects server)
#   3. verify-full without a client cert      -> must fail (hba clientcert=verify-ca)
#
# All checks connect as host=target-postgres-tls so they take the hostssl hba
# line (mTLS path); loopback 127.0.0.1 would match the "trust" line instead.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f infra/docker-compose.dev.yml --profile tls-demo)
DSN='host=target-postgres-tls port=5432 user=demo dbname=demo_shop password=demo123'
FAILED=0

try_connect() { # $1 = full libpq connstring; succeeds when psql exits 0
  "${COMPOSE[@]}" exec -T target-postgres-tls psql "$1" -c 'SELECT 1' >/dev/null 2>&1
}

# Precondition: server must be up and reachable. Without this, a dead server
# makes checks 2-3 "pass" spuriously (a connection failure looks like a
# rejection). Keys live in /certs-sec (named volume) because Windows bind-mounts
# cannot hold the 0600 perms libpq/postgres require.
if ! try_connect "$DSN sslmode=require sslrootcert=/certs/ca.crt sslcert=/certs/client.crt sslkey=/certs-sec/client.key"; then
  echo "ABORT: target-postgres-tls is not reachable — check container logs first:"
  echo '  docker compose -f infra/docker-compose.dev.yml --profile tls-demo logs target-postgres-tls'
  exit 1
fi

if try_connect "$DSN sslmode=verify-full sslrootcert=/certs/ca.crt sslcert=/certs/client.crt sslkey=/certs-sec/client.key"; then
  echo "PASS 1/3  verify-full + client cert: connected (TLS, CA check, hostname check, mTLS)"
else
  echo "FAIL 1/3  verify-full + client cert: could NOT connect (expected success)"; FAILED=1
fi

if try_connect "$DSN sslmode=verify-full sslrootcert=/certs/server.crt sslcert=/certs/client.crt sslkey=/certs-sec/client.key"; then
  echo "FAIL 2/3  wrong CA (server.crt is not a CA): accepted (expected rejection)"; FAILED=1
else
  echo "PASS 2/3  wrong CA: rejected by the client (server identity not verifiable)"
fi

if try_connect "$DSN sslmode=verify-full sslrootcert=/certs/ca.crt"; then
  echo "FAIL 3/3  no client cert: accepted (expected mTLS rejection)"; FAILED=1
else
  echo "PASS 3/3  no client cert: rejected by the server (hba hostssl clientcert=verify-ca)"
fi

if [ "$FAILED" -ne 0 ]; then
  echo "SMOKE TEST: FAIL"
  exit 1
fi
echo "SMOKE TEST: PASS (3/3)"
