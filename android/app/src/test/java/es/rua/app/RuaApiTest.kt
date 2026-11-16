package es.rua.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class RuaApiTest {
    @Test fun trimsTrailingSlash() {
        assertEquals("https://agenda.example", RuaApi.normalizeBaseUrl(" https://agenda.example/// "))
    }

    @Test fun rejectsHttp() {
        assertThrows(IllegalArgumentException::class.java) { RuaApi.normalizeBaseUrl("http://agenda.example") }
    }

    @Test fun rejectsEmbeddedCredentials() {
        assertThrows(IllegalArgumentException::class.java) { RuaApi.normalizeBaseUrl("https://user:pass@agenda.example") }
    }
}
