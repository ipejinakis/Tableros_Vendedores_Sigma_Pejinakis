#!/usr/bin/env bash
# Corre en el SERVIDOR, con sudo. Instala `cloudflared` y lo deja como servicio conectado a TU túnel de Cloudflare.
# El token del túnel es un secreto: se pide por teclado (no se ve ni queda en el historial de la terminal).
#   ssh -t n8npeji 'sudo bash ~/tableros-sigma-deploy/code/deploy/instalar_cloudflared.sh'
# Es idempotente: si ya está instalado como servicio, avisa y no hace nada.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Correr con sudo."; exit 1; }

if systemctl list-unit-files | grep -q '^cloudflared.service'; then
  echo "cloudflared ya está instalado como servicio:"; systemctl --no-pager --lines=3 status cloudflared | head -6
  echo "Para cambiar de túnel: sudo cloudflared service uninstall  y volver a correr este script."
  exit 0
fi

echo "== Repositorio e instalación de cloudflared =="
apt-get install -y -qq curl gnupg >/dev/null
mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" > /etc/apt/sources.list.d/cloudflared.list
apt-get update -qq
apt-get install -y -qq cloudflared >/dev/null
cloudflared --version

echo
echo "Pegá el TOKEN del túnel (el texto largo que empieza con 'eyJ...' del comando de instalación de Cloudflare) y apretá Enter."
echo "No se muestra mientras lo pegás."
read -r -s TOKEN
[ -n "${TOKEN:-}" ] || { echo "Token vacío, abortado."; exit 1; }
cloudflared service install "$TOKEN"
unset TOKEN
sleep 4
systemctl --no-pager --lines=5 status cloudflared | head -10
echo
echo "Listo: el túnel sale desde este servidor hacia Cloudflare (no se abre ningún puerto)."
echo "Falta, en el panel de Cloudflare: el 'Public hostname' del túnel hacia http://localhost:8510 y la política de Access."
