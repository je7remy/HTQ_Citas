#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Genera un certificado TLS autofirmado para la intranet del HTQPJB.
# Salida: nginx/certs/sgcm.crt y nginx/certs/sgcm.key
#
# Uso:
#   ./scripts/gen-cert.sh                 # CN=sgcm.intranet por defecto
#   ./scripts/gen-cert.sh 10.0.0.15       # CN/SAN = esa IP del servidor
#   ./scripts/gen-cert.sh sgcm.hospital   # CN/SAN = ese hostname
#
# El cert dura 825 días (máximo aceptado por navegadores modernos para
# certificados sin CA pública). Regenerar antes de que expire.
# ---------------------------------------------------------------------------
set -euo pipefail

HOST="${1:-sgcm.intranet}"
CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/nginx/certs"
mkdir -p "$CERT_DIR"

# Si HOST parece IP, lo ponemos como IP en el SAN; si no, como DNS.
if [[ "$HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  SAN="IP:$HOST,DNS:localhost,IP:127.0.0.1"
else
  SAN="DNS:$HOST,DNS:localhost,IP:127.0.0.1"
fi

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERT_DIR/sgcm.key" \
  -out    "$CERT_DIR/sgcm.crt" \
  -days 825 \
  -subj "/C=DO/ST=La Vega/L=La Vega/O=HTQPJB/CN=$HOST" \
  -addext "subjectAltName=$SAN"

chmod 600 "$CERT_DIR/sgcm.key"
echo "[OK] Certificado generado en $CERT_DIR (CN=$HOST, SAN=$SAN)"
echo "     Reinicia Nginx:  docker compose restart nginx"
