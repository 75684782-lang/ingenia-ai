# Pruebas del complemento

No hay pruebas automatizadas ejecutables sin Civil 3D, porque cualquier acceso a
`Autodesk.Civil.DatabaseServices` requiere los ensamblados instalados y un documento activo.

Pruebas manuales obligatorias (ver `docs/civil3d-integration.md`):

1. Compilación del target correcto.
2. `GET /status` con y sin token.
3. Herramientas de lectura sobre un dibujo de prueba.
4. Creación de superficie, contornos, alineamiento y perfil con confirmación.
5. Reversión de transacción ante argumentos inválidos.
6. Comportamiento con Civil 3D cerrado o token incorrecto.

No añadir pruebas que simulen éxito de operaciones de Civil 3D en esta carpeta.
