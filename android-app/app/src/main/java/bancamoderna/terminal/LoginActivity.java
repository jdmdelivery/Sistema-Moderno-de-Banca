package bancamoderna.terminal;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;

import org.json.JSONObject;

/**
 * Inicio de sesión del operador (especificación §2.1): la terminal ya
 * está activada (serial + token); el operador entra con usuario y PIN
 * contra POST /terminal/login.
 */
public class LoginActivity extends Activity {
    private EditText usuarioTxt, pinTxt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Banca Moderna — Entrar");
        Prefs prefs = new Prefs(this);

        LinearLayout root = Ui.columna(this);
        root.addView(Ui.texto(this, "Sistema de Banca Moderna", 22, true));
        root.addView(Ui.texto(this, "Terminal: " + prefs.terminalSerial(), 14, false));

        usuarioTxt = Ui.campo(this, "Usuario del operador", InputType.TYPE_CLASS_TEXT);
        root.addView(usuarioTxt);

        pinTxt = Ui.campo(this, "PIN",
                InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        root.addView(pinTxt);

        Button entrar = Ui.boton(this, "ENTRAR");
        entrar.setOnClickListener(v -> entrar());
        root.addView(entrar);

        Button config = Ui.boton(this, "CONFIGURACIÓN DE LA TERMINAL");
        config.setOnClickListener(v -> {
            startActivity(new Intent(this, ConfigActivity.class));
        });
        root.addView(config);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
    }

    private void entrar() {
        String usuario = usuarioTxt.getText().toString().trim();
        String pin = pinTxt.getText().toString().trim();
        if (usuario.isEmpty() || pin.isEmpty()) {
            Ui.toast(this, "Escriba su usuario y su PIN.");
            return;
        }
        Prefs prefs = new Prefs(this);
        Ui.async(() -> {
                    JSONObject body = new JSONObject();
                    body.put("usuario", usuario);
                    body.put("pin", pin);
                    return new ApiClient(prefs).post("/terminal/login", body);
                },
                (JSONObject r) -> {
                    JSONObject operador = r.optJSONObject("operador");
                    JSONObject sucursal = r.optJSONObject("sucursal");
                    prefs.guardarSesion(
                            r.optString("token", ""),
                            operador != null ? operador.optString("nombre", usuario) : usuario,
                            sucursal != null ? sucursal.optString("nombre", "") : "");
                    Estado.saldo = r.optString("saldo", "");
                    startActivity(new Intent(this, MenuActivity.class));
                    finish();
                },
                (Exception e) -> Ui.toast(this,
                        e.getMessage() != null ? e.getMessage() : "No se pudo entrar"));
    }
}
