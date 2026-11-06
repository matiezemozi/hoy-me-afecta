package ar.com.hoymeafecta;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Conservative validity check for published planned-work windows.
 *  The window is an announcement, NOT evidence of a current interruption.
 *  Pure Java so it can be tested without an Android SDK.
 */
final class ScheduledWorkWindow {
    private ScheduledWorkWindow() { }

    static boolean isPublishedWindowRelevant(String start, String end, long nowMillis) {
        if (start == null || end == null) return false;
        // Require a complete date and explicit Argentina offset; no guessed timezones.
        if (!start.matches("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}-03:00") ||
                !end.matches("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}-03:00")) return false;
        try {
            SimpleDateFormat date = new SimpleDateFormat("yyyy-MM-dd'T'HH:mmXXX", Locale.US);
            date.setLenient(false);
            Date a = date.parse(start);
            Date b = date.parse(end);
            if (a == null || b == null) return false;
            long from = a.getTime(), until = b.getTime();
            long horizon = 14L * 24L * 60L * 60L * 1000L;
            // Include a published interval that has begun but not yet ended.
            // This NEVER says the electricity interruption actually started.
            return from < until && until > nowMillis && from <= nowMillis + horizon &&
                    until <= from + horizon;
        } catch (Exception ignored) {
            return false;
        }
    }
}
