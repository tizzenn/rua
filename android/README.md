# Rúa para Android (cliente nativo)

Primera implementación del cliente Android de Rúa. Consume la API generalista ya existente del servidor v3.5; no duplica el recolector ni la base de datos.

## Funciones de esta versión

- Agenda de actividades desde `GET /api/activities`.
- Búsqueda de texto y filtros por municipio/categoría.
- Ficha con fecha, recinto, participantes, estado, verificación, fuente y entradas.
- Dirección del servidor configurable; exige HTTPS y no guarda credenciales.
- Avisos locales con WorkManager, consultando el servidor cada seis horas aproximadamente cuando Android lo permita.
- La primera consulta de avisos establece una línea base silenciosa; solo las actividades descubiertas después pueden generar notificación. Los IDs se guardan localmente para evitar repeticiones.
- Kotlin + Jetpack Compose + AndroidX; sin Firebase, Google Play Services, analítica ni SDK propietario.

## Compilar

Requisitos: JDK 17, Android SDK Platform 35 y Gradle 8.9 o compatible con Android Gradle Plugin 8.7.3.

Desde este directorio:

```bash
gradle assembleDebug
```

APK: `app/build/outputs/apk/debug/app-debug.apk`.

Para instalar en un dispositivo conectado:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

En el primer arranque, abre Ajustes y configura la URL HTTPS pública de tu instancia Rúa.

## Limitaciones conocidas de 0.1.0

- No hay cuenta ni registro público: el servidor sigue siendo autohospedado y el cliente es de solo lectura.
- Los avisos son sondeo periódico local, no push instantáneo. Android puede retrasar WorkManager por ahorro de batería. No depende de FCM.
- La publicación F-Droid/Play, firma de release, iconografía final, enlaces profundos, modo sin conexión y pruebas en dispositivos reales quedan pendientes.
- Esta versión aún no está compilada ni validada en un dispositivo físico; requiere compilarla en un entorno con Android SDK.
