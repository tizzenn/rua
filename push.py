"""Web Push para Rúa. Requiere: pip install pywebpush (solo para ENVIAR avisos)."""
import base64, json, os, sys
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
import core

KEY_FILE = Path(os.environ.get("RUA_VAPID_PRIVATE_KEY", core.config_path("vapid_private.pem")))
SUBJECT = os.environ.get("RUA_VAPID_SUBJECT", "mailto:admin@example.com")


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def generate_keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization as ser
    if KEY_FILE.exists():
        raise SystemExit(f"{KEY_FILE.name} ya existe; no se sobrescribe (invalidaría las suscripciones).")
    key = ec.generate_private_key(ec.SECP256R1())
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()))
    print("Claves VAPID creadas en", KEY_FILE.name, "(permisos 600). No las subas a ningún repositorio.")


def public_key():
    if not KEY_FILE.exists():
        return None
    from cryptography.hazmat.primitives import serialization as ser
    key = ser.load_pem_private_key(KEY_FILE.read_bytes(), None)
    raw = key.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint)
    return _b64url(raw)


def available():
    return KEY_FILE.exists()


def add_subscription(data, max_subs):
    ep = data.get("endpoint"); keys = data.get("keys") or {}
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not all(isinstance(x, str) and x for x in (ep, p256dh, auth)):
        raise ValueError("Suscripción incompleta.")
    if urlparse(ep).scheme != "https" or len(ep) > 1000 or len(p256dh) > 200 or len(auth) > 100:
        raise ValueError("Suscripción no válida.")
    with core.connect() as db:
        exists = db.execute("SELECT 1 FROM subscriptions WHERE endpoint=?", (ep,)).fetchone()
        if not exists and db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] >= max_subs:
            raise ValueError("Límite de suscripciones alcanzado.")
        db.execute("INSERT OR REPLACE INTO subscriptions VALUES (?,?,?,?)",
                   (ep, p256dh, auth, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return {"ok": True}


def remove_subscription(data):
    with core.connect() as db:
        db.execute("DELETE FROM subscriptions WHERE endpoint=?", (str(data.get("endpoint", "")),))
    return {"ok": True}


def _send(payload):
    from pywebpush import webpush, WebPushException
    sent = dead = 0
    with core.connect() as db:
        subs = db.execute("SELECT * FROM subscriptions").fetchall()
        for s in subs:
            try:
                webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                        data=json.dumps(payload, ensure_ascii=False),
                        vapid_private_key=str(KEY_FILE), vapid_claims={"sub": SUBJECT}, ttl=86400)
                sent += 1
            except WebPushException as exc:
                code = getattr(exc.response, "status_code", None)
                if code in (404, 410):
                    db.execute("DELETE FROM subscriptions WHERE endpoint=?", (s["endpoint"],)); dead += 1
                else:
                    print("Fallo de envío:", code, str(exc)[:120])
    return sent, dead


def notify_new(mark_only=False):
    """Avisa de eventos futuros aún no notificados y los marca. Sin novedades: no envía nada."""
    from datetime import date
    with core.connect() as db:
        new = [dict(r) for r in db.execute(
            "SELECT * FROM events WHERE notified_at IS NULL AND date >= ? ORDER BY created_at",
            (date.today().isoformat(),))]
    if not new:
        print("Sin novedades: no se envía aviso."); return 0
    if not mark_only:
        if not available():
            print("Push sin configurar (python push.py genkeys); los eventos quedan pendientes."); return 0
        sent_total = 0
        if len(new) <= 3:
            for e in new:
                st = "" if e["status"] == "confirmed" else " (sin confirmar)"
                sent, _ = _send({"title": f'Nuevo: {e["artist"]}',
                                 "body": f'{e["style"]} · {e["city"]} · {e["date"]}{st}',
                                 "url": e["source_url"] or "/"})
                sent_total += sent
        else:
            cities = sorted({e["city"] for e in new})
            sent_total, _ = _send({"title": f"{len(new)} eventos nuevos en Rúa", "body": " · ".join(cities), "url": "/"})
        if sent_total == 0:
            print("No se ha podido entregar ningún push; los eventos siguen pendientes.")
            return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with core.connect() as db:
        db.executemany("UPDATE events SET notified_at=? WHERE id=?", [(now, e["id"]) for e in new])
    print(f"{len(new)} evento(s) {'marcados' if mark_only else 'notificados'}.")
    return len(new)


if __name__ == "__main__":
    core.init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "genkeys": generate_keys()
    elif cmd == "notify": notify_new(mark_only="--mark-only" in sys.argv)
    else: print("Uso: python push.py genkeys | notify [--mark-only]")
