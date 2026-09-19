# Instalación

## 1. Requisitos y backup

Necesitas una instalación funcional de Yamtrack, Docker Compose, acceso al host y una versión validada de Kavita. Este complemento usa rutas internas de la imagen Yamtrack (`/yamtrack`, `app.management`, `Book.save`): cambiar de imagen requiere pruebas.

Antes de tocar montajes, detén los procesos que escriben o usa la API de backup de SQLite para obtener una copia coherente. Guarda también Compose, configuración, imagen exacta y estado del conector si ya existía. No copies una SQLite activa sin tratar su WAL.

Los ejemplos asumen el stack en `/opt/yamtrack`, contenedor `yamtrack`, servicio Redis `redis`, volumen `./db` y red de proxy `caddy_default`. **Adapta estos nombres a tu stack**; no reemplaces tu Compose existente completo.

## 2. Código e imagen

Desde el directorio del stack:

```sh
git clone https://github.com/raishack/kavita-yamtrack-sync.git
cd kavita-yamtrack-sync
git checkout v0.2.1
cp deploy/config.example.json config.json
install -d -m 700 secrets
cd ..
install -d -m 700 db/kavita-yamtrack-sync
```

Fija `YAMTRACK_VALIDATED_IMAGE` en el archivo privado de configuración de Compose al **digest** probado, no `latest`. Este identificador de imagen no es un secreto. Imagen de referencia 0.26.3:

```text
ghcr.io/fuzzygrim/yamtrack@sha256:78497b454b2b52d3b1062f6fd238351d714cff0895db4369e49ace36f4622e75
```

Descarga esa imagen y prueba antes de desplegar:

```sh
docker pull ghcr.io/fuzzygrim/yamtrack@sha256:78497b454b2b52d3b1062f6fd238351d714cff0895db4369e49ace36f4622e75
./kavita-yamtrack-sync/deploy/test-image.sh ghcr.io/fuzzygrim/yamtrack@sha256:78497b454b2b52d3b1062f6fd238351d714cff0895db4369e49ace36f4622e75
```

Los tests usan contenedores desechables sin red y base en memoria, nunca tus volúmenes. Si tu arquitectura no está soportada por el digest, valida una imagen oficial de esa arquitectura antes de continuar.

## 3. Configuración y claves

En Kavita, cada lector genera su propia clave API desde sus preferencias. Utiliza el gestor de secretos o editor seguro del host para crear `kavita-yamtrack-sync/secrets/kavita-reader-api-key`. **No la pegues en comandos, URLs, Git, incidencias ni logs**. El archivo debe contener únicamente la clave, ser legible por el usuario que ejecuta el comando dentro del contenedor y tener modo `0600` (o más restrictivo). El conector rechaza permisos de grupo/otros.

```sh
chmod 600 kavita-yamtrack-sync/secrets/kavita-reader-api-key
chmod 600 kavita-yamtrack-sync/config.json
```

Edita el JSON: URL HTTPS de Kavita, nombre **exacto** de usuario Yamtrack, ruta interna de la clave y versiones permitidas. No añadas la clave al JSON. Para más usuarios, añade mapeos y montajes individuales. Revisa [Configuración](CONFIGURATION.md).

## 4. Montajes y panel opcional

Combina [el override de ejemplo](../deploy/docker-compose.override.example.yml) con tu Compose. Los montajes del comando son necesarios; el servicio `yamtrack-kavita-review` y la red Caddy son opcionales si no quieres panel.

- El montaje `/yamtrack/app/management` sustituye ese directorio dentro del contenedor: revisa cualquier comando personalizado previo y combínalo antes de usarlo.
- El comando y el panel deben usar **el mismo digest de Yamtrack**, base, configuración y directorio de estado.
- El ejemplo carga `.env` en el panel. Debe contener la misma configuración que recibe Yamtrack (`SECRET`, URL/orígenes, base de datos, Redis y proveedores). Si tu stack utiliza otros nombres o secretos de archivo, adapta el servicio. No cambies el secreto de sesión para instalar el panel.
- No montes las claves Kavita en el panel; solo el comando las necesita. Monta cada secreto por separado.
- Conserva cookies, orígenes CSRF, cabeceras del proxy y autenticación de Yamtrack. No deshabilites CSRF para arreglar un 403.
- Comprueba propietarios/UID del volumen: tanto comando como panel necesitan escribir estado y bloqueo. No uses permisos globales `777`.

Valida la sintaxis **sin volcar valores secretos** y recrea solo los servicios modificados:

```sh
docker compose config --quiet
docker compose up -d yamtrack yamtrack-kavita-review
```

Si omites el panel, recrea únicamente `yamtrack`.

Para Caddy, incorpora [el fragmento](../deploy/Caddyfile.review.snippet) en el mismo sitio HTTPS de Yamtrack, antes del proxy general. La red debe permitir que Caddy resuelva `yamtrack-kavita-review`. No añadas `ports:` al panel. Usa `/kavita-sync/` con barra final y un enlace visible en tu página de entrada si lo deseas; el complemento no modifica la navegación original de Yamtrack.

## 5. Simulación y primera aplicación

```sh
docker exec yamtrack python manage.py sync_kavita --config /run/kavita-yamtrack-sync/config.json
```

La salida resume decisiones, no una tabla con todas las lecturas. Revisa tus metadatos/overrides y valida primero sobre una copia aislada si necesitas inspeccionar cada asociación. Un resultado sin errores no garantiza que los títulos ambiguos se hayan identificado: revisa contadores `review`, `unmatched` y `manual_fallback`.

Tras el backup y la revisión:

```sh
docker exec yamtrack python manage.py sync_kavita --config /run/kavita-yamtrack-sync/config.json --apply
```

Repite para comprobar idempotencia: sin cambios de lectura nuevos no deben duplicarse fichas ni historial. El estado operativo y sus timestamps sí se actualizan. Comprueba notas, valoración, progreso y fechas antes de automatizar.

## 6. Automatización

Adapta ruta, ejecutable Docker y contenedor de los archivos `deploy/systemd/`. El servicio **incluye `--apply`**: no lo actives antes del piloto.

```sh
sudo install -m 644 kavita-yamtrack-sync/deploy/systemd/yamtrack-kavita-sync.service /etc/systemd/system/
sudo install -m 644 kavita-yamtrack-sync/deploy/systemd/yamtrack-kavita-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yamtrack-kavita-sync.timer
```

Se ejecuta 5 minutos después de finalizar el ciclo anterior, con hasta 30 segundos de desfase. El bloqueo compartido evita solapamientos. No actives además otro cron para la misma configuración. En NAS sin systemd, usa su planificador serializando el mismo comando.

## 7. Comprobaciones

```sh
sudo systemctl status yamtrack-kavita-sync.timer --no-pager
sudo journalctl -u yamtrack-kavita-sync.service -n 30 --no-pager
docker port yamtrack-kavita-review
curl --fail https://yamtrack.example.org/kavita-sync/health/
curl --fail https://yamtrack.example.org/kavita-sync/ready/
```

El panel no debe tener puertos publicados. Verifica redirección al login como anónimo y separación entre dos cuentas. `ready` puede devolver 503 hasta completar la primera aplicación correcta; `health` solo confirma que responde el proceso.
