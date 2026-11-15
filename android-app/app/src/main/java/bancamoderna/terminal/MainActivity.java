package bancamoderna.terminal;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/**
 * Puerta de entrada: sin activación → Configuración; activada pero sin
 * sesión → Login; con sesión → Menú principal.
 */
public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Prefs prefs = new Prefs(this);
        Class<?> destino;
        if (!prefs.activada()) {
            destino = ConfigActivity.class;
        } else if (prefs.sessionToken().isEmpty()) {
            destino = LoginActivity.class;
        } else {
            destino = MenuActivity.class;
        }
        startActivity(new Intent(this, destino));
        finish();
    }
}
