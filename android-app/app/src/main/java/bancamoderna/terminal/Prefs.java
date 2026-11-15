package bancamoderna.terminal;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Configuración de la terminal y sesión del operador.
 * La terminal se activa UNA vez con el serial SUNMI y el token que emite
 * el panel del consorcio (Panel → Terminales). La sesión (Bearer) se
 * obtiene en el login del operador y se guarda hasta cerrar sesión.
 */
public class Prefs {
    public static final String URL_DEFECTO = "https://sistema-de-banca-moderna.onrender.com";

    private final SharedPreferences sp;

    public Prefs(Context ctx) {
        sp = ctx.getSharedPreferences("bancamoderna", Context.MODE_PRIVATE);
    }

    public String serverUrl() {
        String u = sp.getString("server_url", URL_DEFECTO);
        if (u == null || u.trim().isEmpty()) u = URL_DEFECTO;
        u = u.trim();
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    public String terminalSerial() {
        return sp.getString("terminal_serial", "");
    }

    public String terminalToken() {
        return sp.getString("terminal_token", "");
    }

    public boolean activada() {
        return !terminalSerial().isEmpty() && !terminalToken().isEmpty();
    }

    public void guardarActivacion(String url, String serial, String token) {
        sp.edit()
                .putString("server_url", url.trim())
                .putString("terminal_serial", serial.trim())
                .putString("terminal_token", token.trim())
                .apply();
    }

    public String sessionToken() {
        return sp.getString("session_token", "");
    }

    public String operadorNombre() {
        return sp.getString("operador_nombre", "");
    }

    public String sucursalNombre() {
        return sp.getString("sucursal_nombre", "");
    }

    public void guardarSesion(String token, String operador, String sucursal) {
        sp.edit()
                .putString("session_token", token)
                .putString("operador_nombre", operador)
                .putString("sucursal_nombre", sucursal)
                .apply();
    }

    public void cerrarSesion() {
        sp.edit().remove("session_token").remove("operador_nombre")
                .remove("sucursal_nombre").apply();
    }
}
