#!/usr/bin/env python3
"""Rúa: servidor HTTP (PWA + API + RSS + suscripciones push). Solo sirve ./public."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json, os, sys, hmac, re, shutil
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import core, push

PUBLIC = core.ROOT / "public"
HOST = os.environ.get("RUA_HOST", "127.0.0.1")
PORT = int(os.environ.get("RUA_PORT", "8000"))
ADMIN_TOKEN = os.environ.get("RUA_ADMIN_TOKEN", "")
MAX_SUBS = int(os.environ.get("RUA_MAX_SUBSCRIPTIONS", "500"))
SOURCE_TYPES = {"ics", "rss", "atom", "json", "jsonld", "tribe_api", "cultura_api"}


def ensure_config_files():
    """Inicializa el volumen de configuración sin sobrescribir decisiones del administrador."""
    core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("instance.json", "sources.json", "categories.json", "profile.json", "venues.json"):
        target = core.config_path(name)
        source = core.ROOT / name
        if not target.exists() and source.exists():
            shutil.copyfile(source, target)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def validate_instance(data):
    if not isinstance(data, dict):
        raise ValueError("La configuración debe ser un objeto JSON.")
    current = core.get_instance_config()
    allowed = {"name", "description", "geographic_mode", "municipalities", "default_radius_km", "timezone", "allow_public_registration", "federation_enabled", "municipality_aliases", "provinces"}
    if set(data) - allowed:
        raise ValueError("Hay campos de configuración desconocidos.")
    cfg = {**current, **data}
    cfg["name"] = str(cfg["name"]).strip()[:80]
    cfg["description"] = str(cfg["description"]).strip()[:240]
    if not cfg["name"]:
        raise ValueError("El nombre de la instancia no puede estar vacío.")
    if cfg["geographic_mode"] not in ("local", "regional", "unrestricted"):
        raise ValueError("Ámbito geográfico no válido.")
    municipalities = cfg.get("municipalities")
    if not isinstance(municipalities, list) or len(municipalities) > 500:
        raise ValueError("Municipios debe ser una lista de hasta 500 elementos.")
    if any(not isinstance(x, str) or not x.strip() or len(x.strip()) > 100 for x in municipalities):
        raise ValueError("Hay un municipio vacío o demasiado largo.")
    cfg["municipalities"] = list(dict.fromkeys(x.strip() for x in municipalities))
    if cfg["geographic_mode"] != "unrestricted" and not cfg["municipalities"]:
        raise ValueError("Una instancia local o regional necesita al menos un municipio.")
    try:
        radius = float(cfg["default_radius_km"])
    except (TypeError, ValueError):
        raise ValueError("El radio debe ser numérico.")
    if not 0 <= radius <= 500:
        raise ValueError("El radio debe estar entre 0 y 500 km.")
    cfg["default_radius_km"] = radius
    try:
        ZoneInfo(str(cfg["timezone"]))
    except Exception:
        raise ValueError("Zona horaria no reconocida.")
    for key in ("allow_public_registration", "federation_enabled"):
        if not isinstance(cfg[key], bool):
            raise ValueError(f"{key} debe ser booleano.")
    if not isinstance(cfg.get("municipality_aliases", {}), dict) or any(
            not isinstance(k, str) or not isinstance(x, str) for k, x in cfg.get("municipality_aliases", {}).items()):
        raise ValueError("municipality_aliases debe ser un objeto {alias: municipio}.")
    if not isinstance(cfg.get("provinces", []), list) or any(not isinstance(x, str) for x in cfg.get("provinces", [])):
        raise ValueError("provinces debe ser una lista de nombres.")
    return cfg


def validate_sources(data):
    if not isinstance(data, list) or len(data) > 200:
        raise ValueError("Las fuentes deben ser una lista de hasta 200 elementos.")
    out, names = [], set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Fuente {i + 1}: debe ser un objeto.")
        src = dict(item)
        name = str(src.get("name", "")).strip()
        kind = str(src.get("type", "")).strip()
        if not name or len(name) > 120:
            raise ValueError(f"Fuente {i + 1}: nombre vacío o demasiado largo.")
        if name.casefold() in names:
            raise ValueError(f"Nombre de fuente duplicado: {name}")
        names.add(name.casefold())
        if kind not in SOURCE_TYPES:
            raise ValueError(f"{name}: tipo no admitido ({kind}).")
        url = str(src.get("url", "")).strip()
        if src.get("enabled", True) and not url:
            raise ValueError(f"{name}: una fuente activa necesita URL.")
        if url:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f"{name}: la URL debe ser HTTPS y no contener credenciales.")
        if not isinstance(src.get("enabled", True), bool):
            raise ValueError(f"{name}: enabled debe ser booleano.")
        if src.get("status", "unverified") not in ("confirmed", "announced", "unverified"):
            raise ValueError(f"{name}: estado de verificación no válido.")
        if src.get("model", "event") not in ("event", "activity"):
            raise ValueError(f"{name}: model debe ser event o activity.")
        if "category_ids" in src and (not isinstance(src["category_ids"], list) or any(not isinstance(x, str) for x in src["category_ids"])):
            raise ValueError(f"{name}: category_ids debe ser una lista de identificadores.")
        out.append(src)
    return out


def validate_categories(data):
    if not isinstance(data, list) or len(data) > 300:
        raise ValueError("Las categorías deben ser una lista de hasta 300 elementos.")
    out, ids = [], set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Categoría {i + 1}: formato incorrecto.")
        cid = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        parent = item.get("parent_id") or None
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,59}", cid):
            raise ValueError(f"Identificador de categoría no válido: {cid}")
        if cid in ids:
            raise ValueError(f"Identificador duplicado: {cid}")
        if not name or len(name) > 80:
            raise ValueError(f"Nombre no válido para categoría {cid}.")
        if parent is not None and not isinstance(parent, str):
            raise ValueError(f"Categoría {cid}: parent_id no válido.")
        if not isinstance(item.get("enabled", True), bool):
            raise ValueError(f"Categoría {cid}: enabled debe ser booleano.")
        ids.add(cid)
        out.append({"id": cid, "name": name, "parent_id": parent, "enabled": item.get("enabled", True)})
    by_id = {x["id"]: x for x in out}
    for item in out:
        if item["parent_id"] and item["parent_id"] not in by_id:
            raise ValueError(f"Categoría {item['id']}: no existe su categoría padre.")
        seen, cur = set(), item["id"]
        while cur:
            if cur in seen:
                raise ValueError("La jerarquía de categorías contiene un ciclo.")
            seen.add(cur)
            cur = by_id[cur]["parent_id"]
    return out


def admin_categories():
    with core.connect() as db:
        return [{**dict(r), "enabled": bool(r["enabled"])} for r in db.execute("SELECT id,name,parent_id,enabled FROM categories ORDER BY COALESCE(parent_id,''),name")]


def save_categories(data):
    categories = validate_categories(data)
    current = {x["id"]: x for x in admin_categories()}
    submitted = {x["id"]: x for x in categories}
    # Las categorías ya utilizadas no se borran: quedan desactivadas para preservar referencias.
    for cid, old in current.items():
        if cid not in submitted:
            categories.append({"id": cid, "name": old["name"], "parent_id": old["parent_id"], "enabled": False})
    ids = {x["id"] for x in categories}
    for item in categories:
        if item["parent_id"] and item["parent_id"] not in ids:
            raise ValueError(f"Categoría {item['id']}: categoría padre desconocida.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with core.connect() as db:
        for item in categories:
            db.execute("""INSERT INTO categories(id,name,parent_id,enabled,created_at) VALUES(?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET name=excluded.name,parent_id=excluded.parent_id,enabled=excluded.enabled""",
              (item["id"], item["name"], item["parent_id"], int(item["enabled"]), now))
    atomic_json(core.config_path("categories.json"), categories)
    return categories


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PUBLIC), **kw)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        super().end_headers()

    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, limit=1_000_000):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > limit:
            raise ValueError("Tamaño de petición no válido.")
        return json.loads(self.rfile.read(length))

    def is_admin(self):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return bool(ADMIN_TOKEN) and hmac.compare_digest(token.encode(), ADMIN_TOKEN.encode())

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/admin/check":
            if not self.is_admin(): return self.send_json(403, {"error": "Token de administración incorrecto."})
            return self.send_json(200, {"ok": True})
        if path.startswith("/api/admin/"):
            if not self.is_admin(): return self.send_json(403, {"error": "Autenticación de administración requerida."})
            if path == "/api/admin/review":
                try:
                    state = parse_qs(urlparse(self.path).query).get("state", ["pending"])[0]
                    return self.send_json(200, {"activities": core.review_list(state)})
                except ValueError as exc:
                    return self.send_json(400, {"error": str(exc)})
            if path == "/api/admin/config":
                try:
                    sources_path = core.config_path("sources.json")
                    if not sources_path.exists(): sources_path = core.ROOT / "sources.json"
                    sources = json.loads(sources_path.read_text(encoding="utf-8")) if sources_path.exists() else []
                    return self.send_json(200, {"instance": core.get_instance_config(), "sources": sources, "categories": admin_categories()})
                except Exception as exc:
                    return self.send_json(500, {"error": f"No se pudo leer la configuración: {exc}"})
            return self.send_json(404, {"error": "Ruta de administración no encontrada."})
        if path == "/api/health":
            return self.send_json(200, {"ok": True, "service": "rua", "push": push.available()})
        if path == "/api/status":
            sources = core.get_source_status()
            return self.send_json(200, {"sources": sources,
                "checked": sum(1 for x in sources if x["status"] in ("ok", "error")),
                "enabled": sum(1 for x in sources if x["enabled"]),
                "errors": sum(1 for x in sources if x["enabled"] and x["status"] == "error"),
                "unhealthy": sum(1 for x in sources if x["enabled"] and x["consecutive_bad"] >= core.BAD_RUNS_ALERT)})
        if path == "/api/events":
            events = core.get_events()
            for e in events:
                e.pop("fingerprint", None); e.pop("notified_at", None)
            return self.send_json(200, {"events": events, "count": len(events), "legacy": True})
        if path == "/api/activities":
            activities = core.get_activities()
            return self.send_json(200, {"activities": activities, "count": len(activities)})
        if path == "/api/profile":
            # Preferencias públicas de visualización y avisos (sin secretos). Vacío = agenda neutra.
            try: prof = core.get_profile()
            except ValueError as exc: return self.send_json(500, {"error": str(exc)})
            return self.send_json(200, {k: prof[k] for k in ("name", "highlight", "notify", "show_others")})
        if path == "/api/categories":
            return self.send_json(200, {"categories": core.get_categories()})
        if path == "/api/instance":
            config = core.get_instance_config()
            # La configuración pública no contiene secretos; solo se exponen preferencias de instancia.
            return self.send_json(200, {k: config.get(k) for k in (
                "name", "description", "geographic_mode", "municipalities", "default_radius_km", "timezone")})
        if path == "/api/push/key":
            key = push.public_key()
            if not key:
                return self.send_json(503, {"error": "Push no configurado en el servidor."})
            return self.send_json(200, {"publicKey": key})
        if path == "/feed.xml":
            body = core.rss_feed().encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/api/"):
            return self.send_json(404, {"error": "Ruta no encontrada."})
        return super().do_GET()

    def do_PUT(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/admin/"):
            return self.send_json(404, {"error": "Ruta no encontrada."})
        if not self.is_admin():
            return self.send_json(403, {"error": "Autenticación de administración requerida."})
        try:
            data = self.read_json()
            if path == "/api/admin/instance":
                cfg = validate_instance(data)
                atomic_json(core.config_path("instance.json"), cfg)
                return self.send_json(200, {"saved": True, "instance": cfg})
            if path == "/api/admin/sources":
                sources = validate_sources(data)
                atomic_json(core.config_path("sources.json"), sources)
                return self.send_json(200, {"saved": True, "count": len(sources)})
            if path == "/api/admin/categories":
                categories = save_categories(data)
                return self.send_json(200, {"saved": True, "count": len(categories)})
            return self.send_json(404, {"error": "Ruta de administración no encontrada."})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)})
        except OSError as exc:
            return self.send_json(500, {"error": f"No se pudo guardar la configuración: {exc}"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path in ("/api/events", "/api/activities"):
                if not self.is_admin():
                    return self.send_json(403, {"error": "Define RUA_ADMIN_TOKEN y envía Authorization: Bearer <token>."})
                data = self.read_json()
                batch = data if isinstance(data, list) else [data]
                if len(batch) > 200:
                    raise ValueError("Máximo 200 registros por petición.")
                upsert = core.upsert_activity if path == "/api/activities" else core.upsert_event
                results = [upsert(i) for i in batch]
                return self.send_json(201, {"inserted": sum(1 for _, c in results if c),
                                            "updated": sum(1 for _, c in results if not c)})
            if path == "/api/admin/review":
                if not self.is_admin():
                    return self.send_json(403, {"error": "Autenticación de administración requerida."})
                d = self.read_json(10_000)
                return self.send_json(200, core.review_action(d.get("id"), str(d.get("action"))))
            if path == "/api/push/subscribe":
                return self.send_json(201, push.add_subscription(self.read_json(10_000), MAX_SUBS))
            if path == "/api/push/unsubscribe":
                return self.send_json(200, push.remove_subscription(self.read_json(10_000)))
            return self.send_json(404, {"error": "Ruta no encontrada."})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


def main():
    ensure_config_files()
    core.init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "import":
        if len(sys.argv) < 3:
            print("Uso: python server.py import eventos.json"); raise SystemExit(2)
        data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        for item in (data if isinstance(data, list) else [data]):
            eid, created = core.upsert_event(item)
            print("Añadido" if created else "Actualizado", eid, item.get("artist"))
        return
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Rúa en http://{HOST}:{PORT}  ·  RSS: {core.BASE_URL}/feed.xml")
    if not ADMIN_TOKEN:
        print("Aviso: RUA_ADMIN_TOKEN vacío; POST /api/events deshabilitado.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando servidor…")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
