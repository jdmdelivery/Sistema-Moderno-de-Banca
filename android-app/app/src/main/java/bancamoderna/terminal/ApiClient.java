package bancamoderna.terminal;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Cliente HTTP de la API de terminal del Sistema de Banca Moderna.
 * Autenticación en dos capas, como manda el servidor:
 *  - Cabeceras X-Terminal-Serial + X-Terminal-Token (la terminal activada).
 *  - Authorization: Bearer <sesión> tras el login del operador.
 * Los errores del servidor llegan como {"detail": "mensaje"} con su
 * código HTTP y se lanzan como ApiException para mostrarlos tal cual.
 */
public class ApiClient {

    public static class ApiException extends Exception {
        public final int status;

        public ApiException(int status, String mensaje) {
            super(mensaje);
            this.status = status;
        }
    }

    private final Prefs prefs;

    public ApiClient(Prefs prefs) {
        this.prefs = prefs;
    }

    public JSONObject get(String path) throws ApiException {
        return request("GET", path, null);
    }

    public JSONObject post(String path, JSONObject body) throws ApiException {
        return request("POST", path, body);
    }

    /** GET público sin credenciales de terminal (solo /health). */
    public JSONObject getPublico(String path) throws ApiException {
        return requestRaw("GET", path, null, false, false);
    }

    private JSONObject request(String method, String path, JSONObject body) throws ApiException {
        return requestRaw(method, path, body, true, true);
    }

    private JSONObject requestRaw(String method, String path, JSONObject body,
                                  boolean conTerminal, boolean conSesion) throws ApiException {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(prefs.serverUrl() + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod(method);
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(25000);
            conn.setRequestProperty("Accept", "application/json");
            if (conTerminal && prefs.activada()) {
                conn.setRequestProperty("X-Terminal-Serial", prefs.terminalSerial());
                conn.setRequestProperty("X-Terminal-Token", prefs.terminalToken());
            }
            if (conSesion && !prefs.sessionToken().isEmpty()) {
                conn.setRequestProperty("Authorization", "Bearer " + prefs.sessionToken());
            }
            if (body != null) {
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                byte[] datos = body.toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(datos);
                }
            }
            int code = conn.getResponseCode();
            String texto = leer(code >= 200 && code < 300
                    ? conn.getInputStream() : conn.getErrorStream());
            if (code >= 200 && code < 300) {
                return texto.isEmpty() ? new JSONObject() : new JSONObject(texto);
            }
            String detalle = null;
            if (!texto.isEmpty()) {
                try {
                    detalle = new JSONObject(texto).optString("detail", null);
                } catch (Exception ignored) {
                }
            }
            if (detalle == null || detalle.isEmpty()) {
                detalle = "Error del servidor (HTTP " + code + ")";
            }
            throw new ApiException(code, detalle);
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(0, "Sin conexión con el servidor: " + e.getMessage());
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private static String leer(InputStream in) throws Exception {
        if (in == null) return "";
        StringBuilder sb = new StringBuilder();
        try (BufferedReader br = new BufferedReader(
                new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String linea;
            while ((linea = br.readLine()) != null) sb.append(linea);
        }
        return sb.toString();
    }
}
