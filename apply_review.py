#!/usr/bin/env python3
"""Aplica review.json (editable desde la web de GitHub) a la base de datos. Sin servidor ni curl.
Formato:  {"reject": [{"title": "Nombre", "date": "2026-12-04"}], "confirm": [{"title": "Otro"}]}
`date` es opcional (YYYY-MM-DD); sin ella afecta a todas las fechas futuras con ese título."""
import json, sys
import core


def apply(path=None):
    path = path or core.config_path("review.json")
    if not path.exists():
        path = core.ROOT / "review.json"
    if not path.exists():
        print("Sin review.json: nada que aplicar."); return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict): raise ValueError("debe ser un objeto con 'reject' y/o 'confirm'")
    except ValueError as exc:
        print(f"AVISO: review.json no es válido ({exc}); se ignora y el sitio se genera igualmente."); return 0
    core.init_db()
    done = 0
    for action in ("reject", "confirm"):
        entries = data.get(action, [])
        if not isinstance(entries, list):
            print(f"AVISO: '{action}' debe ser una lista."); continue
        for e in entries:
            if not isinstance(e, dict) or not str(e.get("title", "")).strip():
                print(f"AVISO: entrada ignorada en '{action}': {e!r}"); continue
            title, day = core.norm(e["title"]), str(e.get("date", "")).strip()
            with core.connect() as db:
                ids = [r["id"] for r in db.execute("SELECT id,title FROM activities WHERE substr(starts_at,1,10)>=date('now','-1 day')"
                                                   + (" AND substr(starts_at,1,10)=?" if day else ""), (day,) if day else ()).fetchall()
                       if core.norm(r["title"]) == title]
            if not ids:
                print(f"AVISO: '{e['title']}' ({day or 'cualquier fecha'}) no coincide con ninguna actividad."); continue
            for i in ids:
                core.review_action(i, action); done += 1
    print(f"review.json aplicado: {done} cambio(s).")
    return done


if __name__ == "__main__":
    apply()
