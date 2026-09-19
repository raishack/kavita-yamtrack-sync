# Seguridad y privacidad

No publiques claves, configuración de producción, bases, estado, colas, títulos leídos ni logs sin revisar. La clave de cada lector reside en archivo privado; nunca en argumentos, URLs o Git. Las peticiones autenticadas no siguen redirecciones. Usa HTTPS o una red privada controlada si aplicas la excepción HTTP explícita.

El conector escribe mediante el ORM de Yamtrack, no mediante SQL directo. Necesita acceso de escritura a la base y al estado para aplicar cambios. El panel comparte la sesión y el secreto de Yamtrack; no expongas directamente su puerto. No desactives CSRF ni uses permisos globales para resolver errores.

Los catálogos externos reciben consultas bibliográficas; revisa sus políticas antes de habilitar matching en bibliotecas sensibles. El archivo de estado puede revelar hábitos y nombres de usuario aunque no contenga claves.

Para vulnerabilidades, usa el canal privado **Report a vulnerability** de GitHub si está habilitado. No abras incidencias públicas con datos explotables o secretos; si el canal no está disponible, solicita un contacto privado sin detallar la vulnerabilidad.

La compatibilidad se limita a las versiones documentadas. Cualquier actualización de Yamtrack/Kavita requiere revalidación y copias coherentes.
