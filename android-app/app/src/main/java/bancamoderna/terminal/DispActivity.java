package bancamoderna.terminal;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ScrollView;

import org.json.JSONObject;

/**
 * Selector de loterías DISP (especificación §2.4): selección múltiple
 * de los sorteos que sirve el servidor. Un sorteo cerrado aparece
 * deshabilitado con su motivo («CERRADO …»): no se puede marcar.
 */
public class DispActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("DISP — Loterías");

        LinearLayout root = Ui.columna(this);
        root.addView(Ui.texto(this, "Marque las loterías de la jugada:", 16, true));

        for (JSONObject s : Estado.sorteos) {
            int id = s.optInt("id");
            boolean abierto = s.optBoolean("abierto", false);
            CheckBox cb = new CheckBox(this);
            String etiqueta = s.optString("nombre")
                    + "  (cierra " + s.optString("hora_cierre") + ")";
            if (!abierto) {
                etiqueta += "  — CERRADO: " + s.optString("motivo_cierre", "");
            }
            cb.setText(etiqueta);
            cb.setTextSize(16);
            cb.setEnabled(abierto);
            cb.setChecked(abierto && Estado.seleccion.contains(id));
            cb.setOnCheckedChangeListener((v, marcada) -> {
                if (marcada) {
                    Estado.seleccion.add(id);
                } else {
                    Estado.seleccion.remove(id);
                }
            });
            root.addView(cb);
        }

        Button retornar = Ui.boton(this, "RETORNAR");
        retornar.setOnClickListener(v -> finish());
        root.addView(retornar);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
    }
}
