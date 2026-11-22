#!/usr/bin/env python3
"""Genera un sitio ESTÁTICO (carpeta site/) desde la base de datos: sin servidor.
Uso: python publish_static.py [carpeta]      (RUA_BASE_URL = URL pública, para el RSS)"""
import html, json, sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import core

INDEX = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rúa — agenda</title>
<link rel="alternate" type="application/rss+xml" title="Rúa — destacados" href="feed.xml">
<style>
:root{--bg:#fff;--fg:#1b1d22;--mut:#5d6470;--card:#f4f5f7;--acc:#0a7d4d;--warn:#b3361f}
@media(prefers-color-scheme:dark){:root{--bg:#14161b;--fg:#eceef2;--mut:#9aa1ad;--card:#1e2128;--acc:#5ee0a0;--warn:#ff8a70}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:16px}
h1{margin:.2em 0}h2{margin:1.4em 0 .4em;font-size:1.05em;color:var(--acc);text-transform:uppercase;letter-spacing:.06em}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.bar input,.bar select{flex:1;min-width:140px;padding:9px;border-radius:8px;border:1px solid var(--mut);background:var(--card);color:var(--fg);font:inherit}
.card{background:var(--card);border-radius:12px;padding:12px 14px;margin:10px 0}.card h3{margin:0 0 2px;font-size:1.1em}
.meta{color:var(--mut);font-size:.9em}.tag{display:inline-block;font-size:.72em;font-weight:700;border:1px solid var(--mut);border-radius:99px;padding:1px 8px;margin-right:6px;color:var(--mut)}
.tag.warn{border-color:var(--warn);color:var(--warn)}.links a{margin-right:12px;color:var(--acc)}.foot{color:var(--mut);font-size:.85em;margin-top:24px}
.card.cancelled h3{text-decoration:line-through;opacity:.65}
</style></head><body><main>
<h1 id="title">Rúa</h1><div class="meta" id="sub"></div>
<div class="bar"><input id="q" type="search" placeholder="Buscar…"><select id="mun"><option value="">Todos los municipios</option></select><select id="cat"><option value="">Todas las categorías</option></select></div>
<div id="list"></div><p class="foot" id="foot"></p>
<script>
"use strict";
const $=id=>document.getElementById(id);
const el=(t,x,c)=>{const n=document.createElement(t);if(x!=null)n.textContent=x;if(c)n.className=c;return n;};
const fmt=a=>{const d=new Date(a);if(isNaN(d))return a.slice(0,10);const day=d.toLocaleDateString("es-ES",{weekday:"short",day:"numeric",month:"short",year:"numeric",timeZone:"Europe/Madrid"});
 return /T00:00:00$/.test(a)?day:day+" · "+d.toLocaleTimeString("es-ES",{hour:"2-digit",minute:"2-digit",timeZone:"Europe/Madrid"});};
const safe=u=>/^https?:\/\//.test(u||"")?u:null;
function card(a,names){const c=el("div",null,"card"+(a.status==="cancelled"?" cancelled":""));
 c.append(el("h3",a.title));
 c.append(el("div",[fmt(a.starts_at),a.municipality,a.venue].filter(Boolean).join(" · "),"meta"));
 const tags=el("div");
 if(a.status==="cancelled")tags.append(el("span","CANCELADO","tag warn"));
 if(a.status==="postponed")tags.append(el("span","APLAZADO","tag warn"));
 if(a.verification==="unverified")tags.append(el("span","SIN VERIFICAR","tag"));
 (a.category_ids||[]).forEach(id=>tags.append(el("span",names[id]||id,"tag")));
 c.append(tags);
 const links=el("div",null,"links");
 [[safe(a.source_url),"Fuente"],[safe(a.ticket_url),"Entradas"]].forEach(([u,t])=>{if(u){const l=el("a",t);l.href=u;l.rel="noopener noreferrer";l.target="_blank";links.append(l);}});
 c.append(links);return c;}
(async()=>{
 const [data,prof,cats]=await Promise.all(["activities.json","profile.json","categories.json"].map(f=>fetch(f).then(r=>r.json())));
 const names={};(cats.categories||cats).forEach(c=>names[c.id]=c.name);
 $("title").textContent=prof.name||"Rúa";
 $("sub").textContent=data.count+" actividades · actualizado "+new Date(data.generated_at).toLocaleString("es-ES",{timeZone:"Europe/Madrid"});
 const acts=data.activities;
 [...new Set(acts.map(a=>a.municipality))].sort().forEach(m=>{const o=el("option",m);o.value=m;$("mun").append(o);});
 [...new Set(acts.flatMap(a=>a.category_ids||[]))].sort().forEach(id=>{const o=el("option",names[id]||id);o.value=id;$("cat").append(o);});
 function draw(){const q=$("q").value.trim().toLowerCase(),m=$("mun").value,c=$("cat").value;
  const ok=a=>(!m||a.municipality===m)&&(!c||(a.category_ids||[]).includes(c))&&(!q||(a.title+" "+(a.venue||"")+" "+(a.description||"")).toLowerCase().includes(q));
  const list=acts.filter(ok),hi=prof.highlight&&prof.highlight.length;const box=$("list");box.replaceChildren();
  const section=(label,items)=>{if(!items.length)return;if(label)box.append(el("h2",label));items.forEach(a=>box.append(card(a,names)));};
  if(hi){section("Destacado",list.filter(a=>a.highlight));if(prof.show_others!==false)section("Resto de la agenda",list.filter(a=>!a.highlight));}
  else section("",list);
  if(!box.children.length)box.append(el("p","Nada que mostrar con estos filtros.","meta"));}
 ["q","mun","cat"].forEach(id=>$(id).addEventListener("input",draw));draw();
 $("foot").textContent="Datos de fuentes públicas; comprueba siempre la fuente antes de ir. ";
})().catch(()=>{$("list").textContent="No se pudieron cargar los datos.";});
</script></main></body></html>
"""


def _rfc822(iso):
    try:
        d = datetime.fromisoformat(iso)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        d = datetime.now(timezone.utc)
    return format_datetime(d)


def rss(activities, base_url, profile):
    """Feed de lo DESTACADO por el perfil (o de todo si no hay perfil), lo más nuevo primero."""
    items = [a for a in activities if a["highlight"]] if profile["highlight"] else list(activities)
    items.sort(key=lambda a: (a.get("created_at") or "", a["id"]), reverse=True)
    out = []
    for a in items[:60]:
        prefix = {"cancelled": "[CANCELADO] ", "postponed": "[APLAZADO] "}.get(a["status"], "")
        desc = f'{a["municipality"]} · {a["starts_at"][:10]}' + (f' · {a["venue"]}' if a.get("venue") else "") + \
               (" · sin verificar" if a.get("verification") == "unverified" else "")
        link = a.get("source_url") if str(a.get("source_url", "")).startswith("https://") else base_url + "/"
        out.append(f"<item><title>{html.escape(prefix + a['title'])}</title><description>{html.escape(desc)}</description>"
                   f"<link>{html.escape(link)}</link><guid isPermaLink=\"false\">urn:rua:activity:{html.escape(a['fingerprint'])}:{a['status']}</guid>"
                   f"<pubDate>{_rfc822(a.get('created_at'))}</pubDate></item>")
    title = html.escape(profile["name"] or "Rúa — agenda")
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
            f"<title>{title}</title><link>{html.escape(base_url)}/</link>"
            f'<atom:link href="{html.escape(base_url)}/feed.xml" rel="self" type="application/rss+xml"/>'
            f"<description>Novedades de la agenda</description><language>es</language>{''.join(out)}</channel></rss>")


def build(out_dir="site"):
    core.init_db()
    out = Path(out_dir)
    (out / "api").mkdir(parents=True, exist_ok=True)
    base_url = core.BASE_URL.rstrip("/")
    acts = core.get_activities(limit=1000)
    profile = core.get_profile()
    pub_profile = {k: profile[k] for k in ("name", "highlight", "notify", "show_others")}
    # fingerprint y created_at solo se usan para el RSS; no se publican en el JSON
    public_acts = [{k: v for k, v in a.items() if k not in ("fingerprint", "created_at", "updated_at")} for a in acts]
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status = [{k: s.get(k) for k in ("name", "type", "enabled", "status", "last_checked", "fetched", "consecutive_bad")}
              for s in core.get_source_status()]
    payloads = {
        "activities": {"activities": public_acts, "count": len(public_acts), "generated_at": generated},
        "profile": pub_profile,
        "categories": {"categories": core.get_categories()},
        "status": {"sources": status, "generated_at": generated,
                   "unhealthy": sum(1 for s in status if s["enabled"] and (s["consecutive_bad"] or 0) >= core.BAD_RUNS_ALERT)},
    }
    for name, data in payloads.items():
        text = json.dumps(data, ensure_ascii=False)
        (out / f"{name}.json").write_text(text, encoding="utf-8")
        (out / "api" / name).write_text(text, encoding="utf-8")      # misma ruta que la API (/api/activities…) para clientes existentes
    (out / "feed.xml").write_text(rss(acts, base_url, profile), encoding="utf-8")
    (out / "index.html").write_text(INDEX, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return {"activities": len(public_acts), "highlighted": sum(1 for a in acts if a["highlight"])}


if __name__ == "__main__":
    info = build(sys.argv[1] if len(sys.argv) > 1 else "site")
    print(f'Sitio generado: {info["activities"]} actividades, {info["highlighted"]} destacadas.')
