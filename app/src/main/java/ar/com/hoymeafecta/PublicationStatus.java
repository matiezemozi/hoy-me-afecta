package ar.com.hoymeafecta;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.Normalizer;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * Conservative, read-only comparison of a saved ENRE notice with the newest
 * available publication. Equal descriptions do NOT establish incident identity.
 * Missing data or stale sources never imply electricity has been restored.
 */
public final class PublicationStatus {
    public static final String UNKNOWN = "unknown";
    public static final String MATCH_FOUND = "similar_listing_found";
    public static final String NOT_LISTED = "similar_listing_not_found";
    private static final long MAX_AGE_MS = 3L * 60 * 60 * 1000;

    private PublicationStatus() { }

    public static final class Result {
        public final String status;
        public final String explanation;
        public final String generatedAt;
        public final String sourceCheckedAt;

        Result(String status, String explanation, String generatedAt, String sourceCheckedAt) {
            this.status = status;
            this.explanation = explanation;
            this.generatedAt = generatedAt;
            this.sourceCheckedAt = sourceCheckedAt;
        }
    }

    private static String normalized(String input) {
        return Normalizer.normalize(input == null ? "" : input, Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "").trim().toLowerCase(Locale.ROOT);
    }

    private static long utc(String value) {
        if (value == null || value.isEmpty()) return -1;
        try {
            SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
            fmt.setTimeZone(TimeZone.getTimeZone("UTC"));
            fmt.setLenient(false);
            Date date = fmt.parse(value);
            return date == null ? -1 : date.getTime();
        } catch (Exception ignored) { return -1; }
    }

    private static boolean recent(String when, long now) {
        long timestamp = utc(when);
        long age = now - timestamp;
        return timestamp > 0 && age >= -60_000L && age < MAX_AGE_MS;
    }

    public static Result assess(JSONObject feed, String company, String partido,
            String locality, String title, long nowMs) {
        if (feed == null || feed.optInt("schema_version") != 1)
            return unknown("No hay un informe verificable para este aviso.", "", "");
        String generated = feed.optString("generated_at", "");
        if (!recent(generated, nowMs))
            return unknown("El último informe no es reciente. No se puede confirmar el estado de este aviso.",
                    generated, "");
        String provider = normalized(company);
        if (!"edenor".equals(provider) && !"edesur".equals(provider))
            return unknown("Este origen todavía no admite comprobación automática.", generated, "");
        JSONObject sources = feed.optJSONObject("sources");
        JSONObject source = sources == null ? null : sources.optJSONObject(provider);
        String checked = source == null ? "" : source.optString("checked_at", "");
        if (source == null || !"ok".equals(source.optString("status", "")) ||
                !recent(checked, nowMs))
            return unknown("La fuente correspondiente no tiene una consulta reciente y correcta.",
                    generated, checked);
        JSONArray alerts = feed.optJSONArray("alerts");
        if (alerts == null)
            return unknown("El informe no incluye una lista comprobable de cortes.", generated, checked);
        for (int i = 0; i < alerts.length(); i++) {
            JSONObject a = alerts.optJSONObject(i);
            if (a == null) continue;
            if ("electricidad".equals(a.optString("category", "")) &&
                    provider.equals(normalized(a.optString("company", ""))) &&
                    normalized(partido).equals(normalized(a.optString("partido", ""))) &&
                    normalized(locality).equals(normalized(a.optString("localidad", ""))) &&
                    normalized(title).equals(normalized(a.optString("title", "")))) {
                return new Result(MATCH_FOUND,
                        "Hay un aviso del mismo tipo, empresa y zona en la última publicación. " +
                        "Podría ser otro incidente similar; no demuestra que el corte original continúe.",
                        generated, checked);
            }
        }
        return new Result(NOT_LISTED,
                "No figura un aviso equivalente en la última publicación consultada. " +
                "Esto NO confirma que se haya restablecido la electricidad.",
                generated, checked);
    }

    private static Result unknown(String message, String generated, String checked) {
        return new Result(UNKNOWN, message, generated, checked);
    }
}
