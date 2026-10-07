# Etapa 2: acceso desde Internet con Cloudflare Tunnel + Access

Quién entra: los vendedores (y gerentes) desde el celular, con una URL (`https://tableros.pejinakiscontrol.com`), sin instalar nada.
Cómo se protege: (1) **Cloudflare Access** pide un código que llega por mail y solo deja pasar a los mails de la lista;
(2) después está el **login propio** de la app (usuario = código de vendedor), que decide qué ve cada uno.
El túnel sale desde el servidor hacia Cloudflare: **no se abre ningún puerto del router ni del servidor**.

## Lo que hace Juan (a nombre de la empresa; yo no puedo registrar ni pagar nada)
1. **Cuenta de Cloudflare** con un mail de la empresa y **MFA** activado (Perfil → Autenticación).
2. **Dominio**: Cloudflare → Domain Registration → Register Domains → buscar `pejinakiscontrol.com` (si está tomado: `pejinakis-control.com` o `pejinakisbi.com`). Cloudflare lo vende a precio de costo (unos USD 10–15 por año) y queda con su DNS ya delegado. Registrarlo a nombre de la empresa, con mail de la empresa.
3. **Zero Trust**: menú Zero Trust → elegir un nombre de equipo (por ejemplo `pejinakis`) → plan **Free**. (Pide una tarjeta aunque cueste USD 0; verificar el cupo de usuarios del plan Free: ~14 vendedores + gerentes + supervisores.)
4. **Túnel**: Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared → nombre `tablero-sigma` → en "Install and run connectors" elegir **Debian / 64-bit** y **copiar el token** (el texto largo que empieza con `eyJ`). No lo pegues en chats ni en docs.
5. En el servidor (te pide la clave de sudo y después el token, que no se ve al pegarlo):
   ```bash
   ssh -t n8npeji 'sudo bash ~/tableros-sigma-deploy/code/deploy/instalar_cloudflared.sh'
   ```
   (hace falta haber subido antes el código con `bash deploy/subir.sh n8npeji`).
6. En el panel, pestaña **Public Hostname** del túnel: Subdomain `tableros`, Domain `pejinakiscontrol.com`, Service **HTTP** `localhost:8510`.
7. **Access**: Zero Trust → Access → Applications → Add → Self-hosted. Application domain `tableros.pejinakiscontrol.com`. Política **Allow** → Include → **Emails** (lista) y método de login **One-time PIN**. Duración de sesión larga (por ejemplo 1 semana a 1 mes) para que el vendedor no pida el código todos los días. **Primero cargar solo 2–3 mails de prueba (el tuyo y uno más)**.
8. **Probar** con un celular por datos móviles (sin Tailscale): entra la pantalla de Cloudflare, llega el código al mail, después aparece el login de la app. Verificar que un mail que NO está en la lista no puede pasar, que un vendedor ve solo lo suyo y que F5 mantiene la sesión.
9. Recién entonces cargar el resto de los mails. Salen de `python scripts/admin/listar_vendedores.py --csv` (columna `email`). Es dato personal: no va al repo ni a los docs. Verificar que cada vendedor recibe el código (mirar spam).

## Altas y bajas
- Vendedor nuevo: usuario en la app (`scripts/admin/usuarios.py`) **y** su mail en la política de Access.
- Baja: quitar el mail de la política de Access (corta el acceso de inmediato) y desactivar el usuario de la app.

## Qué quedó reforzado en la app antes de abrirla a Internet
- Clave mínima de **10 caracteres**, con letras y números; se rechazan claves comunes (`password123`, `pejinakis2026`, …), repetitivas, casi solo números y las que contienen el usuario. Las claves temporales ya repartidas siguen valiendo hasta el primer cambio.
- Freno de intentos **por usuario** (5 fallos = 5 minutos) y **por IP** (20 fallos = 10 minutos). Detrás de Cloudflare la IP sale de `Cf-Connecting-Ip`.
- **Registro de ingresos** en `/opt/tableros-sigma/data/auth/auditoria.log` (una línea JSON por evento: `ingreso_ok`, `ingreso_fallido`, `ingreso_bloqueado`, `salida`, `clave_cambiada`; con hora de Salta e IP; nunca claves). Para mirarlo: `sudo tail -50 /opt/tableros-sigma/data/auth/auditoria.log`.

## Ojo
- La red interna sigue entrando por `http://192.168.1.58:8510` (sin Cloudflare ni HTTPS). Si quisieras que SOLO se pueda entrar por Cloudflare/Tailscale: correr el instalador con `BIND=127.0.0.1` (ver `LEEME-deploy.md`).
- Dependencia: si Cloudflare cae o vence el dominio, los vendedores pierden el acceso (los gerentes siguen por Tailscale o red interna). Poner el vencimiento del dominio en el calendario.
- El tráfico HTTPS se termina en Cloudflare: los datos de ventas pasan por su red. Confirmar que la empresa lo acepta.
