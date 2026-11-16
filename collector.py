#!/usr/bin/env python3
"""Recolector Rúa: ICS, RSS/Atom y JSON; detección por catálogo y géneros explícitos."""
import json, re, sys, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import date, datetime
from html import unescape
from email.utils import parsedate_to_datetime
import core

UA = "Rua-collector/4.0 (+agenda personal; contacto en RUA_VAPID_SUBJECT)"
MAX_BYTES = 8_000_000

CITY_PATTERNS = {
    "Ourense": r"\bourense\b|\borense\b",
    "Vigo": r"\bvigo\b",
    # "Santiago" se admite como abreviatura local, pero nunca Santiago de Chile/Cuba, etc.
    "Santiago de Compostela": r"\bsantiago(?:\s+de\s+compostela)?\b(?!\s+de\s+(?:chile|cuba|queretaro|los\s+caballeros))|\bcompostela\b",
}
# Si la localidad real está fuera de ámbito, no se rescata por aparecer Vigo/Santiago
# en el itinerario, descripción o nombre de la provincia.
OUTSIDE_PATTERNS = r"\b(mos|o\s+porrino|porrino|redondela|nigran|baiona|pontevedra|cangas|moana|tui|a\s+coruna|coruna|ferrol|lugo|ponteareas|vilagarcia|vilagarcía|carballo|ourense\s+provincia|santiago\s+de\s+(?:chile|cuba|queretaro|los\s+caballeros))\b"
STYLE_PATTERNS = [
    ("Rap gallego", r"\b(rap|trap|hip ?hop)\s+(galego|gallego)\b|\b(galego|gallego)\s+(rap|trap)\b"),
    ("Drill", r"\bdrill\b"), ("Trap", r"\btrap\b"),
    ("Rap", r"\brap\b|\brapero\b|\brapera\b|\bhip ?hop\b"),
    ("Underground", r"\bunderground\b"),
]
SESSION_RE = r"\b(dj|sesion|sesiones|fiesta|party|club night|noite)\b"
FESTIVAL_RE = r"\bfestival\b|\bfest\b"


def fetch(url):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    local_test = parsed.hostname in ("127.0.0.1", "localhost", "::1") and parsed.scheme == "http"
    if parsed.scheme != "https" and not local_test:
        raise ValueError("Solo se permiten fuentes HTTPS (HTTP únicamente en localhost para pruebas)")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL de fuente no válida")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/calendar,application/atom+xml,application/rss+xml,application/json,*/*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        final = urllib.parse.urlparse(r.geturl())
        if final.scheme != "https" and not (local_test and final.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("La fuente redirigió a una URL no segura")
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES: raise ValueError("Respuesta demasiado grande")
    return data


def strip_tags(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def load_artists():
    p = core.ROOT / "artists.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def artist_matches(text):
    """Devuelve todos los artistas del catálogo, sin duplicar alias del mismo artista."""
    n = core.norm(strip_tags(text))
    found = []
    for artist in load_artists():
        aliases = [artist.get("name", ""), *artist.get("aliases", [])]
        if any((a := core.norm(alias)) and re.search(r"(?<![\w])" + re.escape(a) + r"(?![\w])", n)
               for alias in aliases):
            found.append(artist)
    # Orden estable: el nombre canónico, no el alias detectado, gobierna la salida.
    return found


def artist_match(text):
    """Compatibilidad para código externo que espere una sola coincidencia."""
    matches = artist_matches(text)
    return matches[0] if matches else None


def classify(text, place="", source_city=None, city_hint_text=None):
    # La ubicación física prevalece sobre textos de gira o listados de otras fechas.
    p = core.norm(strip_tags(place))
    if p and re.search(OUTSIDE_PATTERNS, p): return None, None, None
    place_matches = [c for c, pat in CITY_PATTERNS.items() if re.search(pat, p)] if p else []
    if len(place_matches) > 1: return None, None, None
    city = place_matches[0] if place_matches else None
    if not city and p:
        # Una ubicación concreta que no identifica inequívocamente una de las tres ciudades
        # no se rescata con una mención promocional a Vigo/Santiago/Ourense.
        return None, None, None
    if not city:
        # Sin ubicación estructurada, solo se admite una ciudad inequívoca en el título.
        t = core.norm(strip_tags(city_hint_text if city_hint_text is not None else text))
        if re.search(OUTSIDE_PATTERNS, t): return None, None, None
        title_matches = [c for c, pat in CITY_PATTERNS.items() if re.search(pat, t)]
        if len(title_matches) == 1: city = title_matches[0]
        elif len(title_matches) > 1: return None, None, None
    if not city and source_city in core.CITIES:
        city = source_city
    t = core.norm(strip_tags(text))
    style = next((s for s, pat in STYLE_PATTERNS if re.search(pat, t)), None)
    kind = "Festival" if re.search(FESTIVAL_RE, t) else "Sesión / fiesta" if re.search(SESSION_RE, t) else "Concierto"
    return city, style, kind


def parse_date(s):
    s = (s or "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s) or re.search(r"(\d{4})(\d{2})(\d{2})", s)
    if m: y, mo, d = m.groups()
    else:
        m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
        if not m: return None
        d, mo, y = m.groups()
    try: return date(int(y), int(mo), int(d)).isoformat()
    except ValueError: return None


def parse_datetime(s):
    if not s: return ""
    d = parse_date(s)
    return d or ""


def parse_start_datetime(value):
    """Conserva hora y zona cuando la fuente las proporciona; admite fecha simple."""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.isoformat()
    except ValueError:
        d = parse_date(raw)
        return d or ""


def ics_unescape(v):
    return v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def read_ics(raw):
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]", "", text)
    for block in re.findall(r"BEGIN:VEVENT\n(.*?)\nEND:VEVENT", text, re.S):
        f = {}
        for line in block.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1); f.setdefault(k.split(";")[0].upper(), ics_unescape(v))
        yield {"title": f.get("SUMMARY", ""), "text": f.get("DESCRIPTION", ""),
               "place": f.get("LOCATION", ""), "date": parse_date(f.get("DTSTART", "")),
               "url": f.get("URL", ""), "announced_at": parse_datetime(f.get("X-ANNOUNCEMENT-DATE", "")),
               "presale_at": parse_datetime(f.get("X-PRE-SALE", "")), "ticket_url": f.get("X-TICKETS", "")}


def read_rss(raw):
    root = ET.fromstring(raw)
    for it in root.iter():
        tag = it.tag.rsplit("}", 1)[-1].lower()
        if tag not in ("item", "entry"): continue
        children = {c.tag.rsplit("}", 1)[-1].lower(): c for c in list(it)}
        def val(*names):
            for n in names:
                e = children.get(n)
                if e is not None:
                    if e.text: return e.text.strip()
                    href = e.attrib.get("href")
                    if href: return href
            return ""
        body = strip_tags(val("description", "summary", "content"))
        pub = val("published", "pubdate", "updated")
        try: pub = parsedate_to_datetime(pub).date().isoformat() if pub else ""
        except Exception: pub = parse_date(pub) or ""
        yield {"title": strip_tags(val("title")), "text": body, "place": val("location"),
               "date": parse_date(val("start", "eventdate") + " " + val("title") + " " + body),
               "url": val("link"), "announced_at": "", "published_at": pub, "presale_at": "", "ticket_url": ""}


def dig(obj, path):
    for part in filter(None, (path or "").split(".")):
        obj = obj[int(part)] if isinstance(obj, list) else (obj or {}).get(part)
    return obj


def read_json(raw, src):
    m = src.get("map", {}); items = dig(json.loads(raw), src.get("items_path", "")) or []
    for it in items:
        get = lambda k, default: dig(it, m.get(k, default))
        yield {"title": str(get("title", "title") or ""), "text": str(get("text", "description") or ""),
               "place": str(get("place", "location") or ""), "date": parse_date(str(get("date", "date") or "")),
               "url": str(get("url", "url") or ""), "announced_at": parse_date(str(get("announced_at", "announced_at") or "")) or "",
               "presale_at": parse_date(str(get("presale_at", "presale_at") or "")) or "",
               "ticket_url": str(get("ticket_url", "ticket_url") or "")}


def _jsonld_nodes(value):
    """Recorre JSON-LD y extrae objetos de evento sin depender del orden de @graph."""
    if isinstance(value, list):
        for item in value: yield from _jsonld_nodes(item)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str): types = [types]
        if any(str(t).lower() in ("event", "musicevent", "festival") for t in types):
            yield value
        for key, child in value.items():
            if key not in ("@context",): yield from _jsonld_nodes(child)


def _jsonld_name(value):
    if isinstance(value, str): return strip_tags(value)
    if isinstance(value, dict): return strip_tags(value.get("name", ""))
    if isinstance(value, list): return " & ".join(filter(None, (_jsonld_name(x) for x in value)))
    return ""


def read_jsonld(raw):
    """Lee Event/MusicEvent de schema.org en bloques script application/ld+json."""
    from html.parser import HTMLParser
    class Scripts(HTMLParser):
        def __init__(self): super().__init__(); self.in_jsonld = False; self.parts = []; self.current = []
        def handle_starttag(self, tag, attrs):
            if tag.lower() == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
                self.in_jsonld = True; self.current = []
        def handle_data(self, data):
            if self.in_jsonld: self.current.append(data)
        def handle_endtag(self, tag):
            if tag.lower() == "script" and self.in_jsonld:
                self.parts.append("".join(self.current)); self.in_jsonld = False; self.current = []
    parser = Scripts(); parser.feed(raw.decode("utf-8", "replace"))
    seen = set()
    for script in parser.parts:
        try: payload = json.loads(script)
        except (ValueError, TypeError): continue
        for event in _jsonld_nodes(payload):
            url = event.get("url", "")
            if isinstance(url, dict): url = url.get("url", "")
            key = (str(event.get("name", "")), str(event.get("startDate", "")), str(url))
            if key in seen: continue
            seen.add(key)
            location = event.get("location", {})
            if isinstance(location, list): location = location[0] if location else {}
            if not isinstance(location, dict): location = {"name": str(location)}
            address = location.get("address", {})
            if isinstance(address, str): address_text = address
            elif isinstance(address, dict):
                # Omit addressRegion: a province is not the municipality and can cause false rejection.
                address_text = " ".join(str(address.get(k, "")) for k in ("streetAddress", "postalCode", "addressLocality") if address.get(k))
            else: address_text = ""
            place = ", ".join(x for x in (strip_tags(location.get("name", "")), address_text) if x)
            performers = _jsonld_name(event.get("performer", ""))
            title = strip_tags(event.get("name", ""))
            if performers and core.norm(performers) not in core.norm(title): title = f"{title} — {performers}"
            offers = event.get("offers", [])
            if isinstance(offers, dict): offers = [offers]
            ticket = next((str(x.get("url", "")) for x in offers if isinstance(x, dict)
                           and str(x.get("url", "")).startswith("https://")), "")
            status = str(event.get("eventStatus", "")).lower()
            if "eventcancelled" in status: continue
            yield {"title": title, "text": strip_tags(event.get("description", "")),
                   "place": place, "date": parse_date(str(event.get("startDate", ""))),
                   "starts_at": parse_start_datetime(str(event.get("startDate", ""))),
                   "url": str(url), "announced_at": "", "presale_at": "", "ticket_url": ticket}


def fetch_post_form(url, params):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("www.cultura.gal", "cultura.gal"):
        raise ValueError("La API de Cultura solo admite HTTPS en cultura.gal")
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            content_type = r.headers.get("Content-Type", "")
            data = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError("HTTP 403: cultura.gal ha denegado la petición automatizada. No se reintenta ni se intenta eludir el bloqueo; mantener esta fuente desactivada y buscar un feed o API pública alternativa.") from None
        raise RuntimeError(f"HTTP {exc.code} al consultar cultura.gal") from None
    if len(data) > MAX_BYTES: raise ValueError("Respuesta de Cultura demasiado grande")
    if "json" not in content_type.lower():
        raise ValueError(f"Cultura devolvió {content_type or 'un tipo de contenido desconocido'}, no JSON; posible página de bloqueo o sesión requerida")
    return json.loads(data.decode("utf-8", "replace"))


def read_cultura_api(src):
    """API oficial documentada: POST /services/abertos, pagina por concello."""
    from datetime import timedelta
    start = date.today().isoformat()
    end = (date.today() + timedelta(days=int(src.get("days_ahead", 365)))).isoformat()
    for city, council_id in src.get("councils", {}).items():
        if city not in core.CITIES: continue
        page = 0
        while True:
            payload = fetch_post_form(src["url"], {"dini": start, "dfin": end, "concello": council_id,
                                                      "paxina": page, "idioma": src.get("language", "es")})
            if not isinstance(payload, dict) or "listaAxenda" not in payload:
                raise ValueError("Respuesta JSON de Cultura con estructura inesperada")
            if payload.get("erros"):
                raise ValueError("API Cultura: " + "; ".join(str(e.get("mensaxe", e)) for e in payload["erros"]))
            rows = payload.get("listaAxenda", [])
            for row in rows:
                data = row.get("data") or {}
                start_at = data.get("dataInicio", "")
                links = row.get("ligazons") or []
                urls = [x.get("url", "") for x in links if isinstance(x, dict)]
                ticket = next((x.get("url", "") for x in links if isinstance(x, dict)
                               and re.search(r"entrada|ticket|taquilla|compra", str(x.get("titulo", "")), re.I)
                               and str(x.get("url", "")).startswith("https://")), "")
                detail = next((u for u in urls if u.startswith("https://")), "")
                yield {"title": row.get("titulo", ""), "text": strip_tags(row.get("corpo", "") + " " + row.get("entrada", "") + " " + row.get("tipoEvento", "")),
                       "place": " ".join(x for x in (row.get("lugarCelebracion", ""), row.get("concello", city)) if x),
                       "date": parse_date(start_at), "url": detail, "announced_at": "", "presale_at": "", "ticket_url": ticket}
            total = int(payload.get("totalResultados", len(rows)) or 0)
            per_page = int(payload.get("elementosPorPaxina", 25) or 25)
            if not rows or (page + 1) * per_page >= total: break
            page += 1


def read_tribe_api(src):
    """WordPress The Events Calendar REST API (Concertos do Xacobeo)."""
    from datetime import timedelta
    from urllib.parse import urlencode
    start = date.today().isoformat()
    end = (date.today() + timedelta(days=int(src.get("days_ahead", 540)))).isoformat()
    page = 1
    while True:
        params = {"start_date": start, "end_date": end, "per_page": int(src.get("per_page", 100)), "page": page}
        url = src["url"].rstrip("?") + ("&" if "?" in src["url"] else "?") + urlencode(params)
        payload = json.loads(fetch(url).decode("utf-8", "replace"))
        if not isinstance(payload, dict) or "events" not in payload:
            raise ValueError("Respuesta de Concertos do Xacobeo sin campo events")
        rows = payload.get("events", [])
        for row in rows:
            venue = row.get("venue") or {}
            city = venue.get("city", "")
            address = venue.get("address", "")
            links = row.get("website", "")
            ticket = row.get("ticket_url", "") or row.get("tickets_url", "")
            yield {"title": strip_tags(row.get("title", "")),
                   "text": strip_tags(row.get("description", "") or row.get("excerpt", "")),
                   "place": " ".join(x for x in (venue.get("venue", ""), address, city) if x),
                   "date": parse_date(row.get("start_date", "")),
                   "url": row.get("url", "") or links, "announced_at": "", "presale_at": "",
                   "ticket_url": ticket if isinstance(ticket, str) else ""}
        total_pages = int(payload.get("total_pages", page) or page) if isinstance(payload, dict) else page
        if not rows or page >= total_pages: break
        page += 1


def collect(src):
    kind = src["type"]
    if kind == "cultura_api": return read_cultura_api(src)
    if kind == "tribe_api": return read_tribe_api(src)
    raw = fetch(src["url"])
    if kind == "ics": return read_ics(raw)
    if kind in ("rss", "atom"): return read_rss(raw)
    if kind == "json": return read_json(raw, src)
    if kind == "jsonld": return read_jsonld(raw)
    raise ValueError(f"Tipo de fuente desconocido: {kind}")


def to_event(item, src):
    if not item.get("title") or not item.get("date"): return None, "sin título o fecha"
    if item["date"] < date.today().isoformat(): return None, "pasado"
    blob = " ".join((item["title"], item.get("text", "")))
    city, explicit_style, kind = classify(blob, item.get("place", ""), src.get("city"), item.get("title", ""))
    if not city: return None, "localidad no incluida o no verificable"
    # Prioriza nombres en el título; solo recurre a la descripción si el título no identifica a nadie.
    # Así se evita convertir artistas citados como influencias o colaboradores en cabezas de cartel.
    catalogued = artist_matches(item["title"]) or artist_matches(item.get("text", ""))
    style = explicit_style
    if not style and catalogued:
        # Se usa el primer género común del catálogo; no se inventa una etiqueta a partir del nombre.
        catalogued_styles = {s for a in catalogued for s in a.get("styles", [])}
        priority = ("Rap gallego", "Drill", "Trap", "Rap", "Underground")
        style = next((s for s in priority if s in catalogued_styles), "")
    if not style: return None, "estilo no acreditado ni artista catalogado"
    artist = " & ".join(a["name"] for a in catalogued) if catalogued else strip_tags(item["title"])
    source_url = item.get("url", "")
    if not source_url.startswith("https://"): source_url = src.get("page", "")
    status = src.get("status", "unverified")
    notes = ""
    if catalogued and not explicit_style:
        notes = "Artista(s) identificado(s) en el catálogo editorial; consulta la fuente de estilo enlazada. La ficha no se considera confirmación independiente del concierto."
    elif status == "announced":
        notes = "Fuente configurada como anuncio; revisar que sea la fuente primaria oficial."
    return {"artist": artist[:160], "city": city, "venue": item.get("place", "")[:160],
            "date": item["date"], "style": style, "type": kind, "status": status,
            "source": src["name"], "source_url": source_url,
            "ticket_url": item.get("ticket_url", "") if item.get("ticket_url", "").startswith("https://") else "",
            "style_source_url": next((a.get("style_source_url", "") for a in catalogued if a.get("style_source_url")), "") if catalogued and not explicit_style else source_url,
            "announced_at": item.get("announced_at", ""), "presale_at": item.get("presale_at", ""), "notes": notes}, None


def to_activity(item, src):
    """Normaliza una ficha generalista para el modelo universal de actividades."""
    title = strip_tags(item.get("title", ""))
    starts_at = item.get("starts_at") or parse_start_datetime(item.get("date", ""))
    if not title or not starts_at:
        return None, "sin título o fecha"
    if starts_at[:10] < date.today().isoformat():
        return None, "pasado"
    configured = core.get_instance_config()
    municipalities = configured.get("municipalities", [])
    place = core.norm(strip_tags(item.get("place", "")))
    matches = [m for m in municipalities if re.search(r"(?<![\w])" + re.escape(core.norm(m)) + r"(?![\w])", place)]
    if len(matches) > 1:
        return None, "localidad ambigua"
    municipality = matches[0] if matches else src.get("municipality", src.get("city", ""))
    if not municipality or not core.municipality_allowed(municipality):
        return None, "localidad fuera del ámbito o no verificable"
    category_ids = src.get("category_ids") or ([src["category_id"]] if src.get("category_id") else [])
    if not category_ids:
        return None, "fuente sin categoría configurada"
    url = item.get("url", "")
    if not isinstance(url, str) or not url.startswith("https://"):
        url = src.get("page", "")
    ticket = item.get("ticket_url", "")
    if not isinstance(ticket, str) or not ticket.startswith("https://"):
        ticket = ""
    return {
        "title": title[:300], "description": strip_tags(item.get("text", ""))[:12000],
        "municipality": municipality, "venue": strip_tags(item.get("venue", item.get("place", "")))[:200],
        "starts_at": starts_at, "ends_at": item.get("ends_at", ""),
        "announced_at": item.get("announced_at", ""),
        "registration_opens_at": item.get("presale_at", item.get("registration_opens_at", "")),
        "event_type": src.get("event_type", "event"), "status": src.get("activity_status", "scheduled"),
        "verification": src.get("verification", "single_source" if src.get("status") == "announced" else "unverified"),
        "category_ids": category_ids, "entities": item.get("entities", []),
        "source_name": src.get("name", ""), "source_url": url, "ticket_url": ticket,
    }, None


def run(dry=False):
    core.init_db(); sources = json.loads((core.config_path("sources.json")).read_text(encoding="utf-8")); total_new = 0
    for src in sources:
        if not src.get("enabled", True) or "PON-AQUI" in src.get("url", "PON-AQUI"):
            print(f"[{src.get('name')}] omitida (desactivada o sin URL)"); continue
        started = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            items = list(collect(src))
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"[{src['name']}] ERROR: {message}")
            if not dry:
                core.record_source_run(src["name"], src.get("type", ""), "error", error=message, started_at=started)
            continue
        new = upd = skip = 0
        for item in items:
            generic = src.get("model") == "activity"
            ev, why = (to_activity(item, src) if generic else to_event(item, src))
            if not ev:
                skip += 1
                if dry: print("  · DESCARTADO:", why)
                continue
            if dry:
                if generic:
                    print("  ·", ev["starts_at"], ev["municipality"], ev["category_ids"], "|", ev["title"])
                else:
                    print("  ·", ev["date"], ev["city"], ev["style"], "|", ev["artist"], "|", ev["status"])
                continue
            try:
                _, created = (core.upsert_activity(ev) if generic else core.upsert_event(ev))
            except ValueError:
                skip += 1
                continue
            new += int(created); upd += int(not created)
        total_new += new
        print(f"[{src['name']}] {len(items)} leídos · {new} nuevos · {upd} ya conocidos · {skip} descartados")
        if not dry:
            core.record_source_run(src["name"], src.get("type", ""), "ok", len(items), new, upd, skip, started_at=started)
    return total_new


if __name__ == "__main__":
    n = run(dry="--dry-run" in sys.argv)
    if "--dry-run" not in sys.argv and "--no-notify" not in sys.argv:
        import push
        push.notify_new()
