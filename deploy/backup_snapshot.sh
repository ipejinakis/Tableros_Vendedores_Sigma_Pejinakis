#!/usr/bin/env bash
# Copia de seguridad EN EL SERVIDOR (corre como root, por cron): objetivos y feriados editados desde la app (data/config),
# usuarios y auditoría. Deja una sola copia, siempre la última, en /home/administrador/backup-tablero (legible solo por
# administrador), para que la Mac la baje con scripts/admin/backup_desde_mac.sh. No toca nada de data/.
set -euo pipefail

ORIG="${TABLERO_DATA:-/opt/tableros-sigma/data}"
USUARIO="${BACKUP_USUARIO:-administrador}"
DEST="/home/$USUARIO/backup-tablero"
TMP="$DEST.nuevo"

# Si no está lo esencial, no se pisa la copia buena con una vacía.
[ -f "$ORIG/auth/usuarios.json" ] || { echo "No encuentro $ORIG/auth/usuarios.json: no toco la copia anterior." >&2; exit 1; }

rm -rf "$TMP"
mkdir -p "$TMP/config" "$TMP/auth"
[ -d "$ORIG/config" ] && cp -a "$ORIG/config/." "$TMP/config/"
for f in usuarios.json auditoria.log; do          # sin sesiones.json: las sesiones no se respaldan
  [ -f "$ORIG/auth/$f" ] && cp -a "$ORIG/auth/$f" "$TMP/auth/"
done
date -u +%Y-%m-%dT%H:%M:%SZ > "$TMP/hecho_en_utc.txt"
chown -R "$USUARIO:$USUARIO" "$TMP"
chmod -R go-rwx "$TMP"

rm -rf "$DEST.anterior"
[ -d "$DEST" ] && mv "$DEST" "$DEST.anterior"
mv "$TMP" "$DEST"
rm -rf "$DEST.anterior"
echo "$(date -u +%FT%TZ) backup ok: $(find "$DEST" -type f | wc -l) archivos"
