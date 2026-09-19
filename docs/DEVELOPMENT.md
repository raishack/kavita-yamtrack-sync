# Desarrollo y pruebas

## Arquitectura

- `core.py`: decisiones de progreso, fechas y proporciones.
- `http_clients.py`: Kavita/Open Library, autenticación por cabecera, timeouts y reintentos.
- `matching.py`: identidad bibliográfica, ranking y selección conservadora.
- `automation.py`: fallback y reconciliación.
- `state.py`, `locking.py`: persistencia atómica por archivo y exclusión mutua.
- `observability.py`: salud y errores resumidos.
- `review_*`, `review.html`: panel Django con sesión compartida y aislamiento por usuario.
- `deploy/django_management/commands/sync_kavita.py`: orquestación, modelos/proveedores reales y transacciones.

## Pruebas unitarias (sin servicios ni claves)

Desde la raíz, Python 3.12+:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip install ruff==0.15.6
python -m ruff check .
```

Se recomienda un entorno virtual. No se importa Django para las pruebas unitarias. Para ejecutar el comando real se utiliza la imagen Yamtrack, no una instalación arbitraria de Django.

## Integración real con modelos de Yamtrack

Descarga primero la imagen fijada descrita en [Instalación](INSTALL.md) y ejecuta:

```sh
./deploy/test-image.sh ghcr.io/fuzzygrim/yamtrack@sha256:78497b454b2b52d3b1062f6fd238351d714cff0895db4369e49ace36f4622e75
```

El script fija su ID, ejecuta la suite unitaria y después Django con SQLite en memoria, migraciones originales y proveedores simulados. Usa `--network none`, sin montajes de secretos ni estado real. Verifica `Book.save`, historial, transacciones, colisiones, CSRF, aislamiento, dry-run y reanudación.

CI ejecuta ambas suites en cada push/PR con permisos de lectura; no despliega ni publica automáticamente. Las pruebas HTTP simuladas no equivalen a integración en vivo con cada firmware/versión de Kavita.

## Contribuir

Cambios pequeños, pruebas para decisiones que afecten lecturas, sin bases ni credenciales. Conserva el bloqueo de versión y la simulación por defecto. No cambies identidades deterministas o schema sin plan de migración. Antes de publicar, revisa todo el árbol y artefactos y ejecuta un detector de secretos. El checkout público no es el despliegue activo.
