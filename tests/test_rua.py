"""Pruebas de la agenda generalista: perfil, ámbito, dedupe, estados, avisos y recolector.
Ejecutar: python -m unittest discover -s tests"""
import contextlib, io, json, os, shutil, sys, tempfile, threading, unittest, urllib.error, urllib.request
import unittest.mock as mock
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp())
CONF = TMP / "conf"
shutil.copytree(ROOT, CONF, ignore=shutil.ignore_patterns("android", ".git", "tests", "*.zip", "__pycache__", ".github"))
os.environ.update(RUA_DB=str(TMP / "t.sqlite3"), RUA_CONFIG_DIR=str(CONF), RUA_ADMIN_TOKEN="t" * 32, RUA_FETCH_DELAY="0")
import core, collector, push, server  # noqa: E402

GL = ["", "xaneiro", "febreiro", "marzo", "abril", "maio", "xuño", "xullo", "agosto", "setembro", "outubro", "novembro", "decembro"]
def day(n): return (date.today() + timedelta(days=n)).isoformat()
D1, D2 = day(40), day(41)
SRC = {"name": "T", "type": "ics", "model": "activity", "status": "announced", "default_category": "cultura"}
def item(title, place="", city="", d=D1, text="", **kw): return {"title": title, "text": text, "place": place, "city": city, "date": d, "url": "", **kw}
def cats(it, src=SRC):
    ev, why = collector.to_activity(it, src); return (ev["category_ids"] if ev else None), why


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls): core.init_db()
    def setUp(self): collector._VENUES = None


class TestProfile(Base):
    def test_sample_profile_is_rap_and_configurable(self):
        p = core.get_profile()
        self.assertEqual((p["highlight"], p["notify"]), (["rap"], ["rap"]))
        self.assertIn("rap", p["interests"])

    def test_no_profile_means_neutral_agenda(self):
        empty = TMP / "empty"; empty.mkdir(exist_ok=True)
        for name in ("instance.json", "categories.json", "artists.json"):      # todo menos profile.json
            shutil.copyfile(ROOT / name, empty / name)
        with mock.patch.object(core, "ROOT", empty), mock.patch.object(core, "CONFIG_DIR", empty):
            p = core.get_profile()
            self.assertEqual((p["highlight"], p["notify"], p["interests"], p["show_others"]), ([], [], {}, True))
            ev, _ = collector.to_activity(item("Hard GZ en concierto", "Vigo", "Vigo"), {**SRC, "category_ids": ["musica"]})
        self.assertNotIn("rap", ev["category_ids"])            # sin perfil, nada es «rap»

    def test_general_profile_for_another_interest(self):
        (CONF / "profile.json").write_text(json.dumps({"highlight": ["running-trail"], "notify": [], "interests": {
            "running-trail": {"keywords": ["trail", "carreira"]}}, "category_rules": {}}))
        try:
            self.assertIn("running-trail", cats(item("Trail do Miño", "Ourense", "Ourense"))[0])
            self.assertNotIn("rap", cats(item("Noite de rap", "Ourense", "Ourense"))[0])
        finally:
            shutil.copyfile(ROOT / "profile.json", CONF / "profile.json")

    def test_invalid_profile_rejected(self):
        (CONF / "profile.json").write_text(json.dumps({"highlight": "rap"}))
        try:
            with self.assertRaises(ValueError): core.get_profile()
        finally:
            shutil.copyfile(ROOT / "profile.json", CONF / "profile.json")


class TestCategories(Base):
    def test_artist_catalog_tags_rap_without_keyword(self):
        ev, _ = collector.to_activity(item("Hard GZ en concierto: LACOSTA II", "Sala Rouge", "Vigo"), {**SRC, "category_ids": ["musica"]})
        self.assertEqual(ev["category_ids"], ["musica", "rap"])
        self.assertIn("Hard GZ", [e["name"] for e in ev["entities"]])

    def test_rules_and_default(self):
        self.assertEqual(cats(item("Taller de cerámica", "Biblioteca - Ourense", "Ourense"))[0], ["talleres"])
        self.assertEqual(cats(item("Cousa sen clasificar", "Ourense", "Ourense"))[0], ["cultura"])

    def test_rap_in_title_always_counts_but_in_text_needs_music(self):
        self.assertIn("rap", cats(item("Obradoiro de rap", "Ourense", "Ourense"))[0])
        museum = item("Visita ao museo", "Museo - Vigo", "Vigo", text="Un percorrido polo underground e o rap dos 90")
        self.assertNotIn("rap", cats(museum)[0])
        concert = item("Concerto de sábado", "Sala X", "Vigo", text="Noite de rap e hip hop")
        self.assertIn("rap", cats(concert)[0])

    def test_unknown_source_category_is_filtered(self):
        ev, _ = collector.to_activity(item("Algo", "Vigo", "Vigo"), {**SRC, "category_ids": ["no-existe"]})
        self.assertEqual(ev["category_ids"], ["cultura"])


class TestMunicipality(Base):
    ICS = ("BEGIN:VCALENDAR\n" + "".join(
        f"BEGIN:VEVENT\nSUMMARY:{t}\nDTSTART;VALUE=DATE:{D1.replace('-', '')}\nLOCATION:{loc}\nEND:VEVENT\n" for t, loc in (
            ("A", "Museo Etnolóxico de Ribadavia - Ribadavia"), ("B", "Museo X - Ribadavia - Ourense"),
            ("C", "Biblioteca Pública de Ourense - Ourense"), ("D", "Monte Gaiás, s/n - Santiago de Compostela"),
            ("E", "Casa da Cultura - Trasmiras - Ourense"), ("F", "Sala sen municipio"))) + "END:VCALENDAR\n").encode()

    def test_ics_suffix_is_the_municipality(self):
        got = {i["title"]: collector.to_activity(i, SRC) for i in collector.read_ics(self.ICS)}
        self.assertEqual(got["A"][1], "municipio fuera de ámbito (Ribadavia)")
        self.assertEqual(got["B"][1], "municipio fuera de ámbito (Ribadavia)")     # con provincia detrás
        self.assertEqual(got["E"][1], "municipio fuera de ámbito (Trasmiras)")     # provincia de Ourense != ciudad
        self.assertEqual(got["C"][0]["municipality"], "Ourense")
        self.assertEqual(got["D"][0]["municipality"], "Santiago de Compostela")
        self.assertEqual(got["F"][1], "localidad fuera del ámbito o no verificable")

    def test_alias_and_province_text(self):
        self.assertEqual(collector.to_activity(item("X", "Auditorio", "Orense"), SRC)[0]["municipality"], "Ourense")
        self.assertEqual(collector.to_activity(item("X", "Sala", "Vigo (Pontevedra)"), SRC)[0]["municipality"], "Vigo")

    def test_sala_queen_is_mos_not_vigo(self):
        ev, why = collector.to_activity(item("Hard GZ", "Sala Queen", "Vigo"), {**SRC, "category_ids": ["musica"]})
        self.assertIsNone(ev); self.assertIn("Mos", why)
        self.assertEqual(collector.to_activity(item("X", "Sala Capitol", "Pontevedra"), SRC)[0]["municipality"], "Santiago de Compostela")

    def test_unrestricted_mode_accepts_any_municipality(self):
        cfg = core.get_instance_config()
        with mock.patch.object(core, "get_instance_config", lambda: {**cfg, "geographic_mode": "unrestricted"}):
            self.assertEqual(collector.to_activity(item("X", "Sala", "Lugo"), SRC)[0]["municipality"], "Lugo")


class TestDedupeAndStatus(Base):
    def act(self, title, source, d=D1, **kw):
        base = {"title": title, "municipality": "Vigo", "starts_at": d, "category_ids": ["musica"], "source_name": source}
        return core.upsert_activity({**base, **kw})

    def test_same_event_two_sources_different_titles(self):
        a, c1 = self.act("Hard GZ", "ICS")
        b, c2 = self.act("Hard GZ en concierto: LACOSTA II", "RSS")
        self.assertEqual((a, c1, c2), (b, True, False))
        with core.connect() as db:
            self.assertEqual({r[0] for r in db.execute("SELECT source_name FROM activity_sources WHERE activity_id=?", (a,))}, {"ICS", "RSS"})
            self.assertEqual(db.execute("SELECT title FROM activities WHERE id=?", (a,)).fetchone()[0], "Hard GZ")

    def test_different_events_are_not_merged(self):
        a, _ = self.act("Noite de jazz", "S", d=D2)
        b, c = self.act("Noite de rock", "S", d=D2)
        self.assertTrue(c and a != b)
        t1, _ = self.act("Teatro", "S", d=day(50)); t2, c2 = self.act("Teatro infantil: A bruxa", "S", d=day(50))
        self.assertTrue(c2 and t1 != t2)                       # una sola palabra común no basta

    def test_status_detection_and_no_downgrade(self):
        self.assertEqual(collector.to_activity(item("Rap en Vigo", "Vigo", "Vigo", text="Concierto CANCELADO"), SRC)[0]["status"], "cancelled")
        self.assertEqual(collector.to_activity(item("X", "Vigo", "Vigo", text="Aprazado ata nova data"), SRC)[0]["status"], "postponed")
        self.assertEqual(collector.to_activity(item("X", "Vigo", "Vigo", event_status="cancelled"), SRC)[0]["status"], "cancelled")
        i, _ = self.act("Estado Test", "S", d=day(60), status="cancelled")
        self.act("Estado Test", "S2", d=day(60), status="scheduled")
        with core.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM activities WHERE id=?", (i,)).fetchone()[0], "cancelled")

    def test_jsonld_keeps_cancelled_with_status_and_presale(self):
        page = f"""<script type="application/ld+json">{{"@type":"MusicEvent","name":"Rap Show","startDate":"{D1}",
          "eventStatus":"https://schema.org/EventCancelled","location":{{"name":"Sala Rouge","address":{{"addressLocality":"Vigo"}}}},
          "performer":[{{"name":"MC Zeta"}}],"offers":{{"url":"https://t.example/x","validFrom":"2026-10-05T10:00:00+02:00"}}}}</script>""".encode()
        it = list(collector.read_jsonld(page))[0]
        ev, _ = collector.to_activity(it, {"name": "W", "type": "jsonld", "model": "activity", "category_ids": ["musica"]})
        self.assertEqual((ev["status"], ev["registration_opens_at"], ev["municipality"]), ("cancelled", "2026-10-05", "Vigo"))
        self.assertIn("MC Zeta", [e["name"] for e in ev["entities"]])


class TestReaders(Base):
    def test_rss_dates_in_galician_and_spanish(self):
        d = date.fromisoformat(D1)
        rss = f"""<rss><channel><item><title>Concerto en Vigo</title><link>https://x.example/1</link>
          <description>Data: {d.day} de {GL[d.month]} de {d.year}. Lugar: Auditorio - Vigo</description></item>
          <item><title>Charla</title><description>El {d.day} de {['','enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'][d.month]} de {d.year}</description></item>
          </channel></rss>""".encode()
        items = list(collector.read_rss(rss))
        self.assertEqual([i["date"] for i in items], [D1, D1])
        self.assertIsNone(collector.parse_date("sin fecha"))

    def test_polite_fetch_respects_robots(self):
        collector._ROBOTS.clear()
        def fake(url):
            if url.endswith("/robots.txt"): return b"User-agent: *\nDisallow: /privado\n"
            return b"ok"
        with mock.patch.object(collector, "fetch", fake):
            self.assertEqual(collector.polite_fetch("https://r.example/publico"), b"ok")
            with self.assertRaises(PermissionError): collector.polite_fetch("https://r.example/privado/x")
        collector._ROBOTS.clear()
        def f403(url):
            if url.endswith("/robots.txt"): raise urllib.error.HTTPError(url, 403, "no", {}, None)
            return b"ok"
        with mock.patch.object(collector, "fetch", f403):
            with self.assertRaises(PermissionError): collector.polite_fetch("https://r3.example/a")
        collector._ROBOTS.clear()


class Feed(BaseHTTPRequestHandler):
    BODY = b""
    def do_GET(self): self.send_response(200); self.send_header("Content-Type", "text/calendar"); self.end_headers(); self.wfile.write(self.BODY)
    def log_message(self, *a): pass


class TestRunAndNotify(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda t, loc, extra="": f"BEGIN:VEVENT\nSUMMARY:{t}\nDTSTART;VALUE=DATE:{day(33).replace('-', '')}\nLOCATION:{loc}\n{extra}END:VEVENT\n"
        Feed.BODY = ("BEGIN:VCALENDAR\n" + mk("Concerto de Rap Galego", "Sala Capitol - Santiago de Compostela")
                     + mk("Obradoiro de cerámica", "Biblioteca - Ourense") + mk("Charla en Ribadavia", "Museo - Ribadavia")
                     + "END:VCALENDAR\n").encode()
        cls.feed = HTTPServer(("127.0.0.1", 0), Feed); threading.Thread(target=cls.feed.serve_forever, daemon=True).start()
        cls.api = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler); threading.Thread(target=cls.api.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.feed.shutdown(); cls.feed.server_close(); cls.api.shutdown(); cls.api.server_close()

    def test_1_run_end_to_end_with_profile(self):
        (CONF / "sources.json").write_text(json.dumps([{"name": "ICS local", "type": "ics", "model": "activity", "status": "announced",
            "url": f"http://127.0.0.1:{self.feed.server_port}/c.ics", "default_category": "cultura", "enabled": True}]))
        try:
            with contextlib.redirect_stdout(io.StringIO()): collector.run()
        finally:
            shutil.copyfile(ROOT / "sources.json", CONF / "sources.json")
        by_title = {a["title"]: a for a in core.get_activities()}
        self.assertEqual(set(by_title) & {"Concerto de Rap Galego", "Obradoiro de cerámica", "Charla en Ribadavia"},
                         {"Concerto de Rap Galego", "Obradoiro de cerámica"})        # Ribadavia fuera
        self.assertTrue(by_title["Concerto de Rap Galego"]["highlight"]); self.assertIn("rap", by_title["Concerto de Rap Galego"]["category_ids"])
        self.assertFalse(by_title["Obradoiro de cerámica"]["highlight"])
        self.assertEqual(core.get_source_status()[0]["status"] if core.get_source_status() else "ok", core.get_source_status()[0]["status"])

    def test_2_notify_only_profile_categories_once_and_alert_on_cancel(self):
        sent = []
        with mock.patch.object(push, "_send", lambda p: sent.append(p) or (1, 0)), mock.patch.object(push, "available", lambda: True), \
             contextlib.redirect_stdout(io.StringIO()):
            core.upsert_activity({"title": "Aviso Rap", "municipality": "Vigo", "starts_at": day(70), "category_ids": ["musica", "rap"]})
            core.upsert_activity({"title": "Aviso Taller", "municipality": "Vigo", "starts_at": day(70), "category_ids": ["talleres"]})
            push.notify_activities()
            titles = [p["title"] for p in sent]
            self.assertTrue(any("Aviso Rap" in t for t in titles)); self.assertFalse(any("Aviso Taller" in t for t in titles))
            sent.clear(); push.notify_activities(); self.assertEqual(sent, [])                    # no repite
            core.upsert_activity({"title": "Aviso Rap", "municipality": "Vigo", "starts_at": day(70), "category_ids": ["rap"], "status": "cancelled"})
            push.notify_activities(); self.assertEqual([p["title"] for p in sent], ["CANCELADO: Aviso Rap"])
            sent.clear(); push.notify_activities(); self.assertEqual(sent, [])

    def test_3_empty_notify_sends_nothing_and_born_cancelled_not_announced(self):
        sent = []
        with mock.patch.object(push, "_send", lambda p: sent.append(p) or (1, 0)), mock.patch.object(push, "available", lambda: True), \
             contextlib.redirect_stdout(io.StringIO()):
            core.upsert_activity({"title": "Nace Cancelado", "municipality": "Vigo", "starts_at": day(71), "category_ids": ["rap"], "status": "cancelled"})
            push.notify_activities(); self.assertFalse(any("Nace Cancelado" in p["title"] for p in sent))
            (CONF / "profile.json").write_text(json.dumps({"notify": []}))
            try:
                core.upsert_activity({"title": "Sin Avisos", "municipality": "Vigo", "starts_at": day(72), "category_ids": ["rap"]})
                sent.clear(); push.notify_activities(); self.assertEqual(sent, [])
            finally:
                shutil.copyfile(ROOT / "profile.json", CONF / "profile.json")

    def test_4_mark_only_marks_without_sending(self):
        core.upsert_activity({"title": "Solo Marcar", "municipality": "Ourense", "starts_at": day(73), "category_ids": ["rap"]})
        with mock.patch.object(push, "_send", side_effect=AssertionError("no debe enviar")), contextlib.redirect_stdout(io.StringIO()):
            push.notify_activities(mark_only=True)
        with core.connect() as db:
            self.assertIsNotNone(db.execute("SELECT notified_at FROM activities WHERE title='Solo Marcar'").fetchone()[0])

    def test_5_api_profile_and_activities_highlight(self):
        base = f"http://127.0.0.1:{self.api.server_port}"
        prof = json.loads(urllib.request.urlopen(base + "/api/profile").read())
        self.assertEqual((prof["highlight"], prof["notify"], prof["show_others"]), (["rap"], ["rap"], True))
        acts = json.loads(urllib.request.urlopen(base + "/api/activities").read())["activities"]
        self.assertTrue(all("highlight" in a and "notified_at" not in a for a in acts))

    def test_6_inspect_runs_and_explains(self):
        (CONF / "sources.json").write_text(json.dumps([{"name": "ICS local", "type": "ics", "model": "activity", "status": "announced",
            "url": f"http://127.0.0.1:{self.feed.server_port}/c.ics", "default_category": "cultura"}]))
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out): collector.inspect("ICS local")
        finally:
            shutil.copyfile(ROOT / "sources.json", CONF / "sources.json")
        t = out.getvalue()
        self.assertIn("Elementos leídos: 3", t); self.assertIn("★", t); self.assertIn("municipio fuera de ámbito (Ribadavia)", t)


class TestLaGanzua(Base):
    def test_jsonld_genre_tags_reach_the_interest_matcher(self):
        page = f"""<script type="application/ld+json">{{"@type":"MusicEvent","name":"Noite grande","startDate":"{D1}",
          "genre":["Urbana","HipHop Rap","Trap"],"location":{{"name":"Sala Capitol","address":{{"addressLocality":"Santiago de Compostela"}}}}}}</script>""".encode()
        it = list(collector.read_jsonld(page))[0]
        self.assertIn("HipHop Rap", it["text"])
        ev, _ = collector.to_activity(it, {"name": "G", "type": "jsonld", "model": "activity", "category_ids": ["musica"]})
        self.assertIn("rap", ev["category_ids"]); self.assertEqual(ev["municipality"], "Santiago de Compostela")
        pop = page.replace(b'"HipHop Rap","Trap"', b'"Pop Rock"')
        ev2, _ = collector.to_activity(list(collector.read_jsonld(pop))[0], {"name": "G", "type": "jsonld", "model": "activity", "category_ids": ["musica"]})
        self.assertNotIn("rap", ev2["category_ids"])

    def test_legacy_classify_accepts_province_suffix_but_not_other_cities(self):
        ok = lambda place: collector.classify("Rap night", place, None, "Rap night")[0]
        self.assertEqual(ok("Sala Capitol Santiago De Compostela, A Coruña"), "Santiago de Compostela")
        self.assertEqual(ok("Sala Rouge Vigo, Pontevedra"), "Vigo")
        self.assertIsNone(ok("Palacio De La Ópera A Coruña"))
        self.assertIsNone(ok("Sala Queen Mos"))

    def test_known_venues_from_listings(self):
        for place, expected in (("Sala Sónar", "Santiago de Compostela"), ("Teatro Afundación", "Vigo"), ("Café Cultural Auriense", "Ourense")):
            ev, why = collector.to_activity(item("Concerto", place, ""), SRC)
            self.assertEqual(ev["municipality"] if ev else why, expected)
        self.assertIn("A Coruña", collector.to_activity(item("Concerto", "Sala Pantalán", ""), SRC)[1])

    def test_sources_json_is_valid_for_the_admin_validator(self):
        data = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
        out = server.validate_sources(data)
        ganzua = next(s for s in out if s["name"].startswith("La Ganzúa"))
        self.assertEqual(len(ganzua["urls"]), 5); self.assertTrue(all(u.startswith("https://www.laganzua.net/conciertos/") for u in ganzua["urls"]))


class TestHealthAndReview(Base):
    def write_sources(self, names, disabled=()):
        (CONF / "sources.json").write_text(json.dumps([{"name": n, "type": "ics", "url": "https://x.example/" + n, "enabled": n not in disabled} for n in names]))

    def tearDown(self): shutil.copyfile(ROOT / "sources.json", CONF / "sources.json")

    def test_health_alert_once_recovery_and_zero_items_count_as_bad(self):
        self.write_sources(["Salud A", "Salud B", "Salud C"], disabled=("Salud C",))
        sent = []
        with mock.patch.object(push, "_send", lambda p: sent.append(p) or (1, 0)), mock.patch.object(push, "available", lambda: True), \
             contextlib.redirect_stdout(io.StringIO()):
            core.record_source_run("Salud A", "ics", "error", error="HTTP 500")
            core.record_source_run("Salud A", "ics", "ok", fetched=0)                  # 0 elementos = mala
            self.assertEqual(push.notify_health(), 0)                                   # solo 2 seguidas
            core.record_source_run("Salud A", "ics", "ok", fetched=0)
            for _ in range(3): core.record_source_run("Salud C", "ics", "error", error="x")      # desactivada: se ignora
            self.assertEqual(push.notify_health(), 1)
            self.assertEqual(sent[0]["title"], "Rúa: fuente sin datos"); self.assertIn("Salud A", sent[0]["body"])
            sent.clear(); core.record_source_run("Salud A", "ics", "error", error="x")
            self.assertEqual(push.notify_health(), 0); self.assertEqual(sent, [])       # no repite
            core.record_source_run("Salud A", "ics", "ok", fetched=7)                   # se recupera
            self.assertEqual(core.consecutive_bad("Salud A"), 0); push.notify_health()
            for _ in range(3): core.record_source_run("Salud A", "ics", "ok", fetched=0)
            self.assertEqual(push.notify_health(), 1)                                   # nueva avería: avisa otra vez

    def test_health_without_push_does_not_mark_as_alerted(self):
        self.write_sources(["Salud D"])
        for _ in range(3): core.record_source_run("Salud D", "ics", "error", error="caída")
        with mock.patch.object(push, "available", lambda: False), contextlib.redirect_stdout(io.StringIO()) as out:
            push.notify_health()
        self.assertIn("Salud D", out.getvalue()); self.assertEqual(len(core.pending_source_alerts()), 1)   # sigue pendiente

    def test_status_endpoint_reports_unhealthy(self):
        self.write_sources(["Salud E"])
        for _ in range(3): core.record_source_run("Salud E", "ics", "ok", fetched=0)
        srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler); threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            data = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/api/status").read())
        finally:
            srv.shutdown(); srv.server_close()
        self.assertEqual(data["unhealthy"], 1)
        self.assertEqual(next(s for s in data["sources"] if s["name"] == "Salud E")["consecutive_bad"], 3)

    def test_inferred_interest_is_pending_but_source_category_is_not(self):
        ev, _ = collector.to_activity(item("Noite de rap", "Sala Rouge", "Vigo"), {**SRC, "category_ids": ["musica"]})
        self.assertEqual(ev["review"], "pending")
        plain, _ = collector.to_activity(item("Taller de cerámica", "Biblioteca - Ourense", "Ourense"), SRC)
        self.assertEqual(plain["review"], "")

    def test_reject_hides_everywhere_and_stays_rejected(self):
        a, _ = core.upsert_activity({"title": "Falso Positivo Rap", "municipality": "Vigo", "starts_at": day(80), "category_ids": ["musica", "rap"], "review": "pending"})
        self.assertIn("Falso Positivo Rap", [x["title"] for x in core.review_list("pending")])
        core.review_action(a, "reject")
        self.assertNotIn("Falso Positivo Rap", [x["title"] for x in core.get_activities()])
        sent = []
        with mock.patch.object(push, "_send", lambda p: sent.append(p) or (1, 0)), mock.patch.object(push, "available", lambda: True), \
             contextlib.redirect_stdout(io.StringIO()):
            push.notify_activities()
        self.assertFalse(any("Falso Positivo Rap" in p["title"] for p in sent))
        core.upsert_activity({"title": "Falso Positivo Rap", "municipality": "Vigo", "starts_at": day(80), "category_ids": ["rap"], "review": "pending"})
        self.assertNotIn("Falso Positivo Rap", [x["title"] for x in core.get_activities()])            # la fuente no lo resucita
        self.assertIn("Falso Positivo Rap", [x["title"] for x in core.review_list("rejected")])
        core.review_action(a, "restore"); self.assertIn("Falso Positivo Rap", [x["title"] for x in core.get_activities()])
        core.review_action(a, "confirm")
        self.assertNotIn("Falso Positivo Rap", [x["title"] for x in core.review_list("pending")])

    def test_review_validation_and_admin_api_requires_token(self):
        with self.assertRaises(ValueError): core.review_action(1, "borrar")
        with self.assertRaises(ValueError): core.review_action(999999, "confirm")
        with self.assertRaises(ValueError): core.review_list("otra")
        with self.assertRaises(ValueError): core.validate_activity({"title": "X", "municipality": "Vigo", "starts_at": D1, "category_ids": ["rap"], "review": "ok"})
        srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler); threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        def call(path, data=None, token=None):
            h = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
            r = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=h)
            try:
                with urllib.request.urlopen(r) as x: return x.status
            except urllib.error.HTTPError as e: return e.code
        try:
            self.assertEqual(call("/api/admin/review"), 403); self.assertEqual(call("/api/admin/review", {"id": 1, "action": "reject"}), 403)
            self.assertEqual(call("/api/admin/review", token="x" * 32), 403)
            self.assertEqual(call("/api/admin/review", token="t" * 32), 200)
            self.assertEqual(call("/api/admin/review?state=otra", token="t" * 32), 400)
            self.assertEqual(call("/api/admin/review", {"action": "confirm"}, token="t" * 32), 400)
            self.assertEqual(call("/api/admin/review", {"id": 999999, "action": "confirm"}, token="t" * 32), 400)
        finally:
            srv.shutdown(); srv.server_close()


class TestRound4(Base):
    def test_jsonld_pages_dedupe_repeated_cards(self):
        card = lambda n, d: f"""<script type="application/ld+json">{{"@type":"MusicEvent","name":"{n}","startDate":"{d}","url":"https://x.example/{n}",
          "location":{{"name":"Sala Rouge","address":{{"addressLocality":"Vigo"}}}}}}</script>"""
        p1 = (card("Al-Safir", D1) + card("Reality", D2)).encode(); p2 = (card("Al-Safir", D1) + card("Otro", D2)).encode()
        pages = {"https://www.laganzua.net/p1": p1, "https://www.laganzua.net/p2": p2}
        src = {"name": "G", "type": "jsonld", "url": "https://www.laganzua.net/p1", "urls": list(pages)}
        with mock.patch.object(collector, "polite_fetch", lambda u: pages[u]):
            items = list(collector.collect_jsonld_pages(src))
        self.assertEqual(sorted(i["title"] for i in items), ["Al-Safir", "Otro", "Reality"])

    def test_rss_source_is_disabled_with_reason_and_ics_stays(self):
        src = {s["name"]: s for s in json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))}
        rss = next(s for n, s in src.items() if "RSS oficial" in n)
        self.assertFalse(rss["enabled"]); self.assertIn("sin fecha", rss["disabled_reason"])
        self.assertTrue(next(s for n, s in src.items() if "Calendario ICS" in n)["enabled"])

    def test_gitignore_protects_database_and_keys(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("*.sqlite3", "*.pem", "__pycache__/", ".env"):
            self.assertIn(pattern, ignored)

    def test_dry_run_discard_lines_show_the_title(self):
        (CONF / "sources.json").write_text(json.dumps([{"name": "ICS dry", "type": "ics", "model": "activity", "url": "http://127.0.0.1:1/x", "enabled": True}]))
        ics = f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Evento en Lugo\nDTSTART;VALUE=DATE:{D1.replace('-', '')}\nLOCATION:Museo - Lugo\nEND:VEVENT\nEND:VCALENDAR\n".encode()
        out = io.StringIO()
        try:
            with mock.patch.object(collector, "fetch", lambda u: ics), contextlib.redirect_stdout(out): collector.run(dry=True)
        finally:
            shutil.copyfile(ROOT / "sources.json", CONF / "sources.json")
        self.assertIn("DESCARTADO: municipio fuera de ámbito (Lugo) | Evento en Lugo", out.getvalue())


import xml.etree.ElementTree as ET
import publish_static, apply_review, ci_notify


class TestFreeHosting(Base):
    def new(self, title, d=None, cats_=("musica", "rap"), **kw):
        return core.upsert_activity({"title": title, "municipality": "Vigo", "starts_at": d or day(90), "category_ids": list(cats_), "source_url": "https://x.example/" + title.replace(" ", "-"), **kw})[0]

    def test_static_site_files_and_privacy(self):
        self.new("Sitio Rap Uno", venue_name=None) if False else self.new("Sitio Rap Uno")
        self.new("Sitio Taller Uno", cats_=("talleres",))
        out = TMP / "site1"
        info = publish_static.build(str(out))
        self.assertGreaterEqual(info["highlighted"], 1)
        for name in ("index.html", "activities.json", "profile.json", "categories.json", "status.json", "feed.xml", ".nojekyll",
                     "api/activities", "api/profile", "api/categories", "api/status"):
            self.assertTrue((out / name).exists(), name)
        data = json.loads((out / "activities.json").read_text(encoding="utf-8"))
        self.assertEqual(data["count"], len(data["activities"]))
        for a in data["activities"]:
            self.assertNotIn("fingerprint", a); self.assertNotIn("created_at", a); self.assertNotIn("notified_at", a)
        self.assertEqual((out / "api" / "activities").read_text(encoding="utf-8"), (out / "activities.json").read_text(encoding="utf-8"))
        self.assertNotIn("Sitio Rap Uno", (out / "index.html").read_text(encoding="utf-8"))      # la página carga los datos, no los incrusta
        status = json.loads((out / "status.json").read_text(encoding="utf-8"))
        self.assertTrue(all("error" not in s and "url" not in s for s in status["sources"]))     # sin errores ni URLs internas

    def test_rss_only_highlighted_escaped_and_cancelled_marked(self):
        self.new("Rss <b>Rap</b> & Co"); self.new("Rss Taller", cats_=("talleres",)); self.new("Rss Cancelado Rap", status="cancelled")
        feed = publish_static.rss(core.get_activities(limit=1000), "https://u.github.io/rua", core.get_profile())
        root = ET.fromstring(feed)                       # XML válido aunque el título tenga <b> y &
        titles = [i.findtext("title") for i in root.iter("item")]
        self.assertIn("Rss <b>Rap</b> & Co", titles); self.assertIn("[CANCELADO] Rss Cancelado Rap", titles)
        self.assertNotIn("Rss Taller", titles)
        self.assertTrue(any("rua:activity:" in (g.text or "") and g.text.endswith(":cancelled") for g in root.iter("guid")))
        self.assertIn("https://u.github.io/rua/feed.xml", feed)

    def test_review_json_rejects_confirms_and_is_idempotent(self):
        a = self.new("Rev Falso Rap", d=day(91), review="pending"); self.new("Rev Bueno Rap", d=day(91), review="pending")
        self.new("Rev Falso Rap", d=day(92), review="pending")
        f = TMP / "review.json"
        f.write_text(json.dumps({"reject": [{"title": "rev falso rap", "date": day(91)}], "confirm": [{"title": "Rev Bueno Rap"}, {"title": "No Existe"}]}))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            n1 = apply_review.apply(f); n2 = apply_review.apply(f)
        self.assertEqual((n1, n2), (2, 2))                          # idempotente: mismo resultado, sin duplicar efectos
        self.assertIn("no coincide", out.getvalue())
        titles = [(x["title"], x["starts_at"][:10]) for x in core.get_activities()]
        self.assertNotIn(("Rev Falso Rap", day(91)), titles); self.assertIn(("Rev Falso Rap", day(92)), titles)   # la otra fecha sigue
        self.assertNotIn("Rev Bueno Rap", [x["title"] for x in core.review_list("pending")])
        core.upsert_activity({"title": "Rev Falso Rap", "municipality": "Vigo", "starts_at": day(91), "category_ids": ["rap"]})
        self.assertNotIn(("Rev Falso Rap", day(91)), [(x["title"], x["starts_at"][:10]) for x in core.get_activities()])   # no resucita

    def test_review_json_malformed_is_ignored_not_fatal(self):
        f = TMP / "bad.json"
        for content in ("{ no es json", json.dumps(["lista"]), json.dumps({"reject": "texto"}), json.dumps({"reject": [{"sin": "titulo"}]})):
            f.write_text(content)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(apply_review.apply(f), 0)
            self.assertIn("AVISO", out.getvalue())

    def test_ntfy_publishes_json_once_and_marks_only_on_success(self):
        push.notify_activities(mark_only=True) if False else None
        with mock.patch.object(push, "_send", lambda p: (1, 0)), mock.patch.object(push, "available", lambda: True), contextlib.redirect_stdout(io.StringIO()):
            push.notify_activities()                                 # marca todo lo anterior como ya avisado
        self.new("Ntfy Rap Ñandú — Edición", d=day(95))
        calls = []
        class Resp:
            status = 200
            def __enter__(s): return s
            def __exit__(s, *a): return False
        def fake_urlopen(req, timeout=0): calls.append(req); return Resp()
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "topic-largo-12345"}), mock.patch.object(ci_notify.urllib.request, "urlopen", fake_urlopen), \
             contextlib.redirect_stdout(io.StringIO()):
            ci_notify.main(); first = len(calls); ci_notify.main()
        self.assertEqual(first, 1); self.assertEqual(len(calls), 1)               # no repite
        body = json.loads(calls[0].data.decode("utf-8"))
        self.assertEqual(body["topic"], "topic-largo-12345"); self.assertIn("Ñandú — Edición", body["title"])
        self.assertTrue(body["click"].startswith("https://") or body["click"].startswith("http://"))
        # fallo de ntfy: no se marca como avisado y se reintenta en la siguiente ejecución
        self.new("Ntfy Fallo Rap", d=day(96))
        def boom(req, timeout=0): raise OSError("sin red")
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "topic-largo-12345"}), mock.patch.object(ci_notify.urllib.request, "urlopen", boom), contextlib.redirect_stdout(io.StringIO()):
            ci_notify.main()
        calls.clear()
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "topic-largo-12345"}), mock.patch.object(ci_notify.urllib.request, "urlopen", fake_urlopen), contextlib.redirect_stdout(io.StringIO()):
            ci_notify.main()
        self.assertEqual(len(calls), 1); self.assertIn("Ntfy Fallo Rap", json.loads(calls[0].data.decode())["message"] + json.loads(calls[0].data.decode())["title"])

    def test_ntfy_without_or_with_bad_topic_does_nothing(self):
        for env in ({}, {"NTFY_TOPIC": "corto"}, {"NTFY_TOPIC": "con espacios y símbolos!!"}):
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(ci_notify.urllib.request, "urlopen", side_effect=AssertionError("no debe publicar")), \
                 contextlib.redirect_stdout(io.StringIO()):
                if "NTFY_TOPIC" not in env: os.environ.pop("NTFY_TOPIC", None)
                self.assertEqual(ci_notify.main(), 0)

    def test_workflow_file_has_what_free_hosting_needs(self):
        wf = (ROOT / ".github" / "workflows" / "rua-agenda.yml").read_text(encoding="utf-8")
        for needle in ("cron:", "workflow_dispatch", "rua-state", "deploy-pages", "upload-pages-artifact", "NTFY_TOPIC",
                       "python collector.py --no-notify", "python apply_review.py", "python publish_static.py site", "pages: write"):
            self.assertIn(needle, wf)
        self.assertNotIn("secrets.GITHUB_TOKEN", wf.replace("github.token", ""))   # solo el token por defecto, sin secretos propios salvo ntfy


if __name__ == "__main__":
    unittest.main()
