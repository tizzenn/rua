package es.rua.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

object RuaNotifications {
    const val CHANNEL_ID = "rua_new_activities"
    private const val WORK_NAME = "rua-periodic-sync"

    fun schedule(context: Context, enabled: Boolean) {
        val manager = WorkManager.getInstance(context)
        if (!enabled) {
            manager.cancelUniqueWork(WORK_NAME)
            return
        }
        val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val request = PeriodicWorkRequestBuilder<RuaSyncWorker>(6, TimeUnit.HOURS)
            .setConstraints(constraints).build()
        manager.enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.UPDATE, request)
    }

    fun channel(context: Context) {
        if (Build.VERSION.SDK_INT >= 26) {
            val channel = NotificationChannel(CHANNEL_ID, "Nuevas actividades", NotificationManager.IMPORTANCE_DEFAULT)
            channel.description = "Avisos de nuevas actividades publicadas en Rúa"
            context.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    fun hasPermission(context: Context): Boolean = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
}

class RuaSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("rua", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("notifications_enabled", false)) return Result.success()
        val base = prefs.getString("server_url", "")?.takeIf { it.isNotBlank() } ?: return Result.failure()
        return try {
            val activities = RuaApi.activities(base)
            val ids = activities.map { it.id.ifBlank { "${it.title}|${it.municipality}|${it.startsAt}" } }.toSet()
            val previous = prefs.getStringSet("known_activity_ids", emptySet()).orEmpty()
            if (!prefs.getBoolean("baseline_initialized", false)) {
                prefs.edit().putStringSet("known_activity_ids", ids).putBoolean("baseline_initialized", true).apply()
                return Result.success()
            }
            val newOnes = activities.filter { activity ->
                val id = activity.id.ifBlank { "${activity.title}|${activity.municipality}|${activity.startsAt}" }
                id !in previous
            }
            if (newOnes.isNotEmpty() && RuaNotifications.hasPermission(applicationContext)) {
                RuaNotifications.channel(applicationContext)
                val manager = applicationContext.getSystemService(NotificationManager::class.java)
                val first = newOnes.take(3)
                val text = first.joinToString(" · ") { "${it.title} (${it.municipality})" }
                val notification = androidx.core.app.NotificationCompat.Builder(applicationContext, RuaNotifications.CHANNEL_ID)
                    .setSmallIcon(android.R.drawable.ic_dialog_info)
                    .setContentTitle(if (newOnes.size == 1) "Nueva actividad en Rúa" else "${newOnes.size} novedades en Rúa")
                    .setContentText(text).setStyle(androidx.core.app.NotificationCompat.BigTextStyle().bigText(text))
                    .setAutoCancel(true).build()
                manager.notify(1001, notification)
            }
            // Persistimos IDs aunque Android haya revocado el permiso: no se repite una novedad antigua.
            prefs.edit().putStringSet("known_activity_ids", (previous + ids).toSet()).apply()
            Result.success()
        } catch (_: Exception) { Result.retry() }
    }
}
