package bancamoderna.terminal;

import android.content.Context;
import android.os.RemoteException;

import com.sunmi.peripheral.printer.InnerPrinterCallback;
import com.sunmi.peripheral.printer.InnerPrinterException;
import com.sunmi.peripheral.printer.InnerPrinterManager;
import com.sunmi.peripheral.printer.InnerResultCallback;
import com.sunmi.peripheral.printer.SunmiPrinterService;

/**
 * Impresión en la impresora interna Sunmi mediante la librería OFICIAL
 * de Sunmi (com.sunmi:printerlibrary), que enlaza con el servicio de
 * impresión del equipo (woyou). En un equipo que NO es Sunmi (o sin el
 * servicio de impresión), el enlace falla y la app lo dice con claridad:
 * la venta ya quedó registrada en el servidor y el ticket se puede
 * reimprimir desde una Sunmi real. Nunca se finge una impresión.
 */
public class SunmiPrinter {

    public interface Resultado {
        void ok();

        void error(String mensaje);
    }

    private SunmiPrinterService servicio;
    private boolean enlazando = false;

    private final InnerPrinterCallback callbackEnlace = new InnerPrinterCallback() {
        @Override
        protected void onConnected(SunmiPrinterService service) {
            servicio = service;
            enlazando = false;
        }

        @Override
        protected void onDisconnected() {
            servicio = null;
            enlazando = false;
        }
    };

    /** Intenta enlazar con el servicio de impresión del equipo. */
    public void enlazar(Context ctx) {
        if (servicio != null || enlazando) return;
        try {
            enlazando = true;
            boolean ok = InnerPrinterManager.getInstance()
                    .bindService(ctx.getApplicationContext(), callbackEnlace);
            if (!ok) {
                enlazando = false;
            }
        } catch (InnerPrinterException e) {
            enlazando = false;
        }
    }

    public boolean disponible() {
        return servicio != null;
    }

    /**
     * Imprime el texto del ticket y, si se pasa contenido QR, el código
     * QR grande al final (la llave pública LOT:{id}:{serial}).
     */
    public void imprimir(String textoTicket, String contenidoQr, Resultado resultado) {
        if (servicio == null) {
            resultado.error("El servicio de impresión Sunmi no está disponible "
                    + "en este equipo. La venta SÍ quedó registrada en el "
                    + "servidor; reimprima el ticket desde una terminal Sunmi.");
            return;
        }
        InnerResultCallback cb = new InnerResultCallback() {
            @Override
            public void onRunResult(boolean isSuccess) {
                // Los resultados por comando llegan aquí; el cierre del
                // buffer (onPrintResult) confirma la impresión completa.
            }

            @Override
            public void onReturnString(String result) {
            }

            @Override
            public void onRaiseException(int code, String msg) {
                resultado.error("La impresora reportó un error (" + code + "): " + msg);
            }

            @Override
            public void onPrintResult(int code, String msg) {
                if (code == 0) {
                    resultado.ok();
                } else {
                    resultado.error("La impresión terminó con error (" + code + "): " + msg);
                }
            }
        };
        try {
            servicio.enterPrinterBuffer(true);
            servicio.printerInit(cb);
            servicio.printText(textoTicket, cb);
            if (contenidoQr != null && !contenidoQr.isEmpty()) {
                // QR centrado: tamaño de módulo 8, nivel de corrección 1 (M)
                servicio.setAlignment(1, cb);
                servicio.printQRCode(contenidoQr, 8, 1, cb);
                servicio.setAlignment(0, cb);
            }
            servicio.lineWrap(3, cb);
            servicio.exitPrinterBufferWithCallback(true, cb);
        } catch (RemoteException e) {
            resultado.error("Fallo al enviar a la impresora: " + e.getMessage());
        }
    }

    public void desenlazar(Context ctx) {
        try {
            InnerPrinterManager.getInstance()
                    .unBindService(ctx.getApplicationContext(), callbackEnlace);
        } catch (Exception ignored) {
        }
        servicio = null;
    }
}
