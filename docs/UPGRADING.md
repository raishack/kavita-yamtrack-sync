# Actualizaciones controladas y rollback

El conector depende de API de Kavita y modelos internos de Yamtrack. No actualizar desde `latest`, eliminar bloqueos de versión ni copiar binarios parcheados de una versión a otra.

## Procedimiento

1. Inventariar versiones, digest, montajes, configuración, timer y extensiones locales. Guardar los archivos originales y diferencias que no pertenecen al conector.
2. Descargar la candidata oficial y verificar su identidad/hash. Para Yamtrack, ejecutar `deploy/test-image.sh` contra un ID/digest inmutable.
3. Obtener copia coherente de la base (backup SQLite o parada de todos los escritores), JSON, configuración, claves protegidas, imágenes y código. Verificar integridad y posibilidad de restauración. Restringir accesos; nunca adjuntar copias al repositorio.
4. Arrancar una instancia aislada con la copia, sin jobs ni salida hacia integraciones reales. No montar libros originales con escritura ni apuntar la prueba al Yamtrack de producción.
5. Verificar migración e integridad; comparar progreso, fechas, notas, valoración, PK e historial. Probar autenticación y aislamiento.
6. Kavita: probar autenticación por cabecera, historial paginado, on-deck, detalle y progreso de manga/EPUB. Ejecutar el conector completo en dry-run contra el ensayo.
7. Yamtrack: probar ORM, proveedores simulados, panel, CSRF, aislamiento, transacciones e idempotencia. La suite sintética no sustituye la migración de una copia real.
8. Solo al pasar: pausar timer, esperar el job activo, detener escritores y preparar backup final reciente. Actualizar código/imagen/config sin reemplazar secretos ni JSON vivos. Ambos servicios Yamtrack y panel usan el mismo digest.
9. Añadir únicamente la versión exacta recién validada a la configuración. Si sustituyes archivos bind-mounted, recrea los contenedores afectados para renovar los montajes.
10. Ejecutar dry-run, revisar decisiones, ejecutar un ciclo real y otro idempotente. Comprobar HTTPS, readiness, login, notas y lecturas. Restaurar el estado previo del timer y vigilar el primer ciclo automático.
11. Registrar versión, digest/hash, copia, pruebas, incidencias y receta de reversión en documentación privada. No anunciar éxito por el mero arranque de la web.

## Referencia comprobada

El 19/09/2026 se validó la migración Kavita **0.9.0.2 → 0.9.1.4** con Yamtrack **0.26.3**: copia aislada, integridad, consultas de progreso/historial y dry-run, seguido de ciclo productivo sin errores. La allowlist cambió; el algoritmo de sincronización no.

La integración **Troop Reader** se validó por separado. 0.9.1.4 aún necesitó un ajuste del parámetro de imágenes para esa app; **este conector no necesita ese parche**. Consulta la [guía de Troop Reader](https://github.com/raishack/troop-reader) si utilizas ambos.

## Rollback

Parar el timer, esperar el job y detener el panel; conservar primero una copia del estado nuevo. Restaurar el código, configuración e imagen anterior compatibles y recrear solo los servicios afectados. No deshacer toda una base para revertir solo código: perderías lecturas nuevas.

Si una migración exige restaurar base, detener **todos** los escritores y restaurar el conjunto coherente de base/JSON/código/configuración. Documentar qué cambios posteriores se perderían antes de hacerlo. No iniciar binarios antiguos con una base migrada suponiendo que admite downgrade. Verificar integridad, dry-run, idempotencia y salud antes de reactivar timer.
