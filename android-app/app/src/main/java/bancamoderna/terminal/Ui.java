package bancamoderna.terminal;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Utilidades pequeñas de UI (sin librerías externas) y de hilos. */
public final class Ui {
    private static final ExecutorService EXEC = Executors.newCachedThreadPool();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private Ui() {
    }

    public interface Fondo {
        void run() throws Exception;
    }

    public interface Listo<T> {
        void run(T valor);
    }

    /** Ejecuta trabajo de red fuera del hilo principal y vuelve a la UI. */
    public static <T> void async(CallableBg<T> trabajo, Listo<T> ok, Listo<Exception> error) {
        EXEC.execute(() -> {
            try {
                T v = trabajo.call();
                MAIN.post(() -> ok.run(v));
            } catch (Exception e) {
                MAIN.post(() -> error.run(e));
            }
        });
    }

    public interface CallableBg<T> {
        T call() throws Exception;
    }

    public static int dp(Activity a, int dp) {
        return (int) (dp * a.getResources().getDisplayMetrics().density + 0.5f);
    }

    public static TextView texto(Activity a, String s, float sp, boolean negrita) {
        TextView t = new TextView(a);
        t.setText(s);
        t.setTextSize(sp);
        if (negrita) t.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        return t;
    }

    public static Button boton(Activity a, String s) {
        Button b = new Button(a);
        b.setText(s);
        b.setTextSize(17);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(a, 6), 0, dp(a, 6));
        b.setLayoutParams(lp);
        return b;
    }

    public static EditText campo(Activity a, String hint, int inputType) {
        EditText e = new EditText(a);
        e.setHint(hint);
        e.setTextSize(18);
        e.setInputType(inputType);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(a, 4), 0, dp(a, 4));
        e.setLayoutParams(lp);
        return e;
    }

    public static LinearLayout columna(Activity a) {
        LinearLayout l = new LinearLayout(a);
        l.setOrientation(LinearLayout.VERTICAL);
        int p = dp(a, 14);
        l.setPadding(p, p, p, p);
        return l;
    }

    public static void toast(Activity a, String s) {
        Toast.makeText(a, s, Toast.LENGTH_LONG).show();
    }

    /** Si la sesión venció (401), se limpia y se vuelve al login. */
    public static boolean manejarError(Activity a, Exception e) {
        if (e instanceof ApiClient.ApiException
                && ((ApiClient.ApiException) e).status == 401) {
            new Prefs(a).cerrarSesion();
            Ui.toast(a, "La sesión venció. Entre de nuevo.");
            a.startActivity(new android.content.Intent(a, LoginActivity.class));
            a.finish();
            return true;
        }
        Ui.toast(a, e.getMessage() != null ? e.getMessage() : "Error inesperado");
        return false;
    }

    /** String.join no existe en Android 7.0/7.1 (API 24/25): unir a mano. */
    public static String unir(java.util.List<String> partes, String separador) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < partes.size(); i++) {
            if (i > 0) sb.append(separador);
            sb.append(partes.get(i));
        }
        return sb.toString();
    }

    /** String.repeat es de API 31+: repetir a mano para minSdk 24. */
    public static String repetir(String s, int veces) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < veces; i++) sb.append(s);
        return sb.toString();
    }

    public static String dinero(String valor) {
        try {
            double d = Double.parseDouble(valor);
            return String.format(java.util.Locale.US, "%,.2f", d);
        } catch (Exception e) {
            return valor;
        }
    }

    public static View separador(Activity a) {
        View v = new View(a);
        v.setBackgroundColor(0xFFCCCCCC);
        v.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(a, 1)));
        return v;
    }
}
