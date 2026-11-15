package bancamoderna.terminal;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * Menú principal (especificación §2.2). En esta primera versión trae
 * las funciones de lotería de la Fase 1: vender, pagar y anular, más la
 * configuración y el cierre de sesión. Sin botones decorativos: los
 * módulos de reportes/caja se agregan cuando se entreguen.
 */
public class MenuActivity extends Activity {
    private TextView saldoTxt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Banca Moderna — Menú");
        Prefs prefs = new Prefs(this);

        LinearLayout root = Ui.columna(this);
        root.addView(Ui.texto(this, prefs.sucursalNombre(), 20, true));
        root.addView(Ui.texto(this, "Operador: " + prefs.operadorNombre(), 15, false));
        saldoTxt = Ui.texto(this, "", 16, true);
        root.addView(saldoTxt);
        root.addView(Ui.separador(this));

        Button loteria = Ui.boton(this, "LOTERÍA (VENDER)");
        loteria.setOnClickListener(v ->
                startActivity(new Intent(this, VentaActivity.class)));
        root.addView(loteria);

        Button pagar = Ui.boton(this, "PAGAR TICKET");
        pagar.setOnClickListener(v ->
                startActivity(new Intent(this, PagarActivity.class)));
        root.addView(pagar);

        Button anular = Ui.boton(this, "ANULAR TICKET");
        anular.setOnClickListener(v ->
                startActivity(new Intent(this, AnularActivity.class)));
        root.addView(anular);

        root.addView(Ui.separador(this));

        Button config = Ui.boton(this, "CONFIGURACIÓN");
        config.setOnClickListener(v ->
                startActivity(new Intent(this, ConfigActivity.class)));
        root.addView(config);

        Button salir = Ui.boton(this, "CERRAR SESIÓN");
        salir.setOnClickListener(v -> {
            prefs.cerrarSesion();
            startActivity(new Intent(this, LoginActivity.class));
            finish();
        });
        root.addView(salir);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
    }

    @Override
    protected void onResume() {
        super.onResume();
        mostrarSaldo();
        // Refresca el saldo real desde el servidor.
        Prefs prefs = new Prefs(this);
        Ui.async(() -> new ApiClient(prefs).get("/terminal/sorteos"),
                (JSONObject r) -> {
                    Estado.saldo = r.optString("saldo", Estado.saldo);
                    mostrarSaldo();
                },
                (Exception e) -> {
                    // Silencioso: el menú sigue usable; Venta recargará.
                });
    }

    private void mostrarSaldo() {
        if (Estado.saldo != null && !Estado.saldo.isEmpty()) {
            saldoTxt.setText("Dinero en caja: $" + Ui.dinero(Estado.saldo));
        }
    }
}
