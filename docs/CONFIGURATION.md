# Configuración

Parte de [config.example.json](../deploy/config.example.json). El schema es 1. No se incluyen valores reales ni overrides de usuarios.

| Campo | Valor recomendado / significado |
|---|---|
| `kavita_url` | HTTPS sin credenciales; solo se permite HTTP para una IP privada explícita no loopback en una red controlada |
| `state_file` | JSON privado persistente, compartido entre comando y panel |
| `review_file` | Cola privada; por defecto `review.json` junto al estado |
| `accounts` | Usuario exacto Yamtrack → archivo de clave del mismo lector de Kavita |
| `accounts[].overrides` | ID de capítulo Kavita → `{ "source": "openlibrary", "media_id": "OL123456M" }`; ejemplo ficticio, no copiar IDs a ciegas |
| `allowed_kavita_versions` | Lista exacta validada; ejemplo 0.9.0.2 y 0.9.1.4 |
| `allowed_yamtrack_versions` | Lista exacta validada; ejemplo 0.26.1 y 0.26.3 |
| `timeout_seconds` | 20; limitado a 5–120 |
| `allow_regress` | false; no activar para intentar arreglar una asociación incorrecta |
| `auto_match_min_score` | 95 |
| `review_match_min_score` | 80 |
| `auto_match_min_margin` | 8 respecto al segundo candidato |
| `preferred_publishers` | Ejemplo `Norma`; personalizar para tu biblioteca o usar `[]` |
| `hardcover_enabled` | true; requiere que el proveedor esté configurado en Yamtrack |
| `manual_fallback_after_cycles` | 3; tras ambigüedad persistente crea ficha manual determinista |
| `manual_reconcile_hours` | 24; vuelve a buscar una edición canónica para fichas manuales |
| `metadata_cache_seconds` | 3600; 0 desactiva la caché de detalle |
| `stale_after_seconds` | 3600; readiness falla sin éxito reciente |

## Identidad y coincidencias

ISBN, overrides y decisiones del usuario guían el matching. Título, autor, tomo, editorial, idioma y páginas ayudan a distinguir ediciones. Un tomo diferente no debe aceptarse solo por compartir serie. Los identificadores `chapterId` son unidades internas de Kavita: pueden representar libros o partes/tomos, no solo capítulos literarios.

Si aparecen dos lecturas para la misma edición, se informa del conflicto y se conservan ambas. Una lectura eliminada o reemplazada no se recrea silenciosamente. No borres `state.json` para resolver un error: perderías identidad, decisiones e historial de sincronización.

La proporción se convierte a las páginas de la edición Yamtrack; una lectura incompleta nunca debe redondearse al máximo. Una ficha ya completada no se reabre automáticamente.

## Panel

Cada usuario ve solo su cola. Aprobar seleccionada o usar otra edición guarda una decisión; el siguiente ciclo la aplica. Ignorar permanece hasta un cambio de identidad; buscar de nuevo invalida la decisión de búsqueda. Las escrituras usan POST + CSRF y comparten bloqueo con el comando.

Los secretos de proveedores, si son necesarios, se configuran mediante los mecanismos de Yamtrack. No existe una clave global de Kavita que sustituya las claves individuales.
