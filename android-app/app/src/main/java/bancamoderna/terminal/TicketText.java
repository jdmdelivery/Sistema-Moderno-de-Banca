package bancamoderna.terminal;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Formato del ticket en texto para la térmica de 58 mm (32 columnas),
 * con los campos de la especificación §3.3: banca, fecha/hora, ID,
 * serial, S/N de la terminal, una línea por jugada y MONTO TOTAL.
 * El QR se imprime aparte (contenido LOT:{id}:{serial}).
 */
public final class TicketText {
    private static final int ANCHO = 32;

    private TicketText() {
    }

    public static String desdeJson(JSONObject t) {
        StringBuilder sb = new StringBuilder();
        String banca = t.optString("banca", "BANCA");
        String codigo = t.optString("banca_codigo", "");
        sb.append(centrar((banca + " " + codigo).trim())).append("\n");
        sb.append(centrar("Sistema de Banca Moderna")).append("\n");
        sb.append(linea()).append("\n");
        sb.append("FECHA: ").append(t.optString("fecha_hora", "")).append("\n");
        sb.append("TICKET: ").append(t.optInt("id")).append("\n");
        sb.append("SERIAL: ").append(t.optString("serial", "")).append("\n");
        String sn = t.optString("terminal_serial", "");
        if (!sn.isEmpty() && !"null".equals(sn)) {
            sb.append("S/N TERMINAL: ").append(sn).append("\n");
        }
        sb.append(linea()).append("\n");
        JSONArray jugadas = t.optJSONArray("jugadas");
        if (jugadas != null) {
            for (int i = 0; i < jugadas.length(); i++) {
                JSONObject j = jugadas.optJSONObject(i);
                if (j == null) continue;
                JSONArray lots = j.optJSONArray("loterias");
                StringBuilder nombres = new StringBuilder();
                if (lots != null) {
                    for (int k = 0; k < lots.length(); k++) {
                        if (k > 0) nombres.append(" - ");
                        nombres.append(lots.optString(k));
                    }
                }
                sb.append(j.optString("tipo_nombre", j.optString("tipo", "")))
                        .append(" -> ").append(nombres).append("\n");
                String numeros = j.optString("numeros", "");
                String monto = "$" + Ui.dinero(j.optString("monto", "0"));
                sb.append("  ").append(izqDer(numeros, monto)).append("\n");
                String premio = j.optString("premio", null);
                if (premio != null && !"null".equals(premio)) {
                    sb.append("  PREMIO: $").append(Ui.dinero(premio)).append("\n");
                }
            }
        }
        sb.append(linea()).append("\n");
        String estado = t.optString("estado", "");
        if (!estado.isEmpty()) {
            sb.append("ESTADO: ").append(estado.toUpperCase()).append("\n");
        }
        sb.append("MONTO TOTAL: $").append(Ui.dinero(t.optString("total", "0"))).append("\n");
        return sb.toString();
    }

    private static String linea() {
        return Ui.repetir("-", ANCHO);
    }

    private static String centrar(String s) {
        if (s.length() >= ANCHO) return s;
        int pad = (ANCHO - s.length()) / 2;
        return Ui.repetir(" ", pad) + s;
    }

    private static String izqDer(String izq, String der) {
        int espacio = ANCHO - 2 - izq.length() - der.length();
        if (espacio < 1) espacio = 1;
        return izq + Ui.repetir(" ", espacio) + der;
    }
}
