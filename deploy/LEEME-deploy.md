# Despliegue en el servidor (VM `n8npeji`, Ubuntu)

Primera etapa: Streamlit en `127.0.0.1` del servidor y acceso por **Tailscale** con HTTPS (`tailscale serve`).
Cloudflare Tunnel + Access (vendedores desde el celular) queda para después: ver el doc 09 del proyecto.

## Qué hay en esta carpeta
- `subir.sh` (Mac): sube el último commit al servidor, y con `--con-datos` / `--con-env` también `data/silver`, `usuarios.json` y `.env`.
- `instalar_en_servidor.sh` (servidor, con sudo): crea el usuario de servicio `tableros`, instala en `/opt/tableros-sigma`, arma el venv, el servicio systemd, el cron y la rotación de logs. Se puede correr de nuevo para actualizar.
- `tableros.service`, `cron-tableros`, `logrotate-tableros`: plantillas que usa el instalador.

## Primera vez
1. **En la Mac:** commit y push de todo lo pendiente (`git status` limpio), porque `subir.sh` se niega a subir con cambios sin commitear.
2. **En la Mac:**
   ```bash
   bash deploy/subir.sh TU_USUARIO@IP_O_NOMBRE_DEL_SERVIDOR --con-datos --con-env
   ```
   `--con-datos` copia las tablas ya cargadas (7 MB) y `usuarios.json` (claves en hash, así los vendedores conservan las temporales). `--con-env` copia el `.env` con el token de SIGMA (queda con permisos 600).
3. **En el servidor:**
   ```bash
   sudo bash ~/tableros-sigma-deploy/code/deploy/instalar_en_servidor.sh
   ```
4. **Acceso por Tailscale** (en el servidor; si el 443 ya lo usa otro servicio, queda el 8443 del ejemplo):
   ```bash
   sudo tailscale serve --bg --https=8443 http://127.0.0.1:8510
   tailscale serve status
   ```
   Entrar a `https://<nombre-del-servidor>.<tailnet>.ts.net:8443`. Requiere HTTPS activado en el panel de Tailscale.
5. **Probar:** entrar con un gerente y con un vendedor; el vendedor no tiene que ver datos de otro. Probar F5 (sesión persistente) y desde el celular.
6. **Primer ETL en el servidor** (para verificar token y red, antes de esperar al cron):
   ```bash
   sudo -u tableros bash -c 'cd /opt/tableros-sigma && venv/bin/python scripts/etl/run_etl.py --solo ventas'
   ```

## Actualizar el código más adelante
Commit + push en la Mac, después `bash deploy/subir.sh usuario@servidor` y en el servidor el mismo `sudo bash …/instalar_en_servidor.sh`. No pisa `data/`, `.env` ni `venv`.
Si cambian objetivos o artículos (los Excel): correr los `cargar_*.py` en la Mac y subir con `--con-datos`.

## Operación
- Estado: `systemctl status tableros` · logs de la app: `journalctl -u tableros -f` · logs del ETL: `/var/log/tableros/etl.log`.
- Reiniciar: `sudo systemctl restart tableros` (obligatorio tras tocar `src/`).
- El cron usa la hora del servidor: tiene que ser `America/Argentina/Salta` (`timedatectl`). Si no, `sudo timedatectl set-timezone America/Argentina/Salta`.
- Backup: copiar `/opt/tableros-sigma/data/auth/usuarios.json` fuera de la VM de vez en cuando (solo hashes).
- Permisos: `data/` 700, `.env` 600, usuario `tableros` sin sudo ni shell. No abrir el puerto 8510 hacia afuera.

## Pendiente para la etapa 2
Dominio `pejinakiscontrol.com`, Cloudflare Tunnel + Access, mínimo de clave 10 y lista de claves comunes, registro de auditoría (docs 08 y 09).
