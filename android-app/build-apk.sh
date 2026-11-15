#!/usr/bin/env bash
# Compila el APK de la app de terminal «Banca Moderna» desde cero.
#
# Toolchain durable bajo ~/workspace (sobrevive reinicios de la VM):
#   JDK 17 (Temurin)      -> ~/workspace/jdk
#   Android SDK           -> ~/workspace/android-sdk
#   Gradle + su caché     -> ~/workspace/gradle-8.2 y ~/workspace/.gradle
#
# Uso:  ./build-apk.sh
# Salida: dist/banca-moderna-terminal-debug.apk (firmado con la clave
# debug de Android: instalable en la Sunmi para pruebas).
#
# Peculiaridades de red de ESTA máquina (descubiertas en la Etapa 3):
#  - La salida pasa por el proxy hatch-egress-proxy:3128. Su dirección
#    IPv4 (198.19.0.1) está interceptada por el cortafuegos del entorno
#    y NO sirve para Java; la IPv6 sí. Por eso se fuerza
#    java.net.preferIPv6Addresses=true.
#  - El proxy intercepta el TLS con su propia CA (la del bundle en
#    /run/hatch/egress-tls/ca-bundle.pem). Java no la trae: se genera
#    un truststore con ese bundle en $GRADLE_USER_HOME/hatch-cacerts.jks
#    (una sola vez) y se le pasa a Gradle.
#  - Gradle NO debe llevar org.gradle.jvmargs propio en el proyecto:
#    con jvmargs bifurca un demonio y el enlace cliente<->demonio falla
#    en esta VM (el demonio escucha en 127.0.0.1 y su registro se pierde:
#    «Could not receive a message from the daemon»). Por la misma razón
#    este script llama al binario de la distribución desempaquetada
#    (~/workspace/gradle-8.2) en vez de ./gradlew: el wrapper arranca con
#    sus propios JVM opts, Gradle bifurca el demonio de un solo uso y el
#    build muere. Con el binario directo y --no-daemon el build corre
#    en el proceso del cliente y funciona. El wrapper queda generado en
#    el proyecto para entornos normales.
set -euo pipefail

export JAVA_HOME="${JAVA_HOME:-$HOME/workspace/jdk}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/workspace/android-sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$HOME/workspace/.gradle}"

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

mkdir -p "$GRADLE_USER_HOME"

# --- Proxy para Gradle (sin credenciales: con credenciales da 407) ---
if [ ! -f "$GRADLE_USER_HOME/gradle.properties" ]; then
  cat > "$GRADLE_USER_HOME/gradle.properties" <<'EOF'
systemProp.http.proxyHost=hatch-egress-proxy
systemProp.http.proxyPort=3128
systemProp.https.proxyHost=hatch-egress-proxy
systemProp.https.proxyPort=3128
systemProp.http.nonProxyHosts=localhost|127.0.0.1
systemProp.https.nonProxyHosts=localhost|127.0.0.1
EOF
fi

# --- Truststore con la CA del proxy de salida (una sola vez) ---
TRUSTSTORE="$GRADLE_USER_HOME/hatch-cacerts.jks"
if [ ! -f "$TRUSTSTORE" ]; then
  echo "Generando truststore con la CA del entorno (una sola vez)..."
  python3 - "$TRUSTSTORE" <<'PYEOF'
import re, subprocess, sys, os, tempfile
ks = sys.argv[1]
data = open('/run/hatch/egress-tls/ca-bundle.pem').read()
certs = re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
                   data, re.S)
tmp = tempfile.mkdtemp()
for i, c in enumerate(certs):
    p = os.path.join(tmp, f'c{i}.pem')
    open(p, 'w').write(c)
    subprocess.run([os.path.expanduser('~/workspace/jdk/bin/keytool'),
                    '-importcert', '-noprompt', '-storepass', 'changeit',
                    '-keystore', ks, '-alias', f'c{i}', '-file', p],
                   capture_output=True)
    os.remove(p)
print(f"truststore con {len(certs)} certificados")
PYEOF
fi

export GRADLE_OPTS="-Xmx1536m -Djava.net.preferIPv6Addresses=true -Djavax.net.ssl.trustStore=$TRUSTSTORE -Djavax.net.ssl.trustStorePassword=changeit"

printf 'sdk.dir=%s\n' "$ANDROID_HOME" > local.properties

GRADLE_BIN="$HOME/workspace/gradle-8.2/bin/gradle"
if [ -x "$GRADLE_BIN" ]; then
  "$GRADLE_BIN" --no-daemon assembleDebug
else
  ./gradlew --no-daemon assembleDebug
fi

mkdir -p dist
cp app/build/outputs/apk/debug/app-debug.apk dist/banca-moderna-terminal-debug.apk
echo "APK listo: $APP_DIR/dist/banca-moderna-terminal-debug.apk"
ls -la dist/
