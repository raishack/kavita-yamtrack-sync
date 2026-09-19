# Cambios

## 0.2.1 — primera publicación independiente

- Documentación pública de instalación, operación, pruebas y actualización/reversión.
- Ejemplo compatible con Kavita 0.9.0.2 y 0.9.1.4, Yamtrack 0.26.1 y 0.26.3.
- CI con imagen Yamtrack fijada por digest y base desechable sin red.
- Paquete incluye plantilla del panel; metadatos y versión interna coherentes.
- Eliminados de la copia pública los informes privados, configuraciones y datos de despliegue.
- Sin cambios en el algoritmo de sincronización de 0.2.0. Esta publicación no actualiza automáticamente instalaciones existentes.

## 0.2.0 — base funcional

- Reconciliación manual, conversión proporcional sin completar prematuramente.
- Protección de PK, notas, valoración e historial durante migración de ficha.
- Fallos aislados por cuenta/libro, reintentos y puntos de avance.
- Estado de salud por cuenta, readiness, caché y despliegue con imagen validada.
