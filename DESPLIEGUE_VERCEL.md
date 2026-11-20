# Despliegue de KINC en Vercel (GitHub + Vercel)

Vercel ejecuta la app en funciones **sin disco persistente**, por eso en producción la base de datos es PostgreSQL y las fotos van a un bucket privado.
Vercel detecta Django solo (busca `manage.py` y `kinc/wsgi.py`): no hace falta `vercel.json`.

## 1. Antes de subir a GitHub (en tu PC)

```bash
del db.sqlite3
del core\migrations\0*.py
python manage.py makemigrations core
```

**Importante:** sube a GitHub los archivos que se crean en `core/migrations/` (por ejemplo `0001_initial.py`). Sin ellos, las tablas de KINC no se crean en producción.
El `.gitignore` ya excluye `db.sqlite3`, `media/`, `staticfiles/` y `.env`.

## 2. Base de datos (Neon, desde el Marketplace de Vercel)

Agrega Neon al proyecto en Vercel: crea la variable `DATABASE_URL` automáticamente.

## 3. Bucket privado para las fotos (Cloudflare R2 o Supabase Storage)

1. Crea un bucket **privado** (sin acceso público).
2. Crea una clave de acceso con permiso de lectura y escritura.
3. Anota: clave, secreto, nombre del bucket y la URL del endpoint S3.

## 4. Variables de entorno en Vercel (Project Settings → Environment Variables)

| Variable | Valor |
|---|---|
| `KINC_SECRET_KEY` | cadena larga y aleatoria (obligatoria) |
| `DATABASE_URL` | la entrega Neon |
| `AWS_ACCESS_KEY_ID` | clave del bucket |
| `AWS_SECRET_ACCESS_KEY` | secreto del bucket |
| `AWS_STORAGE_BUCKET_NAME` | nombre del bucket |
| `AWS_S3_ENDPOINT_URL` | endpoint S3 del proveedor |
| `AWS_S3_REGION_NAME` | `auto` en R2; la región de tu proyecto en Supabase |

En Vercel el modo producción se activa solo (`KINC_DEBUG=False`), y `.vercel.app` ya queda permitido.
Con dominio propio agrega `KINC_ALLOWED_HOSTS` y `KINC_CSRF_TRUSTED_ORIGINS` (ej. `https://midominio.cl`).

## 5. Primer despliegue y preparación de la base (una sola vez)

Despliega desde Vercel. Luego, en tu PC (PowerShell), apuntando a la base de producción:

```powershell
$env:DATABASE_URL = "pega-aqui-la-url-de-neon"
python manage.py migrate
python manage.py createcachetable
python manage.py create_kinesiologo --email tu@correo.cl --nombre Nombre --apellido Apellido
```

No uses `seed_data`: se niega a ejecutarse en producción a propósito.

## 6. Qué probar

1. Iniciar sesión como kinesiólogo y crear un paciente (queda con contraseña temporal).
2. Entrar como paciente: debe pedir cambio de contraseña.
3. Aceptar un desafío y subir una foto desde el celular.
4. Como kinesiólogo, abrir la foto y aprobarla.

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| Error 413 al subir una foto | La foto supera 4,5 MB (límite de Vercel). El navegador la reduce sola; si falla, usa una foto más liviana. |
| `relation "core_user" does not exist` | Faltan las migraciones en GitHub o no ejecutaste `migrate` contra la base de producción. |
| `DisallowedHost` | Falta el dominio en `KINC_ALLOWED_HOSTS`. |
| «Verificación CSRF fallida» | Agrega tu dominio a `KINC_CSRF_TRUSTED_ORIGINS`. |
| Las fotos no se ven | Revisa las variables del bucket; el error queda registrado en los logs de Vercel. |
| Error de «prepared statement» | Usa la URL de conexión **sin pooler** de Neon en `DATABASE_URL`. |
| La web carga sin estilos | Revisa tu conexión: Bootstrap y los iconos se cargan desde un CDN. |
