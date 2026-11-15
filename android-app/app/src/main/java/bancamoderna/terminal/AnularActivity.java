package bancamoderna.terminal;

import android.app.Activity;
import android.app.AlertDialog;
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
 * Anular Ticket (especificación §2.7): LECTURA escanea el QR (o se
 * teclea ID + Serial) y ANULAR pide al servidor anularlo. El servidor
 * solo anula tickets vendidos cuyos sorteos aún no han cerrado; si no
 * se puede, la app muestra el motivo exacto que responde el servidor.
 */
public class AnularActivity extends Activity {
    private EditText idTxt, serialTxt;
    private TextView detalleTxt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Anular Ticket de Lotería");

        LinearLayout root = Ui.columna(this);
        idTxt = Ui.campo(this, "ID del ticket", InputType.TYPE_CLASS_NUMBER);
        root.addView(idTxt);
        serialTxt = Ui.campo(this, "Serial del ticket", InputType.TYPE_CLASS_TEXT);
        root.addView(serialTxt);

        Button lectura = Ui.boton(this, "📷 LECTURA (ESCANEAR QR)");
        lectura.setOnClickListener(v -> startActivityForResult(
                new Intent(this, ScanActivity.class), PagarActivity.REQ_SCAN));
        root.addView(lectura);

        detalleTxt = Ui.texto(this, "", 16, false);
        root.addView(detalleTxt);

        Button anular = Ui.boton(this, "ANULAR");
        anular.setOnClickListener(v -> confirmar());
        root.addView(anular);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PagarActivity.REQ_SCAN && resultCode == RESULT_OK
                && data != null) {
            PagarActivity.aplicarQrEn(this, data.getStringExtra("texto"), idTxt, serialTxt);
        }
    }

    private void confirmar() {
        if (idTxt.getText().toString().trim().isEmpty()
                || serialTxt.getText().toString().trim().isEmpty()) {
            Ui.toast(this, "Escanee el ticket o escriba ID y Serial.");
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Anular ticket")
                .setMessage("La anulación no se puede deshacer y el efectivo "
                        + "se devuelve al cliente y sale de la caja. ¿Continuar?")
                .setNegativeButton("No", null)
                .setPositiveButton("SÍ, ANULAR", (d, w) -> anular())
                .show();
    }

    private void anular() {
        Prefs prefs = new Prefs(this);
        Ui.async(() -> {
                    JSONObject o = new JSONObject();
                    o.put("id", Integer.parseInt(idTxt.getText().toString().trim()));
                    o.put("serial", serialTxt.getText().toString().trim().toUpperCase());
                    return new ApiClient(prefs).post("/terminal/tickets/anular", o);
                },
                (JSONObject r) -> {
                    String msg = r.optString("mensaje", "");
                    detalleTxt.setText("🚫 TICKET ANULADO\n"
                            + (msg.isEmpty() ? TicketText.desdeJson(r) : msg));
                    Ui.toast(this, "Ticket anulado en el servidor.");
                },
                (Exception e) -> Ui.manejarError(this, e));
    }
}
