# ---------------------------------------------------------------------------
# Genera un certificado TLS autofirmado para la intranet del HTQPJB (Windows).
# Salida: nginx\certs\sgcm.crt y nginx\certs\sgcm.key
#
# Requiere openssl en el PATH (viene con Git for Windows en
# C:\Program Files\Git\usr\bin\openssl.exe, o instalable con `winget install
# ShiningLight.OpenSSL`).
#
# Uso (desde la raíz del repo):
#   .\scripts\gen-cert.ps1                  # CN=sgcm.intranet
#   .\scripts\gen-cert.ps1 -HostName 10.0.0.15  # CN/SAN = esa IP
#   .\scripts\gen-cert.ps1 -HostName sgcm.hospital
# ---------------------------------------------------------------------------
param(
    [string]$HostName = "sgcm.intranet"
)
$ErrorActionPreference = "Stop"

$certDir = Join-Path (Split-Path $PSScriptRoot -Parent) "nginx\certs"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

if ($HostName -match '^\d+\.\d+\.\d+\.\d+$') {
    $san = "IP:$HostName,DNS:localhost,IP:127.0.0.1"
} else {
    $san = "DNS:$HostName,DNS:localhost,IP:127.0.0.1"
}

openssl req -x509 -newkey rsa:2048 -nodes `
  -keyout "$certDir\sgcm.key" `
  -out    "$certDir\sgcm.crt" `
  -days 825 `
  -subj "/C=DO/ST=La Vega/L=La Vega/O=HTQPJB/CN=$HostName" `
  -addext "subjectAltName=$san"

Write-Host "[OK] Certificado generado en $certDir (CN=$HostName, SAN=$san)"
Write-Host "     Reinicia Nginx:  docker compose restart nginx"
