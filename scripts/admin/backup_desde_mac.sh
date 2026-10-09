#!/usr/bin/env bash
# Baja a la Mac la última copia de seguridad del servidor (objetivos, feriados, usuarios y auditoría).
# Necesita Tailscale prendido. Deja SOLO la última copia en ~/Backups/tablero-sigma/ultima (se pisa cada vez).
#   bash scripts/admin/backup_desde_mac.sh            # baja la copia que dejó el cron de anoche
#   bash scripts/admin/backup_desde_mac.sh --fresca   # primero le pide al servidor una copia nueva (pide la clave de sudo)
set -euo pipefail

HOST="${BACKUP_HOST:-n8npeji}"
DEST="${BACKUP_DEST:-$HOME/Backups/tablero-sigma}"

if [ "${1:-}" = "--fresca" ]; then
  ssh -t "$HOST" 'sudo /usr/local/sbin/tablero-sigma-backup.sh'
fi

mkdir -p "$DEST/ultima"
chmod 700 "$DEST" "$DEST/ultima"
rsync -a --delete "$HOST:backup-tablero/" "$DEST/ultima/"
echo "Copia de seguridad en $DEST/ultima"
echo "Hecha en el servidor (UTC): $(cat "$DEST/ultima/hecho_en_utc.txt")"
echo "Archivos: $(find "$DEST/ultima" -type f | wc -l)"
