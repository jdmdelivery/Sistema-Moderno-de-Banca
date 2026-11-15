package bancamoderna.terminal;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/**
 * Puerta de entrada: sin sesión → Login (usuario y contraseña);
 * con sesión → Menú principal. Sin activación de terminal.
 */
public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Prefs prefs = new Prefs(this);
        Class<?> destino = prefs.sessionToken().isEmpty()
                ? LoginActivity.class : MenuActivity.class;
        startActivity(new Intent(this, destino));
        finish();
    }
}
