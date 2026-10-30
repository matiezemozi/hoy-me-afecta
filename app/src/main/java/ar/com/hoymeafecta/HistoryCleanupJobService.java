package ar.com.hoymeafecta;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** Periodic, offline archive maintenance; Android decides the exact run time. */
public class HistoryCleanupJobService extends JobService {
    private volatile boolean stopped;

    @Override public boolean onStartJob(JobParameters params) {
        stopped = false;
        new Thread(() -> {
            try {
                if (!stopped) HistoryCleanup.runIfDue(getApplicationContext());
            } catch (RuntimeException ignored) {
                // Database might be unavailable; next run will retry.
            } finally {
                if (!stopped) jobFinished(params, false);
            }
        }, "HMA-history-cleanup").start();
        return true;
    }

    @Override public boolean onStopJob(JobParameters params) {
        stopped = true;
        return true;
    }
}
