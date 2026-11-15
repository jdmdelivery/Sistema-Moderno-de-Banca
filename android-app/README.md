# Banca Moderna — App de terminal (Android)

App nativa (Java, sin frameworks) para las terminales SUNMI de las bancas.
Habla con la API de terminal del **Sistema de Banca Moderna**
(`apps/api` de este mismo proyecto). Versión 0.1.0.

- **applicationId:** `do.bancamoderna.terminal`
  (el paquete del código es `bancamoderna.terminal` porque «do» es
  palabra reservada de Java y no puede ser el namespace; el ID
  instalado en el equipo es el requerido).
- **minSdk 24** (Android 7.0 — cubre las SUNMI con Android 7–11),
  **targetSdk 34**.
- **APK actual:** `dist/banca-moderna-terminal-debug.apk`
  (343,419 bytes, SHA-256
  `0adc5cab1b73fd97ab9647a7a85fc3881368c33783410d4dac496fb0cbd20ba7`),
  build **debug** firmado con la clave de depuración de Android:
  instalable tal cual para pruebas. Para producción habrá que firmar
  un release con una clave propia del consorcio.

## Qué hace esta primera versión (sin pantallas decorativas)

1. **Configuración y activación:** URL del servidor precargada
   (`https://sistema-de-banca-moderna.onrender.com`, editable) +
   serial SUNMI + token de terminal (los que emite el panel).
   Botón «Probar conexión» contra `/health`.
2. **Inicio de sesión** del operador (usuario + contraseña) contra
   `POST /terminal/login`.
3. **Venta** fiel a la especificación: botón **DISP** con selección
   múltiple de los sorteos abiertos (los cerrados se muestran
   deshabilitados con su motivo), tipos **QN / PL / SP** con las
   validaciones del servidor (QN 2 dígitos; PL dos números distintos;
   SP exactamente dos sorteos), teclado grande con foco
   NÚMEROS/MONTO, lista de jugadas, total con la misma regla de costo
   del servidor (QN/PL: monto por lotería; SP: el monto una vez) y
   confirmación antes de vender. Al vender muestra el ticket con su
   **ID global y Serial**, su QR `LOT:{id}:{serial}` y el saldo
   restante, con botón **IMPRIMIR**.
4. **Pagar ticket:** por ID + Serial o con **LECTURA** (cámara +
   ZXing, sin servicios de Google): CONSULTAR muestra estado y
   premios; PAGAR solo se habilita si el servidor dice que se puede
   pagar (nadie cobra dos veces).
5. **Anular ticket:** por ID + Serial o LECTURA, con confirmación; el
   servidor valida que sea del día y de la misma sucursal.
6. **Impresión SUNMI real** con la librería oficial
   `com.sunmi:printerlibrary:1.0.24` de Maven Central: enlaza con el
   servicio interno de impresión (`InnerPrinterManager`), imprime el
   ticket a 32 columnas con el QR grande y corta el papel. En un
   equipo que no sea SUNMI el enlace falla y la app lo dice en
   pantalla (la venta ya quedó registrada en el servidor; el ticket
   se reimprime desde una SUNMI).

Quedan fuera de esta v1 (existen en la API y se pueden añadir):
caja/cuadre y reportes desde la terminal.

## Cómo se instala en la SUNMI

1. Copiar `dist/banca-moderna-terminal-debug.apk` a la terminal
   (USB, Bluetooth, WhatsApp/Drive, o descargándolo desde un enlace).
2. En la SUNMI: Ajustes → Seguridad → permitir «Orígenes
   desconocidos» / «Instalar apps desconocidas» para el gestor de
   archivos o el navegador usado.
3. Abrir el .apk y tocar **Instalar**. Aparece como **«Banca
   Moderna»**.

## Cómo se activa una terminal real

1. En el **panel del consorcio** (la URL del servidor, usuario
   administrador): sección **Terminales** → elegir la sucursal,
   número de terminal y escribir el **Serial SUNMI** del equipo
   (está en la etiqueta del equipo y en sus ajustes; es el mismo
   «S/N» que se ve en los tickets) → Guardar.
2. El panel muestra el **token de la terminal UNA SOLA VEZ**:
   copiarlo en ese momento.
3. En la app: pantalla **Configuración de la terminal** → la URL ya
   viene precargada → escribir el **Serial SUNMI** y el **token** →
   «Probar conexión» debe decir «Servidor alcanzado ✔» → **Guardar**.
4. Volver e **iniciar sesión** con el usuario y la contraseña de un operador
   creado en el panel para esa sucursal. Si el serial/token no
   coinciden con el panel, el servidor responde «Terminal no
   autorizada» y la app lo muestra tal cual.

## Cómo se compila el APK

```bash
cd ~/workspace/sistema-loteria/android-app
./build-apk.sh        # deja el APK en dist/
```

Toolchain durable bajo `~/workspace/` (sobrevive reinicios de la VM):

| Pieza | Versión | Ruta |
|---|---|---|
| JDK Temurin | 17.0.21+9 | `~/workspace/jdk` |
| Android SDK cmdline-tools | 11076708 | `~/workspace/android-sdk/cmdline-tools/latest` |
| Plataforma | android-34 | `~/workspace/android-sdk/platforms/android-34` |
| Build-tools | 34.0.0 | `~/workspace/android-sdk/build-tools/34.0.0` |
| Platform-tools (adb) | 37.0.3 | `~/workspace/android-sdk/platform-tools` |
| Gradle | 8.2 (+ wrapper en el proyecto) | `~/workspace/gradle-8.2` |
| Caché y config de Gradle | — | `~/workspace/.gradle` |

El SDK se instaló **a mano desde los ZIP oficiales** de
dl.google.com: el `sdkmanager` no puede descargar en esta VM (su
cliente HTTP muere en el túnel del proxy de salida). Las licencias
están aceptadas en `~/workspace/android-sdk/licenses/`.

**Peculiaridades de red de esta máquina** (documentadas también en
`build-apk.sh`): la salida pasa por el proxy
`hatch-egress-proxy:3128`; su IPv4 está interceptada y no sirve para
Java (se fuerza `java.net.preferIPv6Addresses=true`) y el proxy
intercepta el TLS con su propia CA (se genera una vez el truststore
`~/workspace/.gradle/hatch-cacerts.jks` desde
`/run/hatch/egress-tls/ca-bundle.pem`). Además el demonio de Gradle
no funciona aquí (su registro en 127.0.0.1 se pierde), así que el
script llama al binario de Gradle desempaquetado con `--no-daemon`
en vez de `./gradlew`, y el proyecto no fija `org.gradle.jvmargs`.

## Límites conocidos

- **La impresión solo se puede verificar en una SUNMI física**: la
  librería oficial está integrada y el código imprime por el
  servicio real, pero en esta máquina no hay impresora SUNMI; en un
  teléfono normal la app vende/paga/anula igual y avisa de que no
  hay impresora SUNMI enlazada.
- **Build debug** (clave de depuración): sirve para instalar y
  probar hoy; no es la firma de producción.
- **El servidor en vivo usa hoy una base SQLite temporal** (decisión
  de Jose del 2026-11-14): los datos se borran si el servicio de
  Render se reinicia. La app no depende de eso; cuando se conecte la
  base definitiva no hay que tocarla.
- **Sin venta offline** (así lo define la Fase 1 de la
  especificación): sin conexión, la app no vende.
- La cámara usa la API clásica de Android con ZXing: suficiente para
  el QR de los tickets en las SUNMI; lee el QR en vertical u
  horizontal.
