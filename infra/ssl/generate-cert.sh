#!/bin/bash
# Generate a self-signed SSL certificate for IP 10.41.31.20
# Valid for 365 days. Re-run this script to regenerate.

set -e

CERT_DIR="$(cd "$(dirname "$0")" && pwd)"
IP_ADDR="10.41.31.20"

echo "Generating self-signed SSL certificate for IP: $IP_ADDR"

# Generate private key and certificate in one step
openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout "$CERT_DIR/selfsigned.key" \
  -out "$CERT_DIR/selfsigned.crt" \
  -subj "/C=US/ST=Missouri/O=Emerson/CN=$IP_ADDR" \
  -addext "subjectAltName=IP:$IP_ADDR" \
  -addext "basicConstraints=CA:TRUE"

chmod 600 "$CERT_DIR/selfsigned.key"
chmod 644 "$CERT_DIR/selfsigned.crt"

echo "Certificate generated:"
echo "  Key:  $CERT_DIR/selfsigned.key"
echo "  Cert: $CERT_DIR/selfsigned.crt"
echo ""
echo "To verify: openssl x509 -in $CERT_DIR/selfsigned.crt -text -noout"
