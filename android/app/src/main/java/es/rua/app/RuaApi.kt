package es.rua.app

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Cliente HTTP pequeño: sin SDKs propietarios ni dependencias de terceros. */
object RuaApi {
    fun activities(baseUrl: String): List<RuaActivity> {
        val base = normalizeBaseUrl(baseUrl)
        val connection = (URL("$base/api/activities").openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 10_000
            readTimeout = 15_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Cache-Control", "no-cache")
        }
        try {
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw IllegalStateException("El servidor respondió HTTP $code")
            val array = JSONObject(body).optJSONArray("activities") ?: return emptyList()
            return buildList {
                for (i in 0 until array.length()) {
                    val item = array.optJSONObject(i) ?: continue
                    add(RuaActivity(
                        id = item.optString("id"), title = item.optString("title", "Actividad"),
                        description = item.optString("description"), municipality = item.optString("municipality"),
                        venue = item.optString("venue"), address = item.optString("address"),
                        startsAt = item.optString("starts_at"), endsAt = item.optString("ends_at"),
                        eventType = item.optString("event_type"), status = item.optString("status"),
                        verification = item.optString("verification"), sourceName = item.optString("source_name"),
                        sourceUrl = item.optString("source_url"), ticketUrl = item.optString("ticket_url"),
                        announcedAt = item.optString("announced_at"), registrationOpensAt = item.optString("registration_opens_at"),
                        categories = item.optJSONArray("categories")?.let { a -> (0 until a.length()).map { a.optString(it) } }.orEmpty(),
                        entities = item.optJSONArray("entities")?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it)?.optString("name") } }.orEmpty()
                    ))
                }
            }
        } finally { connection.disconnect() }
    }

    fun normalizeBaseUrl(value: String): String {
        val clean = value.trim().trimEnd('/')
        require(clean.startsWith("https://")) {
            "La app requiere HTTPS para proteger la conexión con tu servidor."
        }
        require(!clean.contains('@')) { "La dirección no puede incluir credenciales." }
        return clean
    }
}

data class RuaActivity(
    val id: String, val title: String, val description: String, val municipality: String,
    val venue: String, val address: String, val startsAt: String, val endsAt: String,
    val eventType: String, val status: String, val verification: String,
    val sourceName: String, val sourceUrl: String, val ticketUrl: String,
    val announcedAt: String, val registrationOpensAt: String,
    val categories: List<String>, val entities: List<String>
)
