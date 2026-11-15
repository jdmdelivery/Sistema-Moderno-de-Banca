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
 * Inicio de sesión del operador (especificación §2.1): entra SOLO con
 * su usuario y contraseña contra POST /terminal/login. Sin activación
 * ni token: el servidor resuelve su sucursal y su terminal.
 */
public class LoginActivity extends Activity {
    private EditText usuarioTxt, claveTxt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Banca Moderna — Entrar");
        Prefs prefs = new Prefs(this);

        LinearLayout root = Ui.columna(this);
        root.addView(Ui.texto(this, "Sistema de Banca Moderna", 22, true));
        root.addView(Ui.texto(this, "Entre con su usuario y contraseña", 14, false));

        usuarioTxt = Ui.campo(this, "Usuario del operador", InputType.TYPE_CLASS_TEXT);
        root.addView(usuarioTxt);

        claveTxt = Ui.campo(this, "Contraseña",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(claveTxt);

        Button entrar = Ui.boton(this, "ENTRAR");
        entrar.setOnClickListener(v -> entrar());
        root.addView(entrar);

        Button config = Ui.boton(this, "CONFIGURACIÓN");
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
        String clave = claveTxt.getText().toString().trim();
        if (usuario.isEmpty() || clave.isEmpty()) {
            Ui.toast(this, "Escriba su usuario y su contraseña.");
            return;
        }
        Prefs prefs = new Prefs(this);
        Ui.async(() -> {
                    JSONObject body = new JSONObject();
                    body.put("usuario", usuario);
                    body.put("clave", clave);
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
