#!/usr/bin/env bash
# Instala (una sola vez) el backup diario en el servidor. Se corre con:
#   sudo bash ~/tableros-sigma-deploy/code/deploy/instalar_backup.sh
# Hace una copia ya mismo y la repite todos los días a las 23:00 UTC (20:00 de Salta).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correlo con sudo."; exit 1; }
AQUI="$(cd "$(dirname "$0")" && pwd)"
install -m 700 -o root -g root "$AQUI/backup_snapshot.sh" /usr/local/sbin/tablero-sigma-backup.sh
cat > /etc/cron.d/tablero-sigma-backup <<'CRON'
# Backup de data/config, usuarios y auditoría (hora UTC: 23:00 = 20:00 Salta)
0 23 * * * root /usr/local/sbin/tablero-sigma-backup.sh >> /var/log/tablero-sigma-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/tablero-sigma-backup
/usr/local/sbin/tablero-sigma-backup.sh
echo "Listo. Copia en /home/administrador/backup-tablero. Bajala a la Mac con: bash scripts/admin/backup_desde_mac.sh"
