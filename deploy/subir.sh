#!/usr/bin/env bash
# Corre en la MAC, desde la raíz del repo. Sube el código (último commit) y, si se pide, los datos y el .env al servidor.
# No instala nada: eso lo hace deploy/instalar_en_servidor.sh en el servidor.
#
# Uso:
#   bash deploy/subir.sh usuario@servidor                  # solo código (actualizaciones)
#   bash deploy/subir.sh usuario@servidor --con-datos      # + data/silver y usuarios.json (primera vez)
#   bash deploy/subir.sh usuario@servidor --con-env        # + .env (primera vez; contiene el token de SIGMA)
set -euo pipefail

HOST="${1:?Uso: bash deploy/subir.sh usuario@servidor [--con-datos] [--con-env]}"; shift || true
CON_DATOS=0; CON_ENV=0
for a in "$@"; do
  case "$a" in
    --con-datos) CON_DATOS=1 ;;
    --con-env) CON_ENV=1 ;;
    *) echo "Opción desconocida: $a"; exit 1 ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"
if [ -n "$(git status --porcelain)" ]; then
  echo "Hay cambios sin commitear. Hacé commit (y push) antes de subir, así lo que corre en el servidor es lo que quedó en git:"
  git status --short
  exit 1
fi
echo "Subiendo el commit $(git rev-parse --short HEAD) a $HOST ..."

DEST='~/tableros-sigma-deploy'
ssh "$HOST" "mkdir -p $DEST/code && rm -rf $DEST/code/* "
git archive --format=tar HEAD | ssh "$HOST" "tar -x -C $DEST/code"

if [ "$CON_DATOS" = 1 ]; then
  echo "Subiendo data/silver y usuarios.json ..."
  ssh "$HOST" "mkdir -p $DEST/data/silver $DEST/data/auth"
  rsync -a --delete data/silver/ "$HOST:$DEST/data/silver/"
  rsync -a data/auth/usuarios.json "$HOST:$DEST/data/auth/usuarios.json"   # sin sesiones.json: las sesiones no se copian
fi
if [ "$CON_ENV" = 1 ]; then
  echo "Subiendo .env (permisos 600) ..."
  scp -q .env "$HOST:$DEST/.env"
  ssh "$HOST" "chmod 600 $DEST/.env"
fi

echo
echo "Listo. Ahora, en el servidor:"
echo "  sudo bash ~/tableros-sigma-deploy/code/deploy/instalar_en_servidor.sh"
