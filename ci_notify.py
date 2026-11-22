#!/usr/bin/env python3
"""Avisos SIN servidor: publica en ntfy.sh (app gratuita para Android/iOS) en vez de Web Push.
Reutiliza la lógica de push.py (qué avisar, no repetir, cancelaciones, salud de fuentes).
Requiere la variable NTFY_TOPIC (un nombre largo y aleatorio: quien lo conozca puede leer los avisos)."""
import json, os, re, urllib.request
import core, push

SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")


def publish(topic, payload, base_url):
    click = payload.get("url") or "/"
    if not click.startswith("https://"): click = base_url + "/"
    body = json.dumps({"topic": topic, "title": payload["title"][:200], "message": payload["body"][:500],
                       "click": click, "tags": ["musical_note"]}).encode("utf-8")     # JSON: admite cualquier carácter
    req = urllib.request.Request(SERVER, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status == 200


def main():
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC no definido: sin avisos (el sitio se genera igualmente)."); return 0
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", topic):
        print("NTFY_TOPIC no válido (8-64 caracteres: letras, números, _ y -). Sin avisos."); return 0
    base = core.BASE_URL.rstrip("/")

    def send(payload):
        try:
            return (1, 0) if publish(topic, payload, base) else (0, 0)
        except Exception as exc:
            print(f"ntfy falló: {exc}"); return (0, 0)

    push._send, push.available = send, (lambda: True)
    core.init_db()
    push.notify_activities()
    push.notify_health()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
