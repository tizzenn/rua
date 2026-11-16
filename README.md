# Rúa (v3.5 Autogestión)

Agenda local abierta, generalista y autogestionada. La aplicación musical de v3.3 se conserva como módulo heredado mientras se incorpora un modelo universal de actividades, categorías, entidades, lugares y fuentes.

La primera instancia mantiene Ourense, Vigo y Santiago de Compostela en `instance.json`, pero el ámbito ya no está codificado en el núcleo generalista: cada instalación define sus municipios y radio en su propia configuración. Las rutas y validaciones heredadas de música siguen conservando compatibilidad con la v3.3.

## Arranque local (Arch Linux)

```bash
export RUA_ADMIN_TOKEN="$(openssl rand -hex 24)"
python server.py                 # http://127.0.0.1:8000
python -m unittest discover -s tests -v
```


## v3.5 — Administración y autohospedaje

- Nuevo panel privado en `/admin.html`, protegido por `RUA_ADMIN_TOKEN`.
- Configuración desde navegador: identidad de la instancia, zona horaria, ámbito, municipios y radio predeterminado.
- Edición validada de categorías jerárquicas. Las categorías omitidas se desactivan en vez de borrarse, para no romper referencias históricas.
- Edición de fuentes desde el panel: ICS, RSS/Atom, JSON, JSON-LD, Tribe API y Cultura API. Las fuentes activas requieren HTTPS; no se aceptan credenciales incrustadas en la URL.
- Configuración persistente separada del código mediante `RUA_CONFIG_DIR`; preparada para volúmenes Docker.
- Despliegue autohospedado con Docker Compose, servicio de recolección separado y volumen persistente.
- Copia de seguridad del volumen Docker mediante `deploy/docker-backup.sh`.
- Las operaciones administrativas requieren Bearer token; el panel solo conserva el token en `sessionStorage` de esa pestaña/sesión.
- 26 pruebas automatizadas, incluyendo autorización, validación de configuración, fuentes, categorías y persistencia.

### Panel de administración

1. Configura un token largo en `RUA_ADMIN_TOKEN`.
2. Arranca Rúa y abre `https://tu-dominio/admin.html`.
3. Introduce el token. El panel permite guardar la configuración, categorías y fuentes.
4. Para cambiar las fuentes, activa solo las que hayas probado. Una fuente con error no equivale a una agenda sin eventos.

Rutas administrativas protegidas:

- `GET /api/admin/config`
- `GET /api/admin/check`
- `PUT /api/admin/instance`
- `PUT /api/admin/categories`
- `PUT /api/admin/sources`

El token se envía mediante `Authorization: Bearer ...`. No se incluye en la URL ni en el HTML. Si `RUA_ADMIN_TOKEN` está vacío, la administración permanece deshabilitada.

### Instalación con Docker Compose

```bash
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
# Copia el token generado a RUA_ADMIN_TOKEN en .env y configura dominio/correo.
docker compose up -d --build
```

La web escucha solo en `127.0.0.1:8000` del host para colocarla detrás de Caddy, Nginx o Traefik. El volumen `rua-data` conserva SQLite y los JSON de configuración entre actualizaciones. El contenedor de recolección consulta las fuentes cada seis horas por defecto (`RUA_COLLECTOR_INTERVAL`).

Para generar las claves VAPID dentro del volumen persistente (opcional, para notificaciones web):

```bash
docker compose exec rua python push.py genkeys
```

Para copia de seguridad del volumen:

```bash
./deploy/docker-backup.sh
```

Para restaurar, detén los servicios y restaura el contenido del archivo comprimido en el volumen `rua-data`. No publiques el archivo `.env`, el volumen de datos ni las claves VAPID.

Para crear las claves VAPID en esta instalación: `sudo -u rua env RUA_CONFIG_DIR=/var/lib/rua /opt/rua/.venv/bin/python /opt/rua/push.py genkeys`. El panel no permite modificar código ni secretos del servidor. Las categorías y fuentes se validan antes de guardarse. La federación, el registro público y el cliente Android todavía no están implementados; los interruptores de preparación no activan esas funciones.

## Cambios de v3.4 Core

- Nuevo modelo universal `activities`, separado del esquema musical heredado `events`.
- Entidades, lugares, categorías múltiples y procedencia de cada fuente.
- Migración aditiva: los eventos musicales existentes se conservan en `events` y se proyectan en `activities`; no se elimina la tabla anterior.
- El estado del evento y el grado de verificación son campos distintos. Las actualizaciones de fuentes secundarias no degradan la verificación existente.
- Ámbito geográfico configurable en `instance.json`; las actividades genéricas se validan contra los municipios de la instancia, no contra una lista global fija.
- Nuevas rutas: `GET /api/activities`, `GET /api/categories`, `GET /api/instance` y `POST /api/activities` (administración autenticada).
- Los conectores pueden declarar `model: "activity"` y `category_ids` para enviar fichas al modelo generalista. Ejemplo: `examples-source-activity.json` (plantilla desactivada, no es una fuente real).
- El endpoint antiguo `/api/events` permanece disponible para no romper la PWA musical durante la transición.
- Pruebas de API, categorías múltiples, entidades, ámbito local y no degradación de verificación.

### Configuración territorial

`instance.json` contiene `geographic_mode`, `municipalities`, `default_radius_km` y `timezone`. Para una instancia local, se admiten actividades en los municipios configurados. `geographic_mode: "unrestricted"` elimina la lista de municipios, pero no se recomienda para una agenda comunitaria local.

### Conector genérico

Una fuente generalista debe declarar explícitamente sus categorías y municipio predeterminado cuando la página no proporciona una localidad inequívoca. No se clasifica automáticamente cualquier contenido como evento. Se puede consultar con `python collector.py --dry-run` antes de activar la escritura.


No necesita dependencias para web, API, RSS ni recolector. Para enviar push: `pip install -r requirements.txt`.

## Cambios de v3.3

- Catálogo ampliado de 1 a 63 artistas y grupos gallegos, con alias controlados, estilos y referencia documental por entrada.
- Detección de varios artistas en un mismo título; se conserva el nombre canónico y se deduplican coincidencias por alias.
- Nuevo lector JSON-LD de schema.org (`Event`, `MusicEvent`, `Festival`): extrae artistas, recinto, fecha, enlace y oferta de entradas. Incluye prueba automatizada.
- Preparadas como candidatas, pero desactivadas hasta validar su HTML real, las agendas de Turismo de Santiago, Turismo de Ourense y Oazis Vigo.
- Para evitar falsos cabezas de cartel, se priorizan las coincidencias del título y solo se analiza la descripción si el título no identifica artistas.
- Corregido el alias incorrecto que asociaba «Lil GZ» a Hard GZ.
- Pruebas de regresión para colaboraciones, alias y cobertura documental del catálogo.

## Cambios de v3.2

- Panel de salud de fuentes: registra cada ejecución, errores, eventos leídos, nuevos, actualizados y descartados.
- Endpoint `/api/status` para consultar la última ejecución de cada fuente sin exponer sus URL.
- La PWA actualiza la agenda al abrirse, al volver a primer plano y cada cinco minutos mientras está visible.
- Filtro geográfico más estricto: evita falsos positivos como Santiago de Chile y corrige topónimos acentuados (A Coruña, O Porriño, Moaña).
- Validación de enlaces de eventos: solo HTTPS, sin credenciales ni esquemas ejecutables.
- La deduplicación impide que una fuente secundaria rebaje un evento de confirmado a anunciado o no verificado.

## Cambios de v3.1

- Catálogo `artists.json`: detecta artistas aunque una ficha no escriba el género en el título. En v3.3 se amplía a 63 artistas/grupos y se admiten varias coincidencias por evento.
- Cada evento puede tener una fuente del evento y otra fuente independiente que acredita el estilo.
- Una ficha oficial puede quedar como **ANUNCIADO** sin que se marque como **CONFIRMADO**.
- La fecha de anuncio no se rellena con la fecha de recolección ni con la fecha de publicación. Solo se guarda cuando la fuente proporciona un campo explícito de anuncio. La preventa se guarda por separado.
- El filtro geográfico da prioridad a la localidad del recinto. Una mención a Vigo en el itinerario no convierte un recinto de Mos u O Porriño en un evento de Vigo.
- Conectores: ICS, RSS/Atom, JSON configurable, JSON-LD schema.org, API REST de The Events Calendar (Concertos do Xacobeo) y lector para la API JSON documentada de Axenda de Cultura (esta última queda desactivada hasta validar su disponibilidad HTTPS actual).
- Migración SQLite automática a esquema 5.
- El envío push ya no marca como notificados los eventos si no se pudo entregar ningún aviso; quedan pendientes para reintentar.
- Interfaz: muestra fuente del evento, fuente del estilo, fecha de anuncio/preventa y estado de verificación.

## Fuentes y recolector

La sección de estado de la PWA distingue fuentes correctas, pendientes y con error. Un error de consulta no equivale a una búsqueda sin resultados. Los registros se guardan en SQLite y se consultan en `/api/status`.

Las fuentes se configuran en `sources.json`. Las fuentes candidatas con lector JSON-LD se mantienen desactivadas hasta confirmar que publican eventos estructurados compatibles; no se presentan como fuentes activas.

```bash
python collector.py --dry-run     # no escribe ni notifica
python collector.py               # importa y notifica nuevos eventos
```

Fuentes activadas:

- **Concertos do Xacobeo**: endpoint REST de The Events Calendar (`/wp-json/tribe/events/v1/events`). Se limita a eventos futuros y después se aplica el filtro estricto de ciudad y estilo.
- **Axenda de Cultura de Galicia**: calendario ICS y RSS del portal oficial Open Data de la Xunta.

La API JSON antigua de Cultura está preparada, pero desactivada: el manual oficial describe `POST /services/abertos` y parámetros como `dini`, `dfin`, `concello`, `paxina` e `idioma`. En una prueba manual comunicada el 15/11/2026, el endpoint devolvió HTTP 403 tanto con el agente de usuario predeterminado como con `Rua-collector/4.0`, acompañado de una página HTML de error de Apache en vez de JSON. No se intenta eludir esa denegación: la fuente queda desactivada hasta que exista una vía pública autorizada y comprobable.

`ics.txt` no se crea automáticamente. Para guardar el ICS configurado y buscar texto en él:

```bash
python -c 'import json; from pathlib import Path; import collector; s=json.loads(Path("sources.json").read_text()); u=next(x["url"] for x in s if x.get("type")=="ics"); d=collector.fetch(u); Path("/tmp/rua-agenda.ics").write_bytes(d); print(f"Guardado: {len(d)} bytes")'
grep -Ei "Rango|Motivos|SIN estilo" /tmp/rua-agenda.ics | head -40
```

El lector de Concertos do Xacobeo usa la API pública estándar del plugin The Events Calendar; su respuesta real debe comprobarse con `--dry-run` en tu equipo antes de desplegar. No se importan como confirmados eventos que solo aparezcan en fichas agregadas. El lector JSON-LD está probado con fixtures locales, pero las tres agendas candidatas siguen desactivadas hasta validar su marcado real.

### Catálogo de artistas

`artists.json` contiene 63 entradas iniciales y acepta:

- `name`: nombre canónico.
- `aliases`: variantes de escritura.
- `styles`: estilos acreditados.
- `style_source_url`: fuente que acredita esos estilos.

Referencias iniciales del catálogo: [Orgullo Galego — música en galego](https://orgullogalego.gal/musica-en-galego/), [iAM R A P — escena gallega](https://www.iamrap.es/articulo/listas-musicales/rap-galicia-emergente-descubrir-2025/20250313163825088450.html), [RTVE — Rap desde Galicia](https://www.rtve.es/play/audios/hyperlevel/hyperlevel-rap-desde-galicia/16140537/) y [La Voz de Galicia — nuevas voces urbanas](https://www.lavozdegalicia.es/noticia/fugas/2025/12/05/span-langgl1spanspan-langgl2spanspan-langgl3spaneles-relevo-da-musica-urbana-galega/0003_202512SF5P1991.htm). Las entradas enlazan la referencia concreta usada para su clasificación.

Añade artistas emergentes y underground cuando haya una fuente razonable que permita acreditar su encaje. El catálogo solo ayuda a detectar artistas: no convierte por sí solo una ficha de evento en confirmación. Las coincidencias del título prevalecen; la descripción solo se usa como respaldo si no hay coincidencias en el título.

### Restricciones geográficas y de género

- Solo Ourense, Vigo y Santiago de Compostela.
- La localidad real del recinto prevalece sobre la ciudad mencionada en la descripción o en el itinerario de gira.
- No se infiere la fecha de anuncio a partir de `pubDate`, `updated`, `CREATED`, `DTSTAMP` o la fecha en que se ejecuta el recolector.
- El evento debe tener fecha futura, artista identificable, ciudad permitida y estilo acreditado por texto o catálogo.
- La deduplicación usa artista + ciudad + fecha, no la sala.

### Bandsintown y Songkick

No se hacen llamadas no autorizadas ni se simula que se han consultado. Según la documentación vigente, Bandsintown vincula por defecto cada clave a un artista y exige autorización expresa para usos de plataforma/multiartista; no concede claves públicas para rastrear cualquier artista. Songkick indica actualmente que no tramita nuevas claves para proyectos personales o de hobby y que el acceso de plataforma está sujeto a licencia/partnership. Por tanto, no se activan conectores ficticios ni scraping que incumpla sus condiciones. Referencias: [Bandsintown — acceso y condiciones](https://help.artists.bandsintown.com/en/articles/7053475-what-is-the-bandsintown-api), [Songkick — estado del acceso API](https://www.songkick.com/developer).

## Web Push

```bash
python push.py genkeys
export RUA_VAPID_SUBJECT="mailto:tu@correo.es"
```

- Push requiere HTTPS público o localhost.
- Abre la PWA y pulsa **ACTIVAR AVISOS**.
- Antes del primer envío, ejecuta `python push.py notify --mark-only` si ya hay eventos antiguos en la base de datos.
- Sin novedades no se envía aviso. Si no se puede entregar ningún push, los eventos no se marcan como notificados.
- Prueba extremo a extremo en Android pendiente de un despliegue HTTPS real.

## Despliegue

1. Copia el proyecto a `/opt/rua`.
2. Crea entorno: `python -m venv .venv && .venv/bin/pip install -r requirements.txt`.
3. Configura `/etc/rua.env` con permisos 600: `RUA_ADMIN_TOKEN`, `RUA_BASE_URL=https://rua.tudominio.es`, `RUA_VAPID_SUBJECT`, `RUA_CONFIG_DIR=/var/lib/rua` y `RUA_DB=/var/lib/rua/rua.sqlite3`.
4. Instala `deploy/*.service` y `deploy/rua-collector.timer` en `/etc/systemd/system/`.
5. `StateDirectory=rua` crea `/var/lib/rua` con propietario del servicio.
6. `systemctl enable --now rua.service rua-collector.timer`.
7. Configura Caddy con `deploy/Caddyfile`.

El temporizador del recolector está configurado cada seis horas para detectar anuncios con antelación. El servidor integrado es para uso personal detrás de un proxy inverso.

## Seguridad

- Solo se sirve `public/`; no se exponen SQLite ni el código.
- `RUA_ADMIN_TOKEN` protege la administración y la importación por API.
- En producción, usa HTTPS delante de Rúa y un token aleatorio largo; no expongas directamente el puerto del servidor.
- No subas `vapid_private.pem` ni `rua.sqlite3`. La clave VAPID se guarda en `RUA_CONFIG_DIR/vapid_private.pem` (por defecto, junto a la configuración).
- `/api/push/subscribe` es público y tiene límite configurable (`RUA_MAX_SUBSCRIPTIONS`, 500 por defecto).

## Importación manual

```bash
python server.py import eventos-ejemplo.json
```

## Cliente Android (0.1.0 en desarrollo)

El cliente Android nativo está en `android/`. Reutiliza `GET /api/activities`, no requiere cambiar el backend y no incorpora Firebase ni servicios propietarios. Incluye filtros, búsqueda y avisos locales mediante WorkManager cada seis horas aproximadamente. La primera sincronización de avisos crea una línea base silenciosa. Requiere servidor HTTPS. Instrucciones y limitaciones en `android/README.md`.
