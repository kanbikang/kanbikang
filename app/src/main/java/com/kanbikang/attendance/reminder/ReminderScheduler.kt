package com.kanbikang.attendance.reminder

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import com.kanbikang.attendance.data.ReminderSettings
import com.kanbikang.attendance.data.Times
import java.time.DayOfWeek
import java.time.LocalDateTime
import java.time.LocalTime

/** 출근·퇴근 알림 알람을 AlarmManager에 등록한다. 알람이 울리면 기록 여부를 확인한 뒤 필요할 때만 알림을 띄운다. */
object ReminderScheduler {
    const val ACTION_REMINDER = "com.kanbikang.attendance.REMINDER"
    const val EXTRA_TYPE = "type"
    const val TYPE_CHECK_IN = "check_in"
    const val TYPE_CHECK_OUT = "check_out"

    fun scheduleAll(context: Context) {
        val config = ReminderSettings(context).load()
        schedule(context, TYPE_CHECK_IN, config.checkInEnabled, config.checkInTime, config.weekendsToo)
        schedule(context, TYPE_CHECK_OUT, config.checkOutEnabled, config.checkOutTime, config.weekendsToo)
    }

    fun canScheduleExact(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        return alarmManager.canScheduleExactAlarms()
    }

    private fun schedule(context: Context, type: String, enabled: Boolean, time: LocalTime, weekendsToo: Boolean) {
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        val pendingIntent = pendingIntent(context, type)
        alarmManager.cancel(pendingIntent)
        if (!enabled) return

        val triggerAt = Times.toMillis(nextTrigger(time, weekendsToo, Times.now()))
        if (canScheduleExact(context)) {
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pendingIntent)
        } else {
            // 정확한 알람 권한이 없으면 시스템이 몇 분 늦게 울릴 수 있다.
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pendingIntent)
        }
    }

    /** 오늘 해당 시각이 아직 안 지났으면 오늘, 지났으면 다음 날. 주말 제외 설정이면 평일까지 미룬다. */
    fun nextTrigger(time: LocalTime, weekendsToo: Boolean, now: LocalDateTime): LocalDateTime {
        var date = now.toLocalDate()
        if (!now.toLocalTime().isBefore(time)) date = date.plusDays(1)
        while (!weekendsToo && (date.dayOfWeek == DayOfWeek.SATURDAY || date.dayOfWeek == DayOfWeek.SUNDAY)) {
            date = date.plusDays(1)
        }
        return date.atTime(time)
    }

    private fun pendingIntent(context: Context, type: String): PendingIntent {
        val intent = Intent(context, ReminderReceiver::class.java)
            .setAction(ACTION_REMINDER)
            .putExtra(EXTRA_TYPE, type)
        val requestCode = if (type == TYPE_CHECK_IN) 1 else 2
        return PendingIntent.getBroadcast(
            context,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }
}
