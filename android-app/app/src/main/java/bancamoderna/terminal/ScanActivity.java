package bancamoderna.terminal;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.hardware.Camera;
import android.os.Bundle;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.TextView;

import com.google.zxing.BinaryBitmap;
import com.google.zxing.ChecksumException;
import com.google.zxing.FormatException;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.NotFoundException;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.ReaderException;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Lector de QR por cámara con ZXing (núcleo): abre la cámara trasera,
 * decodifica cada fotograma hasta encontrar un código y devuelve su
 * texto. Prueba el fotograma tal cual y rotado 90° (las Sunmi en
 * vertical entregan el sensor girado). Sin servicios de Google.
 */
@SuppressWarnings("deprecation")
public class ScanActivity extends Activity implements SurfaceHolder.Callback {
    private static final int REQ_CAMARA = 7;

    private Camera camara;
    private SurfaceView superficie;
    private MultiFormatReader lector;
    private final AtomicBoolean decodificando = new AtomicBoolean(false);
    private volatile boolean terminado = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Lectura de ticket");

        FrameLayout raiz = new FrameLayout(this);
        superficie = new SurfaceView(this);
        superficie.getHolder().addCallback(this);
        raiz.addView(superficie);

        TextView guia = new TextView(this);
        guia.setText("Apunte la cámara al QR del ticket");
        guia.setTextColor(0xFFFFFFFF);
        guia.setTextSize(16);
        guia.setPadding(24, 24, 24, 24);
        raiz.addView(guia);

        Button cancelar = new Button(this);
        cancelar.setText("CANCELAR");
        cancelar.setOnClickListener(v -> finish());
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT);
        lp.gravity = android.view.Gravity.BOTTOM;
        cancelar.setLayoutParams(lp);
        raiz.addView(cancelar);

        setContentView(raiz);

        lector = new MultiFormatReader();
        java.util.Map<com.google.zxing.DecodeHintType, Object> hints =
                new java.util.EnumMap<>(com.google.zxing.DecodeHintType.class);
        hints.put(com.google.zxing.DecodeHintType.POSSIBLE_FORMATS,
                java.util.Collections.singletonList(
                        com.google.zxing.BarcodeFormat.QR_CODE));
        lector.setHints(hints);

        if (checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMARA);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                           int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_CAMARA) {
            if (grantResults.length == 0
                    || grantResults[0] != PackageManager.PERMISSION_GRANTED) {
                Ui.toast(this, "Sin permiso de cámara no se puede escanear.");
                finish();
            } else {
                abrirCamara(superficie.getHolder());
            }
        }
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        abrirCamara(holder);
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) {
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        cerrarCamara();
    }

    private void abrirCamara(SurfaceHolder holder) {
        if (checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            return; // se reintenta al conceder el permiso (surface sigue viva)
        }
        try {
            camara = Camera.open();
            Camera.Parameters p = camara.getParameters();
            // Tamaño de previsualización razonable para decodificar QR
            Camera.Size mejor = null;
            for (Camera.Size s : p.getSupportedPreviewSizes()) {
                if (s.width < 640 || s.width > 1920) continue;
                if (mejor == null
                        || s.width * s.height > mejor.width * mejor.height) {
                    mejor = s;
                }
            }
            if (mejor != null) p.setPreviewSize(mejor.width, mejor.height);
            if (p.getSupportedFocusModes().contains(
                    Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE)) {
                p.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
            }
            camara.setParameters(p);
            camara.setDisplayOrientation(90);
            camara.setPreviewDisplay(holder);
            camara.setPreviewCallback((data, cam) -> procesar(data, cam));
            camara.startPreview();
        } catch (Exception e) {
            Ui.toast(this, "No se pudo abrir la cámara: " + e.getMessage());
            finish();
        }
    }

    private void procesar(byte[] data, Camera cam) {
        if (terminado || !decodificando.compareAndSet(false, true)) return;
        try {
            Camera.Size size = cam.getParameters().getPreviewSize();
            Result r = intentar(data, size.width, size.height, false);
            if (r == null) {
                r = intentar(data, size.width, size.height, true);
            }
            if (r != null) {
                terminado = true;
                Intent i = new Intent();
                i.putExtra("texto", r.getText());
                setResult(RESULT_OK, i);
                finish();
                return;
            }
        } catch (Exception ignored) {
        } finally {
            decodificando.set(false);
        }
    }

    private Result intentar(byte[] data, int ancho, int alto, boolean rotar) {
        byte[] plano = data;
        int w = ancho, h = alto;
        if (rotar) {
            plano = rotar90(data, ancho, alto);
            w = alto;
            h = ancho;
        }
        PlanarYUVLuminanceSource fuente = new PlanarYUVLuminanceSource(
                plano, w, h, 0, 0, w, h, false);
        BinaryBitmap bitmap = new BinaryBitmap(new HybridBinarizer(fuente));
        try {
            return lector.decodeWithState(bitmap);
        } catch (ReaderException e) {
            // NotFoundException, ChecksumException y FormatException
            // son subclases de ReaderException: basta con esta.
            return null;
        } finally {
            lector.reset();
        }
    }

    /** Rota 90° el plano Y de un fotograma NV21. */
    private static byte[] rotar90(byte[] data, int ancho, int alto) {
        byte[] salida = new byte[data.length];
        for (int y = 0; y < alto; y++) {
            for (int x = 0; x < ancho; x++) {
                salida[x * alto + (alto - 1 - y)] = data[y * ancho + x];
            }
        }
        // La parte de color (VU) se copia sin rotar: ZXing solo usa el plano Y.
        System.arraycopy(data, ancho * alto, salida, ancho * alto,
                data.length - ancho * alto);
        return salida;
    }

    private void cerrarCamara() {
        if (camara != null) {
            try {
                camara.setPreviewCallback(null);
                camara.stopPreview();
            } catch (Exception ignored) {
            }
            camara.release();
            camara = null;
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        cerrarCamara();
    }
}
