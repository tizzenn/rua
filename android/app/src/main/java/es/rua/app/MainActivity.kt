package es.rua.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

private val Ink = Color(0xFF111111)
private val SurfaceDark = Color(0xFF1C1C1C)
private val Accent = Color(0xFFE65B43)
private val Muted = Color(0xFFAAAAAA)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        RuaNotifications.channel(this)
        setContent { RuaTheme { RuaHome() } }
    }
}

@Composable
private fun RuaTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(primary = Accent, secondary = Color(0xFFFFB19F), background = Ink,
            surface = SurfaceDark, onPrimary = Color.White, onBackground = Color.White, onSurface = Color.White),
        content = content
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RuaHome() {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("rua", Context.MODE_PRIVATE) }
    var serverUrl by remember { mutableStateOf(prefs.getString("server_url", "") ?: "") }
    var notifications by remember { mutableStateOf(prefs.getBoolean("notifications_enabled", false)) }
    var activities by remember { mutableStateOf<List<RuaActivity>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var lastUpdated by remember { mutableStateOf<String?>(null) }
    var search by remember { mutableStateOf("") }
    var city by remember { mutableStateOf("Todas") }
    var category by remember { mutableStateOf("Todas") }
    var settingsOpen by remember { mutableStateOf(serverUrl.isBlank()) }
    val scope = rememberCoroutineScope()

    fun refresh() {
        if (serverUrl.isBlank()) { settingsOpen = true; return }
        scope.launch {
            loading = true; error = null
            try {
                activities = withContext(Dispatchers.IO) { RuaApi.activities(serverUrl) }
                lastUpdated = java.time.LocalDateTime.now().format(DateTimeFormatter.ofPattern("HH:mm", Locale("es", "ES")))
            } catch (e: Exception) { error = e.message ?: "No se pudo conectar con Rúa." }
            finally { loading = false }
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        notifications = granted
        prefs.edit().putBoolean("notifications_enabled", granted).apply()
        RuaNotifications.schedule(context, granted)
    }

    LaunchedEffect(serverUrl) { if (serverUrl.isNotBlank()) refresh() }

    val categories = remember(activities) { activities.flatMap { it.categories }.distinct().sorted() }
    val visible = remember(activities, search, city, category) {
        activities.filter { a ->
            (city == "Todas" || a.municipality.equals(city, true)) &&
            (category == "Todas" || a.categories.any { it.equals(category, true) }) &&
            listOf(a.title, a.description, a.municipality, a.venue, a.entities.joinToString(" "), a.categories.joinToString(" "))
                .joinToString(" ").contains(search, ignoreCase = true)
        }
    }

    Scaffold(containerColor = Ink, topBar = {
        TopAppBar(
            title = { Column { Text("RÚA", fontWeight = FontWeight.Black, letterSpacing = 3.sp); Text("AGENDA ABIERTA", fontSize = 10.sp, color = Muted, letterSpacing = 2.sp) } },
            actions = {
                IconButton(onClick = { settingsOpen = true }) { Text("⚙", fontSize = 22.sp) }
                TextButton(onClick = { refresh() }, enabled = !loading) { Text(if (loading) "…" else "ACTUALIZAR", color = Accent) }
            }, colors = TopAppBarDefaults.topAppBarColors(containerColor = Ink, titleContentColor = Color.White)
        )
    }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Surface(color = if (error == null && activities.isNotEmpty()) Color(0xFF214D38) else Color(0xFF4A3028), shape = RoundedCornerShape(50)) {
                    Text(if (error == null && activities.isNotEmpty()) "  CONECTADO  " else "  ${if (error != null) "SIN CONEXIÓN" else "CONFIGURA EL SERVIDOR"}  ", modifier = Modifier.padding(vertical = 5.dp), fontSize = 10.sp, fontWeight = FontWeight.Bold)
                }
                Spacer(Modifier.width(10.dp))
                Text(lastUpdated?.let { "Actualizado $it" } ?: "", color = Muted, fontSize = 11.sp)
                Spacer(Modifier.weight(1f))
                Text("${visible.size} eventos", color = Muted, fontSize = 12.sp)
            }
            if (error != null) Text(error!!, color = Color(0xFFFF9D88), modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp), fontSize = 12.sp)
            OutlinedTextField(value = search, onValueChange = { search = it }, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                placeholder = { Text("Buscar artistas, salas, actividades…", color = Muted) }, singleLine = true,
                shape = RoundedCornerShape(12.dp), colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Accent, unfocusedBorderColor = Color.DarkGray))
            FilterRow("CIUDAD", listOf("Todas", "Ourense", "Vigo", "Santiago de Compostela"), city) { city = it }
            if (categories.isNotEmpty()) FilterRow("CATEGORÍA", listOf("Todas") + categories, category) { category = it }
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("AVISOS", fontSize = 10.sp, color = Muted, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                Spacer(Modifier.weight(1f))
                Text(if (notifications) "Cada 6 h aprox." else "Desactivados", fontSize = 11.sp, color = Muted)
                Switch(checked = notifications, onCheckedChange = { enabled ->
                    if (enabled && Build.VERSION.SDK_INT >= 33 && !RuaNotifications.hasPermission(context)) permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                    else {
                        notifications = enabled; prefs.edit().putBoolean("notifications_enabled", enabled).apply()
                        RuaNotifications.schedule(context, enabled)
                    }
                }, modifier = Modifier.height(32.dp))
            }
            HorizontalDivider(color = Color(0xFF333333))
            if (!loading && visible.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(28.dp)) {
                        Text(if (error != null) "No se pudo cargar la agenda" else "Todavía no hay actividades", fontSize = 18.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(8.dp))
                        Text(if (error != null) "Comprueba la dirección del servidor y vuelve a intentarlo." else "Cuando las fuentes publiquen actividades verificadas, aparecerán aquí.", color = Muted)
                        Spacer(Modifier.height(18.dp))
                        TextButton(onClick = { if (error != null) settingsOpen = true else refresh() }) { Text(if (error != null) "CONFIGURAR SERVIDOR" else "RECARGAR", color = Accent) }
                    }
                }
            } else {
                LazyColumn(contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    items(visible, key = { it.id.ifBlank { it.title + it.startsAt } }) { ActivityCard(it) }
                }
            }
        }
    }

    if (settingsOpen) ServerSettingsDialog(serverUrl, notifications, onDismiss = { settingsOpen = false }, onSave = { value ->
        try {
            serverUrl = RuaApi.normalizeBaseUrl(value)
            prefs.edit().putString("server_url", serverUrl).apply()
            settingsOpen = false
        } catch (e: Exception) { error = e.message }
    })
}

@Composable
private fun FilterRow(label: String, options: List<String>, selected: String, onSelect: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(top = 5.dp)) {
        Text(label, color = Muted, fontSize = 9.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp, modifier = Modifier.padding(horizontal = 16.dp, vertical = 3.dp))
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            options.forEach { option ->
                FilterChip(selected = selected == option, onClick = { onSelect(option) }, label = { Text(option, fontSize = 11.sp) },
                    colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Accent, selectedLabelColor = Color.White))
            }
        }
    }
}

@Composable
private fun ActivityCard(activity: RuaActivity) {
    val context = LocalContext.current
    val date = activity.startsAt.take(10).let { raw ->
        runCatching { LocalDate.parse(raw).format(DateTimeFormatter.ofPattern("EEE, d MMM", Locale("es", "ES"))).uppercase(Locale("es", "ES")) }.getOrDefault(raw)
    }
    val status = when (activity.status.lowercase()) {
        "scheduled" -> "PROGRAMADO"
        "cancelled" -> "CANCELADO"
        "postponed" -> "APLAZADO"
        "completed" -> "FINALIZADO"
        else -> activity.status.ifBlank { "ESTADO PENDIENTE" }.uppercase()
    }
    val verification = when (activity.verification.lowercase()) {
        "official" -> "FUENTE OFICIAL"
        "multiple_sources" -> "VARIAS FUENTES"
        "single_source" -> "UNA FUENTE"
        "unverified" -> "SIN VERIFICAR"
        else -> activity.verification.ifBlank { "VERIFICACIÓN PENDIENTE" }.uppercase()
    }
    Card(colors = CardDefaults.cardColors(containerColor = SurfaceDark), shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(15.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(date, color = Accent, fontSize = 11.sp, fontWeight = FontWeight.Black, letterSpacing = 1.sp)
                Spacer(Modifier.weight(1f))
                Text(status, color = if (activity.status == "scheduled") Color(0xFF8DD6A8) else Color(0xFFFFC08A), fontSize = 9.sp, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(4.dp))
            Text(verification, color = Muted, fontSize = 9.sp, letterSpacing = 0.8.sp)
            Spacer(Modifier.height(8.dp))
            Text(activity.title, fontSize = 19.sp, fontWeight = FontWeight.Bold, lineHeight = 23.sp)
            if (activity.entities.isNotEmpty()) Text(activity.entities.joinToString(" · "), color = Color(0xFFFFB19F), fontSize = 13.sp)
            Spacer(Modifier.height(5.dp))
            Text(listOf(activity.municipality, activity.venue).filter { it.isNotBlank() }.joinToString(" · "), color = Muted, fontSize = 12.sp)
            if (activity.categories.isNotEmpty()) {
                Spacer(Modifier.height(9.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) { activity.categories.take(3).forEach { AssistChip(onClick = {}, label = { Text(it, fontSize = 10.sp) }, enabled = false) } }
            }
            if (activity.description.isNotBlank()) {
                Spacer(Modifier.height(7.dp)); Text(activity.description, color = Color(0xFFCCCCCC), fontSize = 12.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
            val dates = listOfNotNull(activity.announcedAt.takeIf { it.isNotBlank() }?.let { "Anuncio: $it" }, activity.registrationOpensAt.takeIf { it.isNotBlank() }?.let { "Preventa: $it" })
            if (dates.isNotEmpty()) { Spacer(Modifier.height(7.dp)); Text(dates.joinToString(" · "), color = Muted, fontSize = 10.sp) }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                if (activity.sourceUrl.startsWith("https://")) TextButton(onClick = { openUrl(context, activity.sourceUrl) }) { Text("FUENTE ↗", color = Muted, fontSize = 10.sp) }
                if (activity.ticketUrl.startsWith("https://")) TextButton(onClick = { openUrl(context, activity.ticketUrl) }) { Text("ENTRADAS ↗", color = Accent, fontSize = 10.sp, fontWeight = FontWeight.Bold) }
            }
        }
    }
}

private fun openUrl(context: Context, url: String) {
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
}

@Composable
private fun ServerSettingsDialog(current: String, notifications: Boolean, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    var value by remember(current) { mutableStateOf(current) }
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text("Conectar con tu Rúa") },
        text = {
            Column {
                Text("Introduce la dirección HTTPS de tu servidor. No añadas /api al final.", color = Muted, fontSize = 13.sp)
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(value = value, onValueChange = { value = it }, label = { Text("https://rua.tudominio.es") }, singleLine = true)
                Spacer(Modifier.height(8.dp))
                Text("Los avisos se consultan en segundo plano aproximadamente cada 6 horas. La primera sincronización crea una línea base y no genera avisos antiguos.", color = Muted, fontSize = 11.sp)
            }
        },
        confirmButton = { TextButton(onClick = { onSave(value) }) { Text("GUARDAR", color = Accent) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("CANCELAR") } },
        containerColor = SurfaceDark)
}
