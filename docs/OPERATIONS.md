# Operación y diagnóstico

## Estado persistente

- `state.json`: identidades, vínculos de fichas, decisiones, caché y reintentos.
- `review.json`: propuestas pendientes de revisión.
- `status.json`: último resultado global/por cuenta, duración y códigos de error.
- `sync.lock`: bloqueo entre comando y panel.

Son archivos privados, normalmente modo 0600. No editarlos con el timer o el panel activos. Los writes del ORM y JSON no forman una transacción distribuida: cada libro se confirma y luego se guarda un punto de avance; la identidad determinista permite reanudar.

## Salud

`/kavita-sync/health/` es liveness; `/kavita-sync/ready/` devuelve 200 solo tras éxito reciente o 503 cuando está degradado. No uses readiness como política de reinicio en bucle: hay que corregir la causa. Un fallo parcial devuelve salida no cero aunque otros libros se hayan actualizado.

## Problemas frecuentes

| Síntoma | Qué revisar |
|---|---|
| `incompatible_kavita_version` / `incompatible_yamtrack_version` | Bloqueo intencional. Validar la versión y solo después ampliar su lista exacta |
| Error al leer clave | Archivo, ruta **interna**, propietario y permisos 0600; no imprimir su contenido |
| HTTP 401/403 | Clave individual, permisos de biblioteca, URL correcta y soporte de autenticación por cabecera |
| Comando `sync_kavita` ausente | Montaje `/yamtrack/app/management` y paquete en `/yamtrack/kavita_yamtrack_sync` |
| Panel vuelve al login | Mismo origen, secreto de sesión y base de usuarios; configuración efectiva del panel |
| Panel rechaza POST | CSRF, cookies y cabeceras HTTPS del proxy; no desactivar la protección |
| Ficha tarda en aparecer | Solo se importan unidades con progreso; historial diferido + on-deck; revisar cola y contadores |
| Proveedor no responde | Los errores no equivalen a «sin coincidencias»; reintentos con espera creciente |
| API devuelve HTML/redirección | URL base canónica: no se siguen redirecciones autenticadas |
| Nuevo config no se aplica | Un bind mount de archivo puede conservar el inode anterior; recrear los servicios afectados |
| Progreso parece menor entre ediciones | Comprobar proporción de páginas antes de confundirla con una regresión |

Para volver a consultar propuestas pendientes:

```sh
docker exec yamtrack python manage.py sync_kavita --config /run/kavita-yamtrack-sync/config.json --refresh-matches
```

Sin `--apply` no persiste la búsqueda; añade el flag solo si deseas guardar y aplicar decisiones. No publiques logs sin revisarlos: aunque el conector resume errores, dependencias o herramientas externas podrían incluir datos.
