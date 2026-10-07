#!/usr/bin/env bash
# Corre en el SERVIDOR (Ubuntu), con sudo, después de deploy/subir.sh. Es idempotente: sirve para instalar y para actualizar.
#   sudo bash ~/tableros-sigma-deploy/code/deploy/instalar_en_servidor.sh
# Variables opcionales: APP_DIR (default /opt/tableros-sigma), PUERTO (default 8510), USUARIO_SERVICIO (default tableros).
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "Correr con sudo."; exit 1; }
APP_DIR="${APP_DIR:-/opt/tableros-sigma}"
PUERTO="${PUERTO:-8510}"
SVC_USER="${USUARIO_SERVICIO:-tableros}"
ORIGEN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"        # .../tableros-sigma-deploy/code
STAGE="$(dirname "$ORIGEN")"                                          # .../tableros-sigma-deploy
LOG_DIR=/var/log/tableros

echo "== Paquetes =="
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip rsync >/dev/null

echo "== Usuario de servicio ($SVC_USER, sin sudo ni shell) =="
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SVC_USER"
mkdir -p "$APP_DIR" "$LOG_DIR"

echo "== Código (no pisa data/, .env ni venv) =="
rsync -a --delete --exclude data --exclude .env --exclude venv "$ORIGEN"/ "$APP_DIR"/

echo "== Datos y .env (solo si se subieron con --con-datos / --con-env) =="
if [ -d "$STAGE/data" ]; then
  mkdir -p "$APP_DIR/data"
  rsync -a "$STAGE/data/" "$APP_DIR/data/"
  rm -rf "$STAGE/data"
  echo "   datos copiados"
fi
if [ -f "$STAGE/.env" ]; then
  mv "$STAGE/.env" "$APP_DIR/.env"
  echo "   .env instalado"
fi
[ -f "$APP_DIR/.env" ] || echo "   AVISO: falta $APP_DIR/.env (el ETL no va a andar hasta que lo subas con --con-env)."
mkdir -p "$APP_DIR/data/auth" "$APP_DIR/data/silver" "$APP_DIR/data/_meta"
# Producción: los datos se guardan en el servidor (ruta absoluta); el resto del .env queda como está
if [ -f "$APP_DIR/.env" ] && ! grep -q '^SIGMA_DATA_DIR=' "$APP_DIR/.env"; then echo "SIGMA_DATA_DIR=$APP_DIR/data" >> "$APP_DIR/.env"; fi

echo "== Entorno Python =="
[ -d "$APP_DIR/venv" ] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "== Permisos =="
chown -R "$SVC_USER":"$SVC_USER" "$APP_DIR" "$LOG_DIR"
chmod 700 "$APP_DIR/data"
[ -f "$APP_DIR/.env" ] && chmod 600 "$APP_DIR/.env"
find "$APP_DIR/data/auth" -type f -exec chmod 600 {} \; 2>/dev/null || true

echo "== Servicio systemd (127.0.0.1:$PUERTO) =="
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@PUERTO@|$PUERTO|g" -e "s|@SVC_USER@|$SVC_USER|g" \
    "$APP_DIR/deploy/tableros.service" > /etc/systemd/system/tableros.service
systemctl daemon-reload
systemctl enable tableros >/dev/null
systemctl restart tableros

echo "== Cron del ETL (06:00 completo, 16:00 solo ventas) y rotación de logs =="
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@SVC_USER@|$SVC_USER|g" "$APP_DIR/deploy/cron-tableros" > /etc/cron.d/tableros
chmod 644 /etc/cron.d/tableros
cp "$APP_DIR/deploy/logrotate-tableros" /etc/logrotate.d/tableros

sleep 3
echo
systemctl --no-pager --lines=0 status tableros | head -5 || true
echo "Escuchando:"; ss -ltn | grep ":$PUERTO " || echo "  (todavía no escucha: mirá 'journalctl -u tableros -n 50')"
echo "Zona horaria del servidor: $(timedatectl show -p Timezone --value 2>/dev/null || date +%Z)  (el cron usa esa hora; debería ser America/Argentina/Salta)"
echo
echo "Siguiente paso (acceso por Tailscale con HTTPS):"
echo "  sudo tailscale serve --bg --https=8443 http://127.0.0.1:$PUERTO"
echo "  tailscale serve status"
