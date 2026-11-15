package bancamoderna.terminal;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Button;
import android.widget.GridLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Pantalla de venta (especificación §2.3 + §2.5): teclado numérico
 * grande, tipos QN/PL/SP, selector DISP de loterías (selección múltiple
 * de sorteos abiertos), lista de jugadas del ticket en curso y Total en
 * vivo. VENDER manda el ticket completo al servidor: solo si el
 * servidor confirma se pasa a la pantalla del ticket para imprimir.
 */
public class VentaActivity extends Activity {

    private static class Jugada {
        String tipo;
        List<Integer> sorteos;
        String numeros; // "19" (QN) o "26-58" (PL/SP)
        double monto;

        double costo() {
            // QN/PL se replican por lotería (monto por lotería);
            // SP cruza dos loterías y cuesta el monto una sola vez.
            return "SP".equals(tipo) ? monto : monto * sorteos.size();
        }
    }

    private final List<Jugada> jugadas = new ArrayList<>();
    // Idempotencia: un UUID por ticket en curso; si el envío se reintenta
    // (doble toque, red), el servidor devuelve el mismo ticket sin duplicar.
    private String operacionId = java.util.UUID.randomUUID().toString();
    private String tipoActual = "QN";
    private StringBuilder digitos = new StringBuilder();
    private boolean focoMonto = false;
    private StringBuilder montoDigitos = new StringBuilder();

    private TextView sorteosTxt, numerosTxt, montoTxt, totalTxt, saldoTxt;
    private LinearLayout listaJugadas;
    private Button[] tipoBtns;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Lotería — Venta");
        construirUi();
        cargarSorteos();
    }

    private void construirUi() {
        LinearLayout root = Ui.columna(this);

        saldoTxt = Ui.texto(this, "", 15, true);
        root.addView(saldoTxt);

        Button disp = Ui.boton(this, "DISP — ELEGIR LOTERÍAS");
        disp.setOnClickListener(v -> {
            if (Estado.sorteos.isEmpty()) {
                Ui.toast(this, "Todavía no cargan los sorteos.");
                return;
            }
            startActivity(new Intent(this, DispActivity.class));
        });
        root.addView(disp);
        sorteosTxt = Ui.texto(this, "", 15, false);
        root.addView(sorteosTxt);

        // Tipo de jugada
        LinearLayout filaTipos = new LinearLayout(this);
        filaTipos.setOrientation(LinearLayout.HORIZONTAL);
        String[] tipos = {"QN", "PL", "SP"};
        String[] nombres = {"QN Quiniela", "PL Palé", "SP Súper Palé"};
        tipoBtns = new Button[tipos.length];
        for (int i = 0; i < tipos.length; i++) {
            final String t = tipos[i];
            Button b = new Button(this);
            b.setText(nombres[i]);
            b.setLayoutParams(new LinearLayout.LayoutParams(0,
                    LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            b.setOnClickListener(v -> {
                tipoActual = t;
                digitos.setLength(0);
                marcarTipo();
                refrescar();
            });
            tipoBtns[i] = b;
            filaTipos.addView(b);
        }
        root.addView(filaTipos);

        numerosTxt = Ui.texto(this, "NÚMEROS: ", 22, true);
        numerosTxt.setOnClickListener(v -> {
            focoMonto = false;
            refrescar();
        });
        root.addView(numerosTxt);

        montoTxt = Ui.texto(this, "MONTO: $", 22, true);
        montoTxt.setOnClickListener(v -> {
            focoMonto = true;
            refrescar();
        });
        root.addView(montoTxt);
        root.addView(Ui.texto(this,
                "Toque NÚMEROS o MONTO para escribir con el teclado.", 12, false));

        root.addView(teclado());

        Button agregar = Ui.boton(this, "AGREGAR JUGADA");
        agregar.setOnClickListener(v -> agregarJugada());
        root.addView(agregar);

        root.addView(Ui.separador(this));
        root.addView(Ui.texto(this, "Jugadas del ticket (toque una para quitarla):",
                15, true));
        listaJugadas = new LinearLayout(this);
        listaJugadas.setOrientation(LinearLayout.VERTICAL);
        root.addView(listaJugadas);

        totalTxt = Ui.texto(this, "Total: $0.00", 22, true);
        root.addView(totalTxt);

        Button vender = Ui.boton(this, "VENDER (JUGAR)");
        vender.setOnClickListener(v -> vender());
        root.addView(vender);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
        marcarTipo();
        refrescar();
    }

    private GridLayout teclado() {
        GridLayout g = new GridLayout(this);
        g.setColumnCount(3);
        String[] teclas = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "←"};
        for (String k : teclas) {
            Button b = new Button(this);
            b.setText(k);
            b.setTextSize(22);
            GridLayout.LayoutParams lp = new GridLayout.LayoutParams();
            lp.width = 0;
            lp.columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1f);
            lp.setMargins(3, 3, 3, 3);
            b.setLayoutParams(lp);
            b.setOnClickListener(v -> tecla(k));
            g.addView(b);
        }
        return g;
    }

    private void tecla(String k) {
        StringBuilder destino = focoMonto ? montoDigitos : digitos;
        switch (k) {
            case "C":
                destino.setLength(0);
                break;
            case "←":
                if (destino.length() > 0) destino.deleteCharAt(destino.length() - 1);
                break;
            default:
                int max = focoMonto ? 7 : ("QN".equals(tipoActual) ? 2 : 4);
                if (destino.length() < max) destino.append(k);
        }
        refrescar();
    }

    private String numerosFormateados() {
        String d = digitos.toString();
        if ("QN".equals(tipoActual)) return d;
        if (d.length() <= 2) return d;
        return d.substring(0, 2) + "-" + d.substring(2);
    }

    private void marcarTipo() {
        String[] tipos = {"QN", "PL", "SP"};
        for (int i = 0; i < tipos.length; i++) {
            tipoBtns[i].setEnabled(!tipos[i].equals(tipoActual));
        }
    }

    private void refrescar() {
        sorteosTxt.setText("Loterías: " + Estado.nombresSeleccion());
        numerosTxt.setText((focoMonto ? "NÚMEROS: " : "▶ NÚMEROS: ") + numerosFormateados());
        montoTxt.setText((focoMonto ? "▶ MONTO: $" : "MONTO: $") + montoDigitos.toString());
        if (!Estado.saldo.isEmpty()) {
            saldoTxt.setText("Caja: $" + Ui.dinero(Estado.saldo));
        }
        listaJugadas.removeAllViews();
        double total = 0;
        for (int i = 0; i < jugadas.size(); i++) {
            Jugada j = jugadas.get(i);
            total += j.costo();
            List<String> nombres = new ArrayList<>();
            for (Integer id : j.sorteos) {
                JSONObject s = Estado.porId(id);
                if (s != null) nombres.add(s.optString("nombre"));
            }
            TextView fila = Ui.texto(this,
                    (i + 1) + ". " + j.tipo + " " + j.numeros + " · "
                            + Ui.unir(nombres, ", ") + " · $"
                            + Ui.dinero(String.valueOf(j.costo())), 16, false);
            final int idx = i;
            fila.setOnClickListener(v -> {
                jugadas.remove(idx);
                refrescar();
            });
            listaJugadas.addView(fila);
        }
        totalTxt.setText("Total: $" + Ui.dinero(String.valueOf(total)));
    }

    private void agregarJugada() {
        if (Estado.seleccion.isEmpty()) {
            Ui.toast(this, "Primero elija las loterías con DISP.");
            return;
        }
        int esperados = "QN".equals(tipoActual) ? 2 : 4;
        if (digitos.length() != esperados) {
            Ui.toast(this, "QN".equals(tipoActual)
                    ? "La quiniela lleva un número de 2 cifras."
                    : "Esta jugada lleva dos números (ej. 26-58).");
            return;
        }
        if ("SP".equals(tipoActual) && Estado.seleccion.size() != 2) {
            Ui.toast(this, "El Súper Palé cruza exactamente dos loterías.");
            return;
        }
        double monto;
        try {
            monto = Double.parseDouble(montoDigitos.toString());
        } catch (Exception e) {
            monto = 0;
        }
        if (monto <= 0) {
            Ui.toast(this, "Escriba el monto de la jugada.");
            return;
        }
        String numeros = numerosFormateados();
        if (!"QN".equals(tipoActual)) {
            String[] p = numeros.split("-");
            if (p.length == 2 && p[0].equals(p[1])) {
                Ui.toast(this, "Los dos números de la pareja deben ser diferentes.");
                return;
            }
        }
        Jugada j = new Jugada();
        j.tipo = tipoActual;
        j.sorteos = new ArrayList<>(Estado.seleccion);
        j.numeros = numeros;
        j.monto = monto;
        jugadas.add(j);
        digitos.setLength(0);
        montoDigitos.setLength(0);
        focoMonto = false;
        refrescar();
    }

    private void cargarSorteos() {
        Prefs prefs = new Prefs(this);
        Ui.async(() -> new ApiClient(prefs).get("/terminal/sorteos"),
                (JSONObject r) -> {
                    Estado.cargarSorteos(r.optJSONArray("sorteos") != null
                            ? r.optJSONArray("sorteos") : new JSONArray());
                    Estado.saldo = r.optString("saldo", Estado.saldo);
                    refrescar();
                },
                (Exception e) -> Ui.manejarError(this, e));
    }

    @Override
    protected void onResume() {
        super.onResume();
        refrescar(); // la selección pudo cambiar en DISP
    }

    private void vender() {
        if (jugadas.isEmpty()) {
            Ui.toast(this, "El ticket no tiene jugadas.");
            return;
        }
        double total = 0;
        for (Jugada j : jugadas) total += j.costo();
        new AlertDialog.Builder(this)
                .setTitle("Confirmar venta")
                .setMessage("Total del ticket: $" + Ui.dinero(String.valueOf(total))
                        + "\n¿Vender ahora?")
                .setNegativeButton("Volver", null)
                .setPositiveButton("VENDER", (d, w) -> enviarVenta())
                .show();
    }

    private void enviarVenta() {
        Prefs prefs = new Prefs(this);
        Ui.async(() -> {
                    JSONArray arr = new JSONArray();
                    for (Jugada j : jugadas) {
                        JSONObject o = new JSONObject();
                        o.put("tipo", j.tipo);
                        JSONArray ss = new JSONArray();
                        for (Integer id : j.sorteos) ss.put(id);
                        o.put("sorteos", ss);
                        o.put("numeros", j.numeros);
                        o.put("monto", j.monto);
                        arr.put(o);
                    }
                    JSONObject body = new JSONObject();
                    body.put("jugadas", arr);
                    body.put("operacion_id", operacionId);
                    return new ApiClient(prefs).post("/terminal/venta", body);
                },
                (JSONObject ticket) -> {
                    jugadas.clear();
                    operacionId = java.util.UUID.randomUUID().toString();
                    Intent i = new Intent(this, TicketActivity.class);
                    i.putExtra("ticket_json", ticket.toString());
                    startActivity(i);
                    cargarSorteos(); // refresca saldo y cierres
                    refrescar();
                },
                (Exception e) -> Ui.manejarError(this, e));
    }
}
