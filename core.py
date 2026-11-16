"""Rúa core: SQLite, validación, deduplicación y RSS. Solo biblioteca estándar."""
from pathlib import Path
from datetime import date, datetime, timezone
from email.utils import format_datetime
from urllib.parse import urlsplit
import sqlite3, os, hashlib, html, re, unicodedata
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("RUA_DB", ROOT / "rua.sqlite3"))
CONFIG_DIR = Path(os.environ.get("RUA_CONFIG_DIR", ROOT))
BASE_URL = os.environ.get("RUA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CITIES = {"Ourense", "Vigo", "Santiago de Compostela"}
STYLES = {"Rap", "Trap", "Drill", "Underground", "Rap gallego"}
TYPES = {"Concierto", "Sesión / fiesta", "Festival"}
STATUSES = {"confirmed", "announced", "unverified"}
FIELDS = ("artist", "city", "venue", "date", "style", "type", "status", "source",
          "source_url", "ticket_url", "announced_at", "presale_at", "style_source_url", "notes")
SCHEMA_VERSION = 9


@contextmanager
def connect():
    """Conexión SQLite con commit/rollback y cierre garantizado."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.strip().lower())


def config_path(name):
    """Ruta de configuración persistente, separada del código para facilitar autohospedaje."""
    return CONFIG_DIR / name


def get_instance_config():
    """Configuración local de la instancia; no contiene límites geográficos en el código."""
    import json
    path = config_path("instance.json")
    defaults = {
        "name": "Rúa", "description": "Agenda local abierta y autogestionada",
        "geographic_mode": "local", "municipalities": [], "default_radius_km": 25,
        "timezone": "Europe/Madrid", "allow_public_registration": False,
        "federation_enabled": False,
    }
    if not path.exists():
        return defaults
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("instance.json debe contener un objeto JSON")
    merged = {**defaults, **data}
    if merged["geographic_mode"] not in ("local", "regional", "unrestricted"):
        raise ValueError("geographic_mode no válido en instance.json")
    if not isinstance(merged.get("municipalities"), list) or any(not isinstance(x, str) or not x.strip() for x in merged["municipalities"]):
        raise ValueError("municipalities debe ser una lista de localidades")
    merged["municipalities"] = list(dict.fromkeys(x.strip() for x in merged["municipalities"]))
    return merged


def municipality_allowed(name):
    config = get_instance_config()
    if config["geographic_mode"] == "unrestricted":
        return True
    allowed = {norm(x) for x in config.get("municipalities", [])}
    return bool(allowed and norm(name) in allowed)


def fingerprint(event):
    # Sin sala: el mismo concierto con la sala escrita distinto no se duplica.
    raw = "|".join(norm(event[k]) for k in ("artist", "city", "date"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def init_db():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          fingerprint TEXT NOT NULL UNIQUE,
          artist TEXT NOT NULL, city TEXT NOT NULL,
          venue TEXT NOT NULL DEFAULT '', date TEXT NOT NULL,
          style TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'Concierto',
          status TEXT NOT NULL DEFAULT 'announced',
          source TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
          ticket_url TEXT NOT NULL DEFAULT '', announced_at TEXT NOT NULL DEFAULT '',
          presale_at TEXT NOT NULL DEFAULT '', style_source_url TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        cols = {r["name"] for r in db.execute("PRAGMA table_info(events)")}
        if "notified_at" not in cols:
            db.execute("ALTER TABLE events ADD COLUMN notified_at TEXT")
        if "presale_at" not in cols:
            db.execute("ALTER TABLE events ADD COLUMN presale_at TEXT NOT NULL DEFAULT ''")
        if "style_source_url" not in cols:
            db.execute("ALTER TABLE events ADD COLUMN style_source_url TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON events(date)")
        db.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
          endpoint TEXT PRIMARY KEY, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
          created_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS source_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
          source_type TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
          fetched INTEGER NOT NULL DEFAULT 0, inserted INTEGER NOT NULL DEFAULT 0,
          updated INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
          error TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL, finished_at TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_source_runs_name ON source_runs(source, id DESC)")
        # Núcleo generalista: se añade sin eliminar ni renombrar las tablas heredadas.
        db.executescript("""
          CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT REFERENCES categories(id),
            enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, entity_type TEXT NOT NULL,
            canonical_url TEXT NOT NULL DEFAULT '', UNIQUE(name, entity_type));
          CREATE TABLE IF NOT EXISTS venues (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, municipality TEXT NOT NULL,
            address TEXT NOT NULL DEFAULT '', latitude REAL, longitude REAL,
            UNIQUE(name, municipality));
          CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            municipality TEXT NOT NULL, venue_id INTEGER REFERENCES venues(id),
            starts_at TEXT NOT NULL, ends_at TEXT NOT NULL DEFAULT '',
            announced_at TEXT NOT NULL DEFAULT '', registration_opens_at TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT 'event', status TEXT NOT NULL DEFAULT 'scheduled',
            verification TEXT NOT NULL DEFAULT 'unverified',
            source_url TEXT NOT NULL DEFAULT '', ticket_url TEXT NOT NULL DEFAULT '',
            legacy_event_id INTEGER UNIQUE REFERENCES events(id),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS activity_categories (
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            category_id TEXT NOT NULL REFERENCES categories(id),
            PRIMARY KEY(activity_id, category_id));
          CREATE TABLE IF NOT EXISTS activity_entities (
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            entity_id INTEGER NOT NULL REFERENCES entities(id),
            role TEXT NOT NULL DEFAULT 'participant',
            PRIMARY KEY(activity_id, entity_id, role));
          CREATE TABLE IF NOT EXISTS activity_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            source_name TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '',
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            UNIQUE(activity_id, source_name, source_url));
          CREATE TABLE IF NOT EXISTS user_interests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_key TEXT NOT NULL,
            category_id TEXT NOT NULL REFERENCES categories(id),
            UNIQUE(user_key, category_id));
          CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(starts_at);
          CREATE INDEX IF NOT EXISTS idx_activities_municipality ON activities(municipality);
          CREATE INDEX IF NOT EXISTS idx_activity_sources_activity ON activity_sources(activity_id);
        """)
        activity_cols = {r["name"] for r in db.execute("PRAGMA table_info(activities)")}
        if "announced_at" not in activity_cols:
            db.execute("ALTER TABLE activities ADD COLUMN announced_at TEXT NOT NULL DEFAULT ''")
        if "registration_opens_at" not in activity_cols:
            db.execute("ALTER TABLE activities ADD COLUMN registration_opens_at TEXT NOT NULL DEFAULT ''")
        # Semillas idempotentes de categorías. El fichero es la taxonomía inicial editable.
        import json
        category_file = config_path("categories.json")
        if not category_file.exists():
            category_file = ROOT / "categories.json"
        if category_file.exists():
            for category in json.loads(category_file.read_text(encoding="utf-8")):
                db.execute("INSERT OR IGNORE INTO categories(id,name,parent_id,enabled,created_at) VALUES(?,?,?,?,?)",
                           (category["id"], category["name"], category.get("parent_id"),
                            int(category.get("enabled", True)), datetime.now(timezone.utc).isoformat(timespec="seconds")))
        # Conserva los eventos musicales existentes y los expone también en el modelo universal.
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        legacy_rows = db.execute("SELECT * FROM events").fetchall()
        for row in legacy_rows:
            category = "rap" if norm(row["style"]) in ("rap", "trap", "drill", "underground", "rap gallego") else "musica"
            fp = hashlib.sha256("|".join((norm(row["artist"]), norm(row["city"]), norm(row["date"]))).encode()).hexdigest()
            cur = db.execute("""INSERT OR IGNORE INTO activities
              (fingerprint,title,description,municipality,starts_at,announced_at,registration_opens_at,
               event_type,status,verification,source_url,ticket_url,legacy_event_id,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (fp, row["artist"], row["notes"], row["city"], row["date"], row["announced_at"], row["presale_at"],
               row["type"], "scheduled", {"confirmed": "official", "announced": "single_source"}.get(row["status"], "unverified"),
               row["source_url"], row["ticket_url"], row["id"],
               row["created_at"] or now, row["updated_at"] or now))
            activity = db.execute("SELECT id FROM activities WHERE fingerprint=?", (fp,)).fetchone()
            if activity:
                # Completa también las filas ya proyectadas por el esquema v8 al añadir fechas de anuncio/preventa.
                db.execute("""UPDATE activities SET
                  announced_at=CASE WHEN announced_at='' THEN ? ELSE announced_at END,
                  registration_opens_at=CASE WHEN registration_opens_at='' THEN ? ELSE registration_opens_at END,
                  status=CASE WHEN status IN ('confirmed','announced','unverified') THEN 'scheduled' ELSE status END,
                  verification=CASE WHEN verification='confirmed' THEN 'official'
                                    WHEN verification='announced' THEN 'single_source' ELSE verification END
                  WHERE id=?""", (row["announced_at"], row["presale_at"], activity["id"]))
                db.execute("INSERT OR IGNORE INTO activity_categories(activity_id,category_id) VALUES(?,?)",
                           (activity["id"], category))
                if row["source"]:
                    db.execute("INSERT OR IGNORE INTO activity_sources(activity_id,source_name,source_url,first_seen,last_seen) VALUES(?,?,?,?,?)",
                               (activity["id"], row["source"], row["source_url"], row["created_at"] or now, row["updated_at"] or now))
        if db.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            # Migración de v2: huella nueva (sin sala). Si dos filas chocan, se conserva la más antigua.
            for r in db.execute("SELECT id, artist, city, date FROM events ORDER BY id").fetchall():
                fp = fingerprint(dict(r))
                try:
                    db.execute("UPDATE events SET fingerprint=? WHERE id=?", (fp, r["id"]))
                except sqlite3.IntegrityError:
                    db.execute("DELETE FROM events WHERE id=?", (r["id"],))
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def validate_event(data):
    if not isinstance(data, dict):
        raise ValueError("El evento debe ser un objeto JSON.")
    for key in ("artist", "city", "date", "style"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"Falta el campo obligatorio: {key}")
    ev = {k: str(data.get(k) or "").strip() for k in FIELDS}
    if ev["city"] not in CITIES:
        raise ValueError("Ciudad no permitida. Solo Ourense, Vigo o Santiago de Compostela.")
    if ev["style"] not in STYLES:
        raise ValueError("Estilo no permitido.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ev["date"]):
        raise ValueError("La fecha debe tener formato YYYY-MM-DD.")
    date.fromisoformat(ev["date"])
    ev["type"] = ev["type"] or "Concierto"
    if ev["type"] not in TYPES:
        raise ValueError("Tipo de evento no permitido.")
    ev["status"] = ev["status"] or "announced"
    if ev["status"] not in STATUSES:
        raise ValueError("Estado no válido.")
    for key in ("source_url", "ticket_url", "style_source_url"):
        if ev[key]:
            parsed = urlsplit(ev[key])
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f"{key} debe ser una URL HTTPS válida y sin credenciales.")
    return ev


def upsert_event(data):
    """Devuelve (id, creado). En actualizaciones, un valor vacío no borra el existente."""
    ev = validate_event(data)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fp = fingerprint(ev)
    with connect() as db:
        old = db.execute("SELECT * FROM events WHERE fingerprint=?", (fp,)).fetchone()
        if old:
            merged = {k: (ev[k] or old[k]) for k in FIELDS}
            # Una fuente secundaria no puede rebajar el estado probatorio ya alcanzado.
            rank = {"unverified": 0, "announced": 1, "confirmed": 2}
            if rank[old["status"]] > rank[merged["status"]]:
                merged["status"] = old["status"]
            # Conserva una fuente de acreditación específica si la nueva ficha no aporta otra.
            if old["style_source_url"] and not ev["style_source_url"]:
                merged["style_source_url"] = old["style_source_url"]
            sets = ",".join(f"{k}=?" for k in FIELDS)
            db.execute(f"UPDATE events SET {sets},updated_at=? WHERE id=?",
                       (*[merged[k] for k in FIELDS], now, old["id"]))
            return old["id"], False
        cols = ",".join(FIELDS)
        cur = db.execute(
            f"INSERT INTO events (fingerprint,{cols},created_at,updated_at) VALUES (?,{','.join('?'*len(FIELDS))},?,?)",
            (fp, *[ev[k] for k in FIELDS], now, now))
        return cur.lastrowid, True


def get_events():
    with connect() as db:
        rows = db.execute("SELECT * FROM events WHERE date >= ? ORDER BY date, artist",
                          (date.today().isoformat(),)).fetchall()
        return [dict(r) for r in rows]


def record_source_run(source, source_type, status, fetched=0, inserted=0, updated=0,
                      skipped=0, error="", started_at=None):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started_at = started_at or now
    with connect() as db:
        db.execute("""INSERT INTO source_runs
          (source,source_type,status,fetched,inserted,updated,skipped,error,started_at,finished_at)
          VALUES (?,?,?,?,?,?,?,?,?,?)""",
          (source, source_type, status, int(fetched), int(inserted), int(updated), int(skipped),
           str(error)[:500], started_at, now))


def get_source_status():
    import json
    cfg = config_path("sources.json")
    if not cfg.exists(): cfg = ROOT / "sources.json"
    sources = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else []
    with connect() as db:
        latest = {}
        for row in db.execute("SELECT * FROM source_runs ORDER BY id DESC"):
            latest.setdefault(row["source"], dict(row))
    result = []
    for src in sources:
        row = latest.get(src.get("name", ""), {})
        result.append({
            "name": src.get("name", "Fuente"), "type": src.get("type", ""),
            "enabled": bool(src.get("enabled", True)),
            "status": row.get("status", "pending"), "last_checked": row.get("finished_at", ""),
            "fetched": row.get("fetched", 0), "inserted": row.get("inserted", 0),
            "updated": row.get("updated", 0), "skipped": row.get("skipped", 0),
            "error": row.get("error", ""), "disabled_reason": src.get("disabled_reason", "")
        })
    return result


def _rfc822(iso):
    try:
        d = datetime.fromisoformat(iso)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
    except ValueError:
        d = datetime.now(timezone.utc)
    return format_datetime(d)


def rss_feed():
    """Feed ordenado por fecha de detección (lo más nuevo primero)."""
    with connect() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM events WHERE date >= ? ORDER BY created_at DESC, id DESC LIMIT 100",
            (date.today().isoformat(),))]
    labels = {"confirmed": "Confirmado", "announced": "Anunciado", "unverified": "Sin verificar"}
    items = []
    for e in rows:
        title = f'{e["artist"]} — {e["city"]} ({e["date"]})'
        desc = (f'{e["style"]} · {e["type"]} · {e["venue"] or "sala por anunciar"} · '
                f'{labels[e["status"]]}. Fuente: {e["source"] or "sin indicar"}.')
        link = e["source_url"] or e["ticket_url"] or BASE_URL + "/"
        items.append(
            f"<item><title>{html.escape(title)}</title>"
            f"<description>{html.escape(desc)}</description>"
            f"<link>{html.escape(link)}</link>"
            f'<guid isPermaLink="false">urn:rua:event:{e["fingerprint"]}</guid>'
            f"<pubDate>{_rfc822(e['created_at'])}</pubDate></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
            "<title>Rúa — Rap en Galicia</title>"
            f"<link>{html.escape(BASE_URL)}/</link>"
            f'<atom:link href="{html.escape(BASE_URL)}/feed.xml" rel="self" type="application/rss+xml"/>'
            "<description>Rap, trap, drill y underground en Ourense, Vigo y Santiago de Compostela.</description>"
            "<language>es</language>"
            f"<lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>"
            f"{''.join(items)}</channel></rss>")


def get_categories():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id,name,parent_id,enabled FROM categories WHERE enabled=1 ORDER BY COALESCE(parent_id,''),name")]


def activity_fingerprint(data):
    raw = "|".join((norm(data["title"]), norm(data["municipality"]), norm(data["starts_at"][:10])))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_activity(data):
    if not isinstance(data, dict):
        raise ValueError("La actividad debe ser un objeto JSON.")
    required = ("title", "municipality", "starts_at")
    for key in required:
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"Falta el campo obligatorio: {key}")
    raw_categories = data.get("category_ids") or ([data.get("category_id")] if data.get("category_id") else [])
    if not isinstance(raw_categories, list) or not raw_categories or any(not isinstance(x, str) or not x.strip() for x in raw_categories):
        raise ValueError("Indica al menos una categoría en category_id o category_ids.")
    ev = {k: str(data.get(k) or "").strip() for k in (
        "title", "description", "municipality", "venue", "address", "starts_at", "ends_at",
        "event_type", "status", "verification", "source_name", "source_url", "ticket_url", "category_id",
        "announced_at", "registration_opens_at")}
    ev["category_ids"] = list(dict.fromkeys(x.strip() for x in raw_categories))
    ev["entities"] = data.get("entities", [])
    if not isinstance(ev["entities"], list):
        raise ValueError("entities debe ser una lista")
    if not municipality_allowed(ev["municipality"]):
        raise ValueError("Localidad fuera del ámbito configurado para esta instancia.")
    if len(ev["title"]) > 300 or len(ev["description"]) > 12000:
        raise ValueError("Título o descripción demasiado largos.")
    try:
        datetime.fromisoformat(ev["starts_at"].replace("Z", "+00:00"))
    except ValueError:
        try: date.fromisoformat(ev["starts_at"])
        except ValueError: raise ValueError("starts_at debe ser una fecha ISO o fecha-hora ISO.")
    if ev["ends_at"]:
        try: datetime.fromisoformat(ev["ends_at"].replace("Z", "+00:00"))
        except ValueError:
            try: date.fromisoformat(ev["ends_at"])
            except ValueError: raise ValueError("ends_at debe ser una fecha ISO o fecha-hora ISO.")
    for field in ("announced_at", "registration_opens_at"):
        if ev[field]:
            try: datetime.fromisoformat(ev[field].replace("Z", "+00:00"))
            except ValueError:
                try: date.fromisoformat(ev[field])
                except ValueError: raise ValueError(f"{field} debe ser una fecha ISO o fecha-hora ISO.")
    if len(ev["category_ids"]) > 12 or len(ev["entities"]) > 50:
        raise ValueError("Demasiadas categorías o entidades asociadas a una actividad.")
    if ev["status"] and ev["status"] not in ("scheduled", "cancelled", "postponed", "completed"):
        raise ValueError("Estado de actividad no válido.")
    if ev["verification"] and ev["verification"] not in ("official", "multiple_sources", "single_source", "unverified"):
        raise ValueError("Grado de verificación no válido.")
    for key in ("source_url", "ticket_url"):
        if ev[key]:
            parsed = urlsplit(ev[key])
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f"{key} debe ser una URL HTTPS válida y sin credenciales.")
    return ev


def upsert_activity(data):
    """Inserta/actualiza eventos genéricos, categorías, entidades y procedencias."""
    ev = validate_activity(data)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fp = activity_fingerprint(ev)
    with connect() as db:
        placeholders = ",".join("?" for _ in ev["category_ids"])
        categories = db.execute(f"SELECT id FROM categories WHERE enabled=1 AND id IN ({placeholders})", ev["category_ids"]).fetchall()
        valid_categories = {r["id"] for r in categories}
        missing = [x for x in ev["category_ids"] if x not in valid_categories]
        if missing:
            raise ValueError("Categoría inexistente o desactivada: " + ", ".join(missing))
        venue_id = None
        if ev["venue"]:
            db.execute("INSERT OR IGNORE INTO venues(name,municipality,address) VALUES(?,?,?)",
                       (ev["venue"], ev["municipality"], ev["address"]))
            venue_id = db.execute("SELECT id FROM venues WHERE name=? AND municipality=?",
                                  (ev["venue"], ev["municipality"])).fetchone()["id"]
        old = db.execute("SELECT * FROM activities WHERE fingerprint=?", (fp,)).fetchone()
        if old:
            # Una fuente secundaria nunca degrada la confirmación ni la verificación.
            status_rank = {"scheduled": 1, "postponed": 2, "cancelled": 3, "completed": 4}
            verification_rank = {"unverified": 0, "single_source": 1, "multiple_sources": 2, "official": 3}
            old_status, new_status = old["status"], ev["status"] or old["status"]
            old_ver, new_ver = old["verification"], ev["verification"] or old["verification"]
            if status_rank.get(old_status, 0) > status_rank.get(new_status, 0):
                new_status = old_status
            if verification_rank.get(old_ver, 0) > verification_rank.get(new_ver, 0):
                new_ver = old_ver
            db.execute("""UPDATE activities SET description=CASE WHEN ?='' THEN description ELSE ? END,
              venue_id=COALESCE(?,venue_id),ends_at=CASE WHEN ?='' THEN ends_at ELSE ? END,
              announced_at=CASE WHEN ?='' THEN announced_at ELSE ? END,
              registration_opens_at=CASE WHEN ?='' THEN registration_opens_at ELSE ? END,
              status=?, verification=?, source_url=CASE WHEN ?='' THEN source_url ELSE ? END,
              ticket_url=CASE WHEN ?='' THEN ticket_url ELSE ? END,updated_at=? WHERE id=?""",
              (ev["description"],ev["description"],venue_id,ev["ends_at"],ev["ends_at"],
               ev["announced_at"],ev["announced_at"],ev["registration_opens_at"],ev["registration_opens_at"],
               new_status,new_ver,ev["source_url"],ev["source_url"],ev["ticket_url"],ev["ticket_url"],now,old["id"]))
            activity_id, created = old["id"], False
        else:
            cur = db.execute("""INSERT INTO activities
              (fingerprint,title,description,municipality,venue_id,starts_at,ends_at,announced_at,registration_opens_at,
               event_type,status,verification,source_url,ticket_url,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (fp,ev["title"],ev["description"],ev["municipality"],venue_id,ev["starts_at"],ev["ends_at"],
               ev["announced_at"],ev["registration_opens_at"],ev["event_type"] or "event",
               ev["status"] or "scheduled",ev["verification"] or "unverified",
               ev["source_url"],ev["ticket_url"],now,now))
            activity_id, created = cur.lastrowid, True
        for category_id in ev["category_ids"]:
            db.execute("INSERT OR IGNORE INTO activity_categories(activity_id,category_id) VALUES(?,?)",
                       (activity_id, category_id))
        for entity in ev["entities"]:
            if isinstance(entity, str):
                entity = {"name": entity, "entity_type": "other"}
            if not isinstance(entity, dict) or not str(entity.get("name", "")).strip():
                raise ValueError("Cada entidad debe tener un nombre")
            name = str(entity["name"]).strip()[:200]
            entity_type = str(entity.get("entity_type", "other")).strip().lower()[:40] or "other"
            canonical_url = str(entity.get("canonical_url", "")).strip()
            if canonical_url:
                parsed = urlsplit(canonical_url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("canonical_url debe ser HTTPS y no contener credenciales")
            db.execute("INSERT OR IGNORE INTO entities(name,entity_type,canonical_url) VALUES(?,?,?)",
                       (name, entity_type, canonical_url))
            entity_id = db.execute("SELECT id FROM entities WHERE name=? AND entity_type=?", (name, entity_type)).fetchone()["id"]
            db.execute("INSERT OR IGNORE INTO activity_entities(activity_id,entity_id,role) VALUES(?,?,?)",
                       (activity_id, entity_id, str(entity.get("role", "participant"))[:40]))
        if ev["source_name"]:
            db.execute("""INSERT INTO activity_sources(activity_id,source_name,source_url,first_seen,last_seen)
              VALUES(?,?,?,?,?) ON CONFLICT(activity_id,source_name,source_url) DO UPDATE SET last_seen=excluded.last_seen""",
              (activity_id,ev["source_name"],ev["source_url"],now,now))
        return activity_id, created


def get_activities(limit=500):
    with connect() as db:
        rows = db.execute("""SELECT a.*,v.name AS venue,v.address,
          GROUP_CONCAT(DISTINCT c.id) AS category_ids,GROUP_CONCAT(DISTINCT c.name) AS categories
          FROM activities a LEFT JOIN venues v ON v.id=a.venue_id
          LEFT JOIN activity_categories ac ON ac.activity_id=a.id
          LEFT JOIN categories c ON c.id=ac.category_id
          WHERE substr(a.starts_at,1,10)>=? GROUP BY a.id ORDER BY a.starts_at,a.title LIMIT ?""",
          (date.today().isoformat(), max(1, min(int(limit), 1000)))).fetchall()
        result = [dict(r) for r in rows]
        for item in result:
            item["category_ids"] = item["category_ids"].split(",") if item["category_ids"] else []
            item["categories"] = item["categories"].split(",") if item["categories"] else []
            item["entities"] = [dict(x) for x in db.execute("""SELECT e.name,e.entity_type,ae.role,e.canonical_url
                FROM activity_entities ae JOIN entities e ON e.id=ae.entity_id WHERE ae.activity_id=? ORDER BY e.name""", (item["id"],))]
            item["sources"] = [dict(x) for x in db.execute("SELECT source_name,source_url,first_seen,last_seen FROM activity_sources WHERE activity_id=? ORDER BY source_name", (item["id"],))]
        return result
