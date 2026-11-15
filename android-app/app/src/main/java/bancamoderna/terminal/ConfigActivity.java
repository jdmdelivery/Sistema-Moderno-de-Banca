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
 * Activación de la terminal (una sola vez): URL del servidor, serial
 * SUNMI de este equipo y token que el consorcio emite en el panel
 * (Panel → Terminales → crear/reactivar: el token se muestra una vez).
 */
public class ConfigActivity extends Activity {
    private EditText urlTxt, serialTxt, tokenTxt;
    private TextView estadoTxt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Banca Moderna — Configuración");
        Prefs prefs = new Prefs(this);

        LinearLayout root = Ui.columna(this);
        root.addView(Ui.texto(this, "Configuración de la terminal", 22, true));
        root.addView(Ui.texto(this,
                "Estos datos los entrega el consorcio. El token se ve una "
                        + "sola vez al crear la terminal en el panel.", 14, false));

        urlTxt = Ui.campo(this, "URL del servidor", InputType.TYPE_TEXT_VARIATION_URI);
        urlTxt.setText(prefs.serverUrl());
        root.addView(urlTxt);

        serialTxt = Ui.campo(this, "Serial SUNMI de esta terminal",
                InputType.TYPE_CLASS_TEXT);
        serialTxt.setText(prefs.terminalSerial());
        root.addView(serialTxt);

        tokenTxt = Ui.campo(this, "Token de la terminal",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        tokenTxt.setText(prefs.terminalToken());
        root.addView(tokenTxt);

        estadoTxt = Ui.texto(this, "", 15, false);
        root.addView(estadoTxt);

        Button probar = Ui.boton(this, "PROBAR CONEXIÓN");
        probar.setOnClickListener(v -> probarConexion());
        root.addView(probar);

        Button guardar = Ui.boton(this, "GUARDAR Y CONTINUAR");
        guardar.setOnClickListener(v -> {
            if (urlTxt.getText().toString().trim().isEmpty()
                    || serialTxt.getText().toString().trim().isEmpty()
                    || tokenTxt.getText().toString().trim().isEmpty()) {
                Ui.toast(this, "Complete la URL, el serial y el token.");
                return;
            }
            prefs.guardarActivacion(urlTxt.getText().toString(),
                    serialTxt.getText().toString(), tokenTxt.getText().toString());
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
        prefs.guardarActivacion(urlTxt.getText().toString(),
                prefs.terminalSerial(), prefs.terminalToken());
        estadoTxt.setText("Probando…");
        Ui.async(() -> new ApiClient(prefs).getPublico("/health"),
                (JSONObject r) -> estadoTxt.setText("Servidor OK: "
                        + r.optString("servicio", "") + " · "
                        + r.optString("hora", "")),
                (Exception e) -> estadoTxt.setText("No responde: " + e.getMessage()));
    }
}
