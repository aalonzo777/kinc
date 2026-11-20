# 🏥 KINC — Guía de instalación y uso

## Requisitos previos
- Python 3.10 o superior instalado
- pip disponible en terminal

---

## Paso 1 — Descargar el proyecto

Coloca la carpeta `kinc/` donde prefieras, por ejemplo en tu escritorio o en `Documentos/`.

---

## Paso 2 — Crear entorno virtual

Abre una terminal dentro de la carpeta `kinc/` y ejecuta:

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

Sabrás que está activo porque verás `(venv)` al inicio de la línea.

---

## Paso 3 — Instalar dependencias

```bash
pip install -r requirements.txt
```

Esto instala Django y Pillow (para manejo de imágenes).

---

## Paso 4 — Crear la base de datos

```bash
python manage.py migrate
```

Esto crea el archivo `db.sqlite3` con todas las tablas del proyecto.

---

## Paso 5 — Cargar datos de prueba (opcional pero recomendado)

```bash
python manage.py seed_data
```

Crea automáticamente:
- Un kinesiólogo de prueba
- Un paciente de prueba
- 3 desafíos de ejemplo
- 3 recompensas de ejemplo
- 2 videos de ejemplo

**Credenciales de acceso:**
| Rol           | Correo              | Contraseña |
|---------------|---------------------|------------|
| Kinesiólogo   | kin@kinc.cl         | kinc1234   |
| Paciente      | paciente@kinc.cl    | kinc1234   |

---

## Paso 6 — Crear superusuario administrador (opcional)

Para acceder al panel de administración de Django:

```bash
python manage.py createsuperuser
```

Luego entra a: http://127.0.0.1:8000/admin/

---

## Paso 7 — Iniciar el servidor

```bash
python manage.py runserver
```

Abre tu navegador en: **http://127.0.0.1:8000**

---

## Estructura del proyecto

```
kinc/
├── manage.py
├── requirements.txt
├── db.sqlite3              ← se crea al hacer migrate
├── media/                  ← fotos subidas por pacientes
├── kinc/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── core/
    ├── models.py           ← todos los modelos (User, Patient, Challenge...)
    ├── views.py            ← toda la lógica
    ├── urls.py             ← todas las rutas
    ├── forms.py            ← formularios
    ├── admin.py            ← panel admin
    ├── management/
    │   └── commands/
    │       └── seed_data.py ← datos de prueba
    └── templates/
        └── core/
            ├── base.html
            ├── login.html
            ├── kin_dashboard.html
            ├── notifications.html
            ├── patients/   ← CRUD pacientes
            ├── challenges/ ← CRUD desafíos
            ├── rewards/    ← CRUD recompensas
            ├── videos/     ← CRUD videos
            └── patient/    ← panel del paciente
```

---

## Flujo de uso

### Como kinesiólogo:
1. Entra con tu correo y contraseña
2. Ve a **Pacientes** → agrega un paciente con su correo y contraseña
3. Ve a **Desafíos** → crea desafíos con tipo, duración y puntos
4. Ve a **Recompensas** → crea recompensas con costo en puntos y stock
5. Ve a **Videos** → agrega videos de YouTube y asígnalos a pacientes
6. Desde el **detalle de un paciente** → asígnale desafíos
7. Cuando el paciente suba su prueba, verás la notificación y podrás **aprobar o rechazar**

### Como paciente:
1. Entra con tu correo y contraseña
2. En **Mis desafíos** → acepta los desafíos y envía la foto de prueba
3. En **Recompensas** → canjea tus puntos por recompensas
4. En **Videos** → ve los videos asignados por tu kinesiólogo

---

## Comandos útiles

```bash
# Reiniciar base de datos desde cero
del db.sqlite3          # Windows
rm db.sqlite3           # macOS/Linux
python manage.py migrate
python manage.py seed_data

# Ver errores detallados (ya activo por defecto con DEBUG=True)
python manage.py runserver

# Colectar archivos estáticos para producción
python manage.py collectstatic
```

---

## Notas importantes

- Las **fotos de prueba** se guardan en la carpeta `media/challenge_proofs/`
- El archivo `db.sqlite3` **es tu base de datos** — guárdalo como respaldo
- Para cambiar a **PostgreSQL** en producción, edita `DATABASES` en `kinc/settings.py`
- Cambia el `SECRET_KEY` en `settings.py` antes de subir a producción


---

## Novedades versión 3

- **Desafíos asignados:** desde la ficha del paciente puedes ver, editar o quitar cada desafío asignado
- **Videos en desafíos:** al crear o editar un desafío puedes asociarle un video de YouTube
- **Sección Videos eliminada** del menú lateral (los videos ahora viven dentro de los desafíos)
- **Chat en dashboard:** acceso rápido al chat con cada paciente desde el panel principal
- **Notificaciones clickeables:** cada notificación lleva directamente a la sección correspondiente
- **Ver foto y verificar:** botón "Ver prueba" en cada desafío muestra la foto del paciente y permite aprobar/rechazar
- **Campo `link` en Notification:** nuevo campo en el modelo — recuerda correr `makemigrations` y `migrate`


---

## Versión 5 — Seguridad (leer antes de instalar)

Esta versión cambia los modelos, así que hay que empezar con una base de datos limpia:

```bash
# Windows
del db.sqlite3
del core\migrations\0*.py
python -m pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

- **Probar todas las validaciones:** `python manage.py test`
- **Crear otro kinesiólogo:** `python manage.py create_kinesiologo --email ana@correo.cl --nombre Ana --apellido Martinez`
- **Probar desde el celular en tu red:** `set KINC_ALLOWED_HOSTS=localhost,127.0.0.1,TU_IP_LOCAL` (Windows) antes de `runserver 0.0.0.0:8000`
- Los pacientes nuevos reciben una contraseña temporal y **deben cambiarla al entrar**.
- Detalle completo de formatos y medidas: ver `SEGURIDAD.md`.

---

## Versión 6 — mejoras

Cambian los modelos (categorías de video, se elimina la asignación de videos a pacientes), así que repite el reinicio:

```bash
del db.sqlite3
del core\migrations\0*.py
python manage.py makemigrations core
python manage.py migrate
python manage.py seed_data
python manage.py test
python manage.py runserver
```

Novedades: historial de progreso con "Entrega rechazada" (0 pts) y "Recompensa rechazada (puntos devueltos)", Videos de vuelta en el menú del kinesiólogo, categorías de video como lista, botón ← volver atrás, botones Progreso/Chat/PDF en la ficha del paciente, puntito rojo de novedades en el menú, menú hamburguesa en el celular, links de YouTube con o sin https/www, videos asociados a desafíos y página de detalle de cada desafío (`/kin/desafios/<id>/detalle/`).

---

## Versión 7 — lista para Vercel

Se agregó compatibilidad con Vercel (PostgreSQL, bucket S3 privado, caché compartida, HTTPS tras proxy y límite de fotos de 4 MB). En tu PC todo sigue funcionando con SQLite.
Reinstala dependencias: `python -m pip install -r requirements.txt`. Pasos de despliegue en `DESPLIEGUE_VERCEL.md`.
