package bancamoderna.terminal;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * Estado en memoria compartido entre la pantalla de Venta y el selector
 * DISP: la lista de sorteos servida por el servidor y la selección
 * múltiple en curso. Vive solo mientras la app está abierta.
 */
public final class Estado {
    public static final List<JSONObject> sorteos = new ArrayList<>();
    public static final LinkedHashSet<Integer> seleccion = new LinkedHashSet<>();
    public static String saldo = "";

    private Estado() {
    }

    public static void cargarSorteos(JSONArray arr) {
        sorteos.clear();
        for (int i = 0; i < arr.length(); i++) {
            sorteos.add(arr.optJSONObject(i));
        }
        // La selección solo conserva sorteos que siguen abiertos.
        seleccion.removeIf(id -> {
            JSONObject s = porId(id);
            return s == null || !s.optBoolean("abierto", false);
        });
    }

    public static JSONObject porId(int id) {
        for (JSONObject s : sorteos) {
            if (s.optInt("id") == id) return s;
        }
        return null;
    }

    public static String nombresSeleccion() {
        List<String> nombres = new ArrayList<>();
        for (Integer id : seleccion) {
            JSONObject s = porId(id);
            if (s != null) nombres.add(s.optString("nombre"));
        }
        return nombres.isEmpty() ? "(ninguna: pulse DISP)" : Ui.unir(nombres, ", ");
    }
}
