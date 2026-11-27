#!/usr/bin/env bash
# Generate demo certificates for the TLS demo target Postgres (profile tls-demo).
# Idempotent: every run overwrites everything in scripts/tls/certs/.
# Output: CA (ca.crt/ca.key), server cert with demo SANs, client cert (mTLS
# identity of the backend), plus a copy of pg_hba.conf for the container mount.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CERTS="$DIR/certs"
mkdir -p "$CERTS"

# 1) Demo CA — self-signed, valid 10 years.
#    MSYS2_ARG_CONV_EXCL stops Git Bash/MSYS2 from rewriting the "/CN=..."
#    subject into a Windows path; the var is ignored on Linux/macOS.
MSYS2_ARG_CONV_EXCL='/CN' openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERTS/ca.key" -out "$CERTS/ca.crt" \
  -days 3650 -subj "/CN=SemanticLayer Demo CA"

# 2) Server key + CSR signed by the CA. SANs cover every address the demo
#    connects through (host machine, container name, loopback).
MSYS2_ARG_CONV_EXCL='/CN' openssl req -newkey rsa:2048 -nodes \
  -keyout "$CERTS/server.key" -out "$CERTS/server.csr" \
  -subj "/CN=target-postgres-tls" \
  -addext "subjectAltName=DNS:localhost,DNS:target-postgres-tls,DNS:host.docker.internal,IP:127.0.0.1"
cat > "$CERTS/san.ext" <<'EOF'
subjectAltName=DNS:localhost,DNS:target-postgres-tls,DNS:host.docker.internal,IP:127.0.0.1
EOF
openssl x509 -req -in "$CERTS/server.csr" -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" \
  -CAcreateserial -days 3650 -out "$CERTS/server.crt" -extfile "$CERTS/san.ext"

# 3) Client key + CSR signed by the same CA — the backend's mTLS identity
MSYS2_ARG_CONV_EXCL='/CN' openssl req -newkey rsa:2048 -nodes \
  -keyout "$CERTS/client.key" -out "$CERTS/client.csr" \
  -subj "/CN=semantic-layer-backend"
openssl x509 -req -in "$CERTS/client.csr" -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" \
  -CAcreateserial -days 3650 -out "$CERTS/client.crt"

# The container mounts certs/ read-only and points hba_file at /certs/pg_hba.conf,
# so the tracked pg_hba.conf must be copied next to the generated certs.
cp "$DIR/pg_hba.conf" "$CERTS/pg_hba.conf"

# Housekeeping: CSRs, SAN file and serial file are byproducts
rm -f "$CERTS/server.csr" "$CERTS/client.csr" "$CERTS/san.ext" "$CERTS/ca.srl"
chmod 600 "$CERTS"/*.key

echo "Certificates written to $CERTS:"
ls -1 "$CERTS"
