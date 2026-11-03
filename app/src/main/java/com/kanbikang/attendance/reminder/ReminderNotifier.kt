package com.kanbikang.attendance.reminder

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.kanbikang.attendance.R
import com.kanbikang.attendance.data.AttendanceRepository
import com.kanbikang.attendance.data.Times
import com.kanbikang.attendance.ui.MainActivity

object ReminderNotifier {
    const val CHANNEL_ID = "reminders"
    const val NOTIFICATION_ID_CHECK_IN = 100
    const val NOTIFICATION_ID_CHECK_OUT = 101

    /** 해당 기록이 아직 없을 때만 알림을 띄운다. */
    suspend fun notifyIfMissing(context: Context, type: String) {
        val now = Times.now()
        val today = now.toLocalDate().toString()
        val active = AttendanceRepository.get(context).activeRecord(now)

        val missing = when (type) {
            ReminderScheduler.TYPE_CHECK_IN -> active.date != today || active.checkIn == null
            ReminderScheduler.TYPE_CHECK_OUT -> active.checkIn != null && active.checkOut == null
            else -> false
        }
        if (!missing) return
        if (!notificationsAllowed(context)) return

        ensureChannel(context)
        val isCheckIn = type == ReminderScheduler.TYPE_CHECK_IN
        val label = if (isCheckIn) "출근" else "퇴근"
        val notificationId = if (isCheckIn) NOTIFICATION_ID_CHECK_IN else NOTIFICATION_ID_CHECK_OUT

        val openApp = PendingIntent.getActivity(
            context,
            notificationId,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val recordNow = PendingIntent.getBroadcast(
            context,
            notificationId + 10,
            Intent(context, ReminderActionReceiver::class.java)
                .setAction(if (isCheckIn) ReminderActionReceiver.ACTION_CHECK_IN else ReminderActionReceiver.ACTION_CHECK_OUT),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("$label 기록을 아직 안 눌렀습니다")
            .setContentText("지금 ${Times.hhmm(Times.toMillis(now))}입니다. 아래 버튼으로 바로 기록할 수 있습니다.")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setContentIntent(openApp)
            .setAutoCancel(true)
            .addAction(0, "지금 $label 기록", recordNow)
            .build()

        NotificationManagerCompat.from(context).notify(notificationId, notification)
    }

    fun cancel(context: Context, notificationId: Int) {
        NotificationManagerCompat.from(context).cancel(notificationId)
    }

    fun notificationsAllowed(context: Context): Boolean {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            return ContextCompat.checkSelfPermission(context, android.Manifest.permission.POST_NOTIFICATIONS) ==
                android.content.pm.PackageManager.PERMISSION_GRANTED
        }
        return true
    }

    private fun ensureChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(CHANNEL_ID, "출퇴근 알림", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "정한 시각까지 출근·퇴근 버튼을 누르지 않았을 때 알려줍니다."
        }
        manager.createNotificationChannel(channel)
    }
}
