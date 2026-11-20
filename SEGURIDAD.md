# Seguridad y validación de formatos — KINC v5

Todas las validaciones se hacen en el **servidor** (los atributos HTML como `maxlength` son solo ayuda visual).
Para comprobarlas: `python manage.py test`

## Formatos validados por campo

| Campo | Regla |
|---|---|
| Nombre / Apellido | 2–50 caracteres, solo letras (con tildes/ñ), espacios, guion y apóstrofe |
| Correo | Formato de email válido, máx. 150, se guarda en minúsculas, **único** (también en la base de datos) |
| Teléfono | Opcional. Acepta espacios/guiones, se normaliza a `+56912345678` (8–15 dígitos, `+` opcional) |
| Edad | Entero entre 1 y 120 |
| Contraseña | Mín. 8, no común, no solo números, no parecida al nombre/correo, máx. 128 |
| Notas clínicas | Máx. 2000 caracteres |
| Desafío | Nombre ≤100, descripción ≤500, puntos 1–10000, tipo solo diario/semanal/mensual |
| Duración del desafío | 1–365 días · 1–52 semanas · 1–24 meses (según el tipo elegido) |
| Recompensa | Nombre ≤100, descripción ≤500, costo 1–100000, stock 0–10000 |
| Video | Solo links de YouTube (`youtube.com/watch?v=…`, `youtu.be/…`) con ID de 11 caracteres; título ≤100, categoría ≤50 |
| Foto de entrega | **Obligatoria**, JPG/PNG/WEBP, máx. 4 MB (límite de Vercel), se verifica con Pillow que sea una imagen real |
| Mensaje de entrega / feedback | Máx. 500 caracteres |
| Chat | 1–1000 caracteres (no vacío) |
| Búsqueda | Máx. 100 caracteres |
| IDs en la URL | Solo hasta 9 dígitos; si no, responde 404 (no error 500) |
| Fechas | No hay campos de fecha que escriba el usuario: todas las genera el servidor |

## Medidas de seguridad

| Riesgo | Medida |
|---|---|
| Inyección SQL | Todo el acceso a datos usa el ORM de Django (consultas parametrizadas); no hay SQL manual |
| XSS | Las plantillas escapan todo el contenido; el PDF también escapa el texto del paciente |
| CSRF | Middleware activo y `{% csrf_token %}` en todos los formularios; cerrar sesión solo por POST |
| Contraseñas | Guardadas con hash (PBKDF2) + validadores de complejidad |
| Contraseña temporal | El paciente **debe** cambiarla en su primer ingreso (el kinesiólogo deja de conocerla) |
| Fuerza bruta | Bloqueo de 15 min tras 5 intentos fallidos (por correo + IP); mensaje igual para correo inexistente |
| Fotos de pacientes | No son públicas: se entregan solo al paciente dueño y a su kinesiólogo (`/entrega/<id>/foto/`); nombres de archivo aleatorios; se borran del disco al eliminar la entrega |
| Aislamiento de datos | Cada kinesiólogo solo ve sus pacientes/desafíos/recompensas/videos; verificado en tests |
| Condiciones de carrera | Puntos y stock se descuentan con UPDATE atómicos; una entrega no puede aprobarse dos veces |
| Sesión | Expira a las 8 h; cookies HttpOnly y SameSite |
| Producción | `KINC_DEBUG=False` activa HTTPS forzado, cookies Secure, HSTS; la clave secreta y los hosts salen de variables de entorno |
| Datos de prueba | `seed_data` se niega a ejecutarse fuera de modo desarrollo |

## Variables de entorno para producción

```
KINC_DEBUG=False
KINC_SECRET_KEY=<cadena larga y aleatoria>
KINC_ALLOWED_HOSTS=midominio.cl
```

## Limitaciones conocidas (honestas)

- El bloqueo de intentos de login usa una caché en la base de datos cuando existe `DATABASE_URL` (producción, compartida entre instancias) y memoria local en tu PC.
- No hay CSP (Content-Security-Policy), 2FA, ni recuperación de contraseña por correo.
- Los datos de salud son sensibles (Ley 19.628 / Ley 21.719): en producción hay que usar HTTPS, respaldos cifrados y no mapear `/media/` en el servidor web.

## Texto sugerido para el informe (RNF-03 Seguridad)

> El sistema exige autenticación mediante correo y contraseña. Las contraseñas se almacenan cifradas (hash PBKDF2) y deben cumplir criterios de complejidad (mínimo 8 caracteres, no comunes ni exclusivamente numéricas). Las contraseñas iniciales asignadas por el kinesiólogo son temporales y deben ser cambiadas por el paciente en su primer ingreso. El acceso se bloquea temporalmente tras cinco intentos fallidos. Cada usuario solo accede a la información que le corresponde según su rol, y las fotografías de evidencia solo son visibles para el paciente que las envió y para su kinesiólogo. Todos los datos ingresados se validan en el servidor (formato, longitud y rango), y las consultas a la base de datos se realizan mediante el ORM de Django, lo que previene inyección SQL. La protección contra XSS y CSRF se aplica mediante el escape automático de plantillas y tokens CSRF en todos los formularios.
