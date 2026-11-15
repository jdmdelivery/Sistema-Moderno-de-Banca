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
 * Pagar Ticket (especificación §2.8): LECTURA escanea el QR (o se
 * teclea ID + Serial) → CONSULTAR trae el estado real del servidor →
 * PAGAR TICKET solo se habilita si el servidor dice que hay premio
 * pendiente. El pago es atómico en el servidor: un solo pago posible.
 */
public class PagarActivity extends Activity {
    static final int REQ_SCAN = 41;

    private EditText idTxt, serialTxt;
    private TextView detalleTxt;
    private Button pagarBtn;
    private JSONObject ultimoTicket;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Pagar Ticket de Lotería");

        LinearLayout root = Ui.columna(this);
        idTxt = Ui.campo(this, "ID del ticket", InputType.TYPE_CLASS_NUMBER);
        root.addView(idTxt);
        serialTxt = Ui.campo(this, "Serial del ticket", InputType.TYPE_CLASS_TEXT);
        root.addView(serialTxt);

        Button lectura = Ui.boton(this, "📷 LECTURA (ESCANEAR QR)");
        lectura.setOnClickListener(v ->
                startActivityForResult(new Intent(this, ScanActivity.class), REQ_SCAN));
        root.addView(lectura);

        Button consultar = Ui.boton(this, "CONSULTAR");
        consultar.setOnClickListener(v -> consultar());
        root.addView(consultar);

        detalleTxt = Ui.texto(this, "", 16, false);
        root.addView(detalleTxt);

        pagarBtn = Ui.boton(this, "PAGAR TICKET");
        pagarBtn.setEnabled(false);
        pagarBtn.setOnClickListener(v -> confirmarPago());
        root.addView(pagarBtn);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_SCAN && resultCode == RESULT_OK && data != null) {
            String texto = data.getStringExtra("texto");
            aplicarQr(texto);
        }
    }

    /** El QR del ticket contiene LOT:{id}:{serial}. */
    static void aplicarQrEn(Activity a, String texto, EditText idTxt, EditText serialTxt) {
        if (texto == null) return;
        String t = texto.trim();
        if (t.startsWith("LOT:")) t = t.substring(4);
        String[] partes = t.split(":");
        if (partes.length >= 2) {
            idTxt.setText(partes[0].trim());
            serialTxt.setText(partes[1].trim().toUpperCase());
        } else {
            Ui.toast(a, "El código leído no es un ticket válido: " + texto);
        }
    }

    private void aplicarQr(String texto) {
        aplicarQrEn(this, texto, idTxt, serialTxt);
        if (!idTxt.getText().toString().isEmpty()) consultar();
    }

    private JSONObject llave() throws Exception {
        JSONObject o = new JSONObject();
        o.put("id", Integer.parseInt(idTxt.getText().toString().trim()));
        o.put("serial", serialTxt.getText().toString().trim().toUpperCase());
        return o;
    }

    private void consultar() {
        if (idTxt.getText().toString().trim().isEmpty()
                || serialTxt.getText().toString().trim().isEmpty()) {
            Ui.toast(this, "Escanee el ticket o escriba ID y Serial.");
            return;
        }
        pagarBtn.setEnabled(false);
        Prefs prefs = new Prefs(this);
        Ui.async(() -> new ApiClient(prefs).post("/terminal/tickets/consultar", llave()),
                (JSONObject r) -> {
                    ultimoTicket = r;
                    StringBuilder sb = new StringBuilder();
                    sb.append(r.optString("mensaje", "")).append("\n");
                    sb.append("Ticket ").append(r.optInt("id"))
                            .append(" · ").append(r.optString("banca", ""))
                            .append(" · ").append(r.optString("fecha_hora", ""))
                            .append("\nEstado: ").append(r.optString("estado", ""));
                    if (r.optBoolean("puede_pagar", false)) {
                        sb.append("\n💰 MONTO A PAGAR: $")
                                .append(Ui.dinero(r.optString("premio_total", "0")));
                    }
                    detalleTxt.setText(sb.toString());
                    pagarBtn.setEnabled(r.optBoolean("puede_pagar", false));
                },
                (Exception e) -> Ui.manejarError(this, e));
    }

    private void confirmarPago() {
        if (ultimoTicket == null) return;
        new AlertDialog.Builder(this)
                .setTitle("Confirmar pago")
                .setMessage("¿Ya entregó al cliente $"
                        + Ui.dinero(ultimoTicket.optString("premio_total", "0"))
                        + "?\nEl pago se registra una sola vez en el servidor.")
                .setNegativeButton("Todavía no", null)
                .setPositiveButton("SÍ, PAGAR", (d, w) -> pagar())
                .show();
    }

    private void pagar() {
        Prefs prefs = new Prefs(this);
        Ui.async(() -> new ApiClient(prefs).post("/terminal/tickets/pagar", llave()),
                (JSONObject r) -> {
                    pagarBtn.setEnabled(false);
                    detalleTxt.setText("✅ PAGADO\n" + TicketText.desdeJson(r));
                    Ui.toast(this, "Pago registrado en el servidor.");
                },
                (Exception e) -> Ui.manejarError(this, e));
    }
}
