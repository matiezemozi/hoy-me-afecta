package ar.com.hoymeafecta;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Private, device-only archive of notifications issued by this installation.
 * The archive can be cleared manually or by an expressly selected schedule.
 * The default is never to clear automatically.
 * Display pagination does NOT remove or limit retained records.
 */
public final class NotificationHistory extends SQLiteOpenHelper {
    private static final String DB_NAME = "hoy_me_afecta_avisos.db";
    private static final int DB_VERSION = 1;
    private static final String TABLE = "avisos";
    private final Context appContext;

    public static final class Record {
        public final long id;
        public final long receivedAt;
        public final String type, company, title, partido, locality, description, firstSeenAt, sourceUrl;
        Record(Cursor c) {
            id = c.getLong(0);
            receivedAt = c.getLong(1);
            type = c.getString(2);
            company = c.getString(3);
            title = c.getString(4);
            partido = c.getString(5);
            locality = c.getString(6);
            description = c.getString(7);
            firstSeenAt = c.getString(8);
            sourceUrl = c.getString(9);
        }
    }

    public NotificationHistory(Context context) {
        super(context.getApplicationContext(), DB_NAME, null, DB_VERSION);
        appContext = context.getApplicationContext();
    }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE " + TABLE + " (" +
                "_id INTEGER PRIMARY KEY AUTOINCREMENT," +
                "event_id TEXT UNIQUE," +
                "received_at INTEGER NOT NULL," +
                "type TEXT NOT NULL," +
                "company TEXT NOT NULL DEFAULT ''," +
                "title TEXT NOT NULL DEFAULT ''," +
                "partido TEXT NOT NULL DEFAULT ''," +
                "locality TEXT NOT NULL DEFAULT ''," +
                "description TEXT NOT NULL DEFAULT ''," +
                "first_seen_at TEXT NOT NULL DEFAULT ''," +
                "source_url TEXT NOT NULL DEFAULT '')");
        db.execSQL("CREATE INDEX avisos_received_idx ON " + TABLE + "(received_at DESC, _id DESC)");
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // No destructive migration. Future changes must preserve the archive.
        if (oldVersion != newVersion) {
            throw new IllegalStateException("Migracion pendiente del historial local");
        }
    }

    /** Save each real publication delivered in a notification; unique event IDs prevent duplicates. */
    public void recordPublications(List<JSONObject> events) {
        // Apply an overdue user-selected cleanup BEFORE saving this new notice.
        try { HistoryCleanup.runIfDue(appContext); }
        catch (RuntimeException ignored) { /* A failed cleanup must not block alerts. */ }
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            long received = System.currentTimeMillis();
            for (JSONObject event : events) {
                String eventId = event.optString("event_id", "");
                if (!eventId.matches("[a-f0-9]{24}")) continue;
                ContentValues values = new ContentValues();
                values.put("event_id", eventId);
                values.put("received_at", received);
                values.put("type", "AVISO DEL ENRE");
                values.put("company", event.optString("company", ""));
                values.put("title", event.optString("title", "Aviso eléctrico"));
                values.put("partido", event.optString("partido", ""));
                values.put("locality", event.optString("localidad", ""));
                values.put("description", "Registro aparecido en una publicación del ENRE. " +
                        "No confirma cuándo comenzó el corte ni si continúa vigente.");
                values.put("first_seen_at", event.optString("first_seen_at", ""));
                values.put("source_url", event.optString("source_url", ""));
                db.insertWithOnConflict(TABLE, null, values, SQLiteDatabase.CONFLICT_IGNORE);
            }
            db.setTransactionSuccessful();
        } finally {
            db.endTransaction();
        }
    }

    /** Tests deliberately have no event ID, so each requested test remains distinguishable. */
    public void recordTest(String type, String title, String message, String locality) {
        try { HistoryCleanup.runIfDue(appContext); }
        catch (RuntimeException ignored) { /* A failed cleanup must not block tests. */ }
        if (!"PRUEBA LOCAL".equals(type) && !"SIMULACION".equals(type))
            throw new IllegalArgumentException("Tipo de prueba no reconocido");
        ContentValues values = new ContentValues();
        values.putNull("event_id");
        values.put("received_at", System.currentTimeMillis());
        values.put("type", type);
        values.put("company", "HOY ME AFECTA");
        values.put("title", title);
        values.put("partido", "");
        values.put("locality", locality == null ? "" : locality);
        values.put("description", message + " No representa un corte real.");
        values.put("first_seen_at", "");
        values.put("source_url", "");
        getWritableDatabase().insertOrThrow(TABLE, null, values);
    }

    public long count() {
        try (Cursor cursor = getReadableDatabase().rawQuery(
                "SELECT COUNT(*) FROM " + TABLE, null)) {
            return cursor.moveToFirst() ? cursor.getLong(0) : 0;
        }
    }

    /** A display page, not a retention limit. No records are deleted by this method. */
    public List<Record> newest(int offset, int pageSize) {
        if (offset < 0 || pageSize <= 0 || pageSize > 100) {
            throw new IllegalArgumentException("Paginacion invalida");
        }
        List<Record> result = new ArrayList<>();
        String sql = "SELECT _id, received_at, type, company, title, partido, " +
                "locality, description, first_seen_at, source_url FROM " + TABLE +
                " ORDER BY received_at DESC, _id DESC LIMIT ? OFFSET ?";
        try (Cursor cursor = getReadableDatabase().rawQuery(sql,
                new String[]{String.valueOf(pageSize), String.valueOf(offset)})) {
            while (cursor.moveToNext()) result.add(new Record(cursor));
        }
        return result;
    }

    /** Retrieve a single saved notice by its local ID; existing database is unchanged. */
    public Record byId(long id) {
        if (id <= 0) return null;
        String sql = "SELECT _id, received_at, type, company, title, partido, " +
                "locality, description, first_seen_at, source_url FROM " + TABLE +
                " WHERE _id = ? LIMIT 1";
        try (Cursor cursor = getReadableDatabase().rawQuery(sql,
                new String[]{String.valueOf(id)})) {
            return cursor.moveToFirst() ? new Record(cursor) : null;
        }
    }

    /** Only manual user action or explicitly selected scheduled cleanup. */
    public void clearAll() {
        SQLiteDatabase db = getWritableDatabase();
        db.delete(TABLE, null, null);
        // Reclaim disk space too; no background pruning occurs anywhere.
        try { db.execSQL("VACUUM"); }
        catch (RuntimeException ignored) { /* Rows are cleared even if compaction is blocked. */ }
    }
}
