package com.kanbikang.attendance.data

import android.content.Context
import java.time.LocalTime

/** 알림 설정값. 시각까지 버튼을 누르지 않았을 때만 알림을 보낸다. */
data class ReminderConfig(
    val checkInEnabled: Boolean = true,
    val checkInTime: LocalTime = LocalTime.of(9, 0),
    val checkOutEnabled: Boolean = true,
    val checkOutTime: LocalTime = LocalTime.of(18, 0),
    val weekendsToo: Boolean = false,
)

class ReminderSettings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("reminders", Context.MODE_PRIVATE)

    fun load(): ReminderConfig = ReminderConfig(
        checkInEnabled = prefs.getBoolean(KEY_IN_ENABLED, true),
        checkInTime = minutesToTime(prefs.getInt(KEY_IN_TIME, 9 * 60)),
        checkOutEnabled = prefs.getBoolean(KEY_OUT_ENABLED, true),
        checkOutTime = minutesToTime(prefs.getInt(KEY_OUT_TIME, 18 * 60)),
        weekendsToo = prefs.getBoolean(KEY_WEEKENDS, false),
    )

    fun save(config: ReminderConfig) {
        prefs.edit()
            .putBoolean(KEY_IN_ENABLED, config.checkInEnabled)
            .putInt(KEY_IN_TIME, config.checkInTime.toSecondOfDay() / 60)
            .putBoolean(KEY_OUT_ENABLED, config.checkOutEnabled)
            .putInt(KEY_OUT_TIME, config.checkOutTime.toSecondOfDay() / 60)
            .putBoolean(KEY_WEEKENDS, config.weekendsToo)
            .apply()
    }

    private fun minutesToTime(minutes: Int): LocalTime = LocalTime.of(minutes / 60, minutes % 60)

    private companion object {
        const val KEY_IN_ENABLED = "check_in_enabled"
        const val KEY_IN_TIME = "check_in_time"
        const val KEY_OUT_ENABLED = "check_out_enabled"
        const val KEY_OUT_TIME = "check_out_time"
        const val KEY_WEEKENDS = "weekends_too"
    }
}
