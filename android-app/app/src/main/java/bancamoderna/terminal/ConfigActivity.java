package bancamoderna.terminal;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * Configuración: SOLO la URL del servidor. Ya no hay activación ni token
 * (2026-11-14): la terminal entra con el usuario y la contraseña del
 * operador. La URL viene precargada con el servidor del consorcio y solo
 * se toca si el consorcio cambia de servidor.
 */
public class ConfigActivity extends Activity {
    private EditText urlTxt;
    private TextView estadoTxt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Banca Moderna — Configuración");
        Prefs prefs = new Prefs(this);

        LinearLayout root = Ui.columna(this);
        root.addView(Ui.texto(this, "Configuración", 22, true));
        root.addView(Ui.texto(this,
                "La terminal entra con su usuario y contraseña; no necesita "
                        + "ningún código. Aquí solo se cambia el servidor si "
                        + "el consorcio lo mueve.", 14, false));

        urlTxt = Ui.campo(this, "URL del servidor", InputType.TYPE_TEXT_VARIATION_URI);
        urlTxt.setText(prefs.serverUrl());
        root.addView(urlTxt);

        estadoTxt = Ui.texto(this, "", 15, false);
        root.addView(estadoTxt);

        Button probar = Ui.boton(this, "PROBAR CONEXIÓN");
        probar.setOnClickListener(v -> probarConexion());
        root.addView(probar);

        Button guardar = Ui.boton(this, "GUARDAR");
        guardar.setOnClickListener(v -> {
            if (urlTxt.getText().toString().trim().isEmpty()) {
                Ui.toast(this, "Escriba la URL del servidor.");
                return;
            }
            prefs.guardarUrl(urlTxt.getText().toString());
            prefs.cerrarSesion();
            startActivity(new Intent(this, LoginActivity.class));
            finish();
        });
        root.addView(guardar);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
    }

    private void probarConexion() {
        Prefs prefs = new Prefs(this);
        // Se prueba con la URL escrita aunque aún no se haya guardado.
        prefs.guardarUrl(urlTxt.getText().toString());
        estadoTxt.setText("Probando…");
        Ui.async(() -> new ApiClient(prefs).getPublico("/health"),
                (JSONObject r) -> estadoTxt.setText("Servidor OK: "
                        + r.optString("servicio", "") + " · "
                        + r.optString("hora", "")),
                (Exception e) -> estadoTxt.setText("No responde: " + e.getMessage()));
    }
}
