package ar.com.hoymeafecta;

import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.Normalizer;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

public class MainActivity extends Activity {
    private static final int INK = Color.rgb(29, 43, 62);
    private static final int BLUE = Color.rgb(27, 92, 160);
    private static final int LIGHT = Color.rgb(245, 247, 251);
    private static final int GREY = Color.rgb(93, 107, 125);
    private LinearLayout root;
    private EditText repoField, placeField, branchField;
    private SharedPreferences prefs;
    private JSONObject feed;
    private String connection = "Sin datos descargados todavía";
    private boolean refreshing = false;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("hoy_me_afecta", MODE_PRIVATE);
        draw();
        if (!prefs.getString("repo", "").trim().isEmpty()) refresh();
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private GradientDrawable background(int color, int radius) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radius));
        return shape;
    }

    private TextView text(String label, int size, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(label); t.setTextSize(size); t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        t.setPadding(0, dp(3), 0, dp(3));
        return t;
    }

    private LinearLayout card() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(16), dp(13), dp(16), dp(13));
        c.setBackground(background(Color.WHITE, 14));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, 0, 0, dp(12));
        root.addView(c, lp);
        return c;
    }

    private Button button(String label, Runnable action) {
        Button b = new Button(this);
        b.setText(label); b.setAllCaps(false); b.setTextColor(Color.WHITE);
        b.setBackground(background(BLUE, 10));
        b.setPadding(dp(12), dp(6), dp(12), dp(6));
        b.setOnClickListener(v -> action.run());
        return b;
    }

    private EditText edit(String label, String value) {
        EditText e = new EditText(this);
        e.setSingleLine(true); e.setTextSize(15); e.setTextColor(INK);
        e.setHint(label); e.setText(value);
        return e;
    }

    private void title(String label) {
        TextView heading = text(label, 19, INK, true);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(15), 0, dp(9));
        root.addView(heading, lp);
    }

    private void draw() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true); scroll.setBackgroundColor(LIGHT);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(20), dp(20), dp(28));
        scroll.addView(root);
        setContentView(scroll);

        root.addView(text("HOY ME AFECTA", 26, INK, true));
        root.addView(text("Lo que te conviene saber antes de salir", 14, GREY, false));
        LinearLayout status = card();
        status.addView(text(connection, 14, BLUE, false));
        if (refreshing) status.addView(text("Consultando las fuentes…", 13, GREY, false));

        title("Tus preferencias");
        LinearLayout setup = card();
        setup.addView(text("Partido o localidad que te interesa", 13, GREY, true));
        placeField = edit("Ejemplo: Luján", prefs.getString("place", ""));
        setup.addView(placeField);
        setup.addView(text("Línea favorita: 57 · ramal (opcional)", 13, GREY, true));
        branchField = edit("Ejemplo: Q", prefs.getString("branch", ""));
        setup.addView(branchField);
        setup.addView(text("Repositorio público de GitHub", 13, GREY, true));
        repoField = edit("usuario/repositorio", prefs.getString("repo", ""));
        setup.addView(repoField);
        setup.addView(text("El repositorio permite leer el informe generado por GitHub Actions. No se necesita GPS.", 12, GREY, false));
        setup.addView(button("Guardar y actualizar", () -> {
            String repo = repoField.getText().toString().trim();
            prefs.edit().putString("repo", repo)
                    .putString("place", placeField.getText().toString().trim())
                    .putString("branch", branchField.getText().toString().trim()).apply();
            if (repo.matches("[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+")) refresh();
            else { connection = "Ingresá un repositorio válido (usuario/repositorio)."; draw(); }
        }));

        title("Electricidad · ENRE");
        electricity();
        title("Colectivos · Línea 57");
        buses();
        title("Información y fuentes");
        LinearLayout notes = card();
        notes.addView(text("Los avisos de cortes corresponden a zonas reportadas por la distribuidora, no garantizan el estado de cada domicilio.", 13, GREY, false));
        notes.addView(text("Si una fuente falla o está desactualizada, la aplicación no interpreta que todo funciona normalmente.", 13, GREY, false));
        notes.addView(button("Consultar ENRE", () -> open("https://www.enre.gov.ar/paginacorte/tabla_cortes_edenor.html")));
    }

    private static String norm(String raw) {
        return Normalizer.normalize(raw == null ? "" : raw, Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "").trim().toLowerCase(Locale.ROOT);
    }

    private boolean isFresh() {
        if (feed == null) return false;
        String iso = feed.optString("generated_at", "");
        try {
            SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
            fmt.setTimeZone(TimeZone.getTimeZone("UTC"));
            Date date = fmt.parse(iso);
            if (date == null) return false;
            long age = System.currentTimeMillis() - date.getTime();
            return age >= -60000 && age < 3L * 60 * 60 * 1000;
        } catch (Exception ignored) { return false; }
    }

    private void electricity() {
        LinearLayout c = card();
        if (feed == null || !isFresh()) {
            c.addView(text("Sin información reciente verificada. No es posible afirmar que no haya cortes.", 14, GREY, false));
            return;
        }
        JSONObject sources = feed.optJSONObject("sources");
        if (sources == null) { c.addView(text("Formato de fuentes no disponible.", 14, GREY, false)); return; }
        for (String company : new String[]{"edenor", "edesur"}) {
            JSONObject source = sources.optJSONObject(company);
            String state = source == null ? "desconocido" : source.optString("status", "desconocido");
            c.addView(text(company.toUpperCase(Locale.ROOT) + ": " +
                    ("ok".equals(state) ? "fuente consultada" : "datos no verificados"), 13,
                    "ok".equals(state) ? BLUE : GREY, false));
        }
        String area = prefs.getString("place", "").trim();
        if (area.isEmpty()) {
            c.addView(text("Elegí tu partido o localidad para filtrar los avisos.", 14, GREY, false));
            return;
        }
        JSONArray alerts = feed.optJSONArray("alerts");
        int shown = 0;
        if (alerts != null) for (int i = 0; i < alerts.length(); i++) {
            JSONObject a = alerts.optJSONObject(i);
            if (a == null || !"electricidad".equals(a.optString("category"))) continue;
            String partido = a.optString("partido", ""), localidad = a.optString("localidad", "");
            String search = norm(area);
            if (!norm(partido).contains(search) && !norm(localidad).contains(search)) continue;
            JSONObject src = sources.optJSONObject(a.optString("company", "").toLowerCase(Locale.ROOT));
            if (src == null || !"ok".equals(src.optString("status"))) continue;
            String place = partido + (localidad.isEmpty() ? "" : " · " + localidad);
            c.addView(text("• " + a.optString("title", "Interrupción informada"), 15, INK, true));
            c.addView(text(place, 13, GREY, false));
            String restoration = a.optString("expected_restoration", "");
            if (!restoration.isEmpty() && !"null".equals(restoration))
                c.addView(text("Reposición estimada: " + restoration, 13, GREY, false));
            shown++;
            if (shown == 15) break;
        }
        if (shown == 0)
            c.addView(text("No se encontraron cortes publicados para «" + area + "» en las fuentes disponibles. Esto NO garantiza suministro normal.", 13, GREY, false));
    }

    private void buses() {
        LinearLayout c = card();
        String branch = prefs.getString("branch", "").trim();
        c.addView(text("Línea 57" + (branch.isEmpty() ? "" : " · Ramal " + branch), 18, INK, true));
        c.addView(text("Estado general: sin datos automáticos verificados.", 14, GREY, false));
        if (feed != null && isFresh()) {
            JSONArray alerts = feed.optJSONArray("alerts");
            int found = 0;
            if (alerts != null) for (int i = 0; i < alerts.length(); i++) {
                JSONObject a = alerts.optJSONObject(i);
                if (a == null || !"colectivo".equals(a.optString("category")) ||
                        !"57".equals(a.optString("line"))) continue;
                String eventBranch = a.optString("branch", "").trim();
                if (!branch.isEmpty() && !eventBranch.isEmpty() && !norm(branch).equals(norm(eventBranch))) continue;
                c.addView(text("Aviso publicado: " + a.optString("title"), 14, INK, true));
                c.addView(text(a.optString("description"), 13, GREY, false));
                c.addView(text("Verificado manualmente: " + a.optString("observed_at"), 12, GREY, false));
                String link = a.optString("source_url", "");
                if (link.startsWith("https://")) c.addView(button("Abrir fuente del aviso", () -> open(link)));
                found++;
            }
            if (found == 0) c.addView(text("Sin avisos manuales vigentes registrados. No equivale a servicio normal.", 13, GREY, false));
        } else {
            c.addView(text("Todavía no se pudo consultar el informe publicado.", 13, GREY, false));
        }
        c.addView(button("Consultar Cuándo SUBO", () -> open("https://www.argentina.gob.ar/sube/cuandosubo")));
    }

    private void open(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
        catch (Exception ignored) { connection = "No se pudo abrir el enlace."; draw(); }
    }

    private void refresh() {
        String repo = prefs.getString("repo", "").trim();
        if (!repo.matches("[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+")) {
            connection = "Configurá un repositorio público para leer el informe.";
            draw(); return;
        }
        if (refreshing) return;
        refreshing = true;
        draw();
        final String url = "https://raw.githubusercontent.com/" + repo +
                "/main/docs/feed.json?refresh=" + System.currentTimeMillis();
        new Thread(() -> {
            HttpURLConnection connectionHandle = null;
            try {
                connectionHandle = (HttpURLConnection) new URL(url).openConnection();
                connectionHandle.setConnectTimeout(12000);
                connectionHandle.setReadTimeout(12000);
                connectionHandle.setRequestProperty("Accept", "application/json");
                if (connectionHandle.getResponseCode() != 200) throw new Exception("HTTP " + connectionHandle.getResponseCode());
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                try (InputStream stream = connectionHandle.getInputStream()) {
                    byte[] buffer = new byte[4096];
                    int n;
                    while ((n = stream.read(buffer)) != -1) {
                        if (bytes.size() + n > 2_000_000) throw new Exception("Respuesta demasiado grande");
                        bytes.write(buffer, 0, n);
                    }
                }
                JSONObject result = new JSONObject(bytes.toString("UTF-8"));
                if (result.optInt("schema_version") != 1) throw new Exception("Formato desconocido");
                runOnUiThread(() -> {
                    feed = result;
                    refreshing = false;
                    connection = isFresh() ? "Informe consultado. Revisá el estado de cada fuente." :
                            "Informe no actualizado recientemente; no se mostrarán avisos como vigentes.";
                    draw();
                });
            } catch (Exception ex) {
                String message = ex.getMessage();
                runOnUiThread(() -> {
                    refreshing = false;
                    feed = null;
                    connection = "No se pudo obtener información actual: " + (message == null ? "error de conexión" : message);
                    draw();
                });
            } finally {
                if (connectionHandle != null) connectionHandle.disconnect();
            }
        }).start();
    }
}
