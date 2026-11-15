package bancamoderna.terminal;

import android.app.Activity;
import android.graphics.Typeface;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * Ticket confirmado por el servidor tras una venta: muestra el número
 * (ID), el serial y el detalle, y ofrece imprimirlo en la térmica
 * Sunmi. La venta ya existe en el servidor antes de imprimir; si la
 * impresión falla, aquí mismo se puede reintentar sin vender de nuevo.
 */
public class TicketActivity extends Activity {
    private SunmiPrinter impresora;
    private TextView estadoImpresion;
    private JSONObject ticket;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Ticket vendido");
        impresora = new SunmiPrinter();
        impresora.enlazar(this);

        LinearLayout root = Ui.columna(this);
        root.addView(Ui.texto(this, "✅ VENTA CONFIRMADA", 20, true));

        String json = getIntent().getStringExtra("ticket_json");
        try {
            ticket = new JSONObject(json != null ? json : "{}");
        } catch (Exception e) {
            ticket = new JSONObject();
        }

        TextView detalle = new TextView(this);
        detalle.setTypeface(Typeface.MONOSPACE);
        detalle.setTextSize(15);
        detalle.setText(TicketText.desdeJson(ticket)
                + "\nQR: " + ticket.optString("qr", ""));
        root.addView(detalle);

        estadoImpresion = Ui.texto(this, "", 15, false);
        root.addView(estadoImpresion);

        Button imprimir = Ui.boton(this, "🖨 IMPRIMIR TICKET");
        imprimir.setOnClickListener(v -> imprimir());
        root.addView(imprimir);

        Button volver = Ui.boton(this, "NUEVA VENTA");
        volver.setOnClickListener(v -> finish());
        root.addView(volver);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
    }

    private void imprimir() {
        estadoImpresion.setText("Imprimiendo…");
        impresora.imprimir(TicketText.desdeJson(ticket),
                ticket.optString("qr", ""),
                new SunmiPrinter.Resultado() {
                    @Override
                    public void ok() {
                        runOnUiThread(() ->
                                estadoImpresion.setText("Ticket impreso ✔"));
                    }

                    @Override
                    public void error(String mensaje) {
                        runOnUiThread(() -> estadoImpresion.setText(mensaje));
                    }
                });
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (impresora != null) impresora.desenlazar(this);
    }
}
