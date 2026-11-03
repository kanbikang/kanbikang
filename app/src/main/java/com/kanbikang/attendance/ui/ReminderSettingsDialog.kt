@file:OptIn(ExperimentalMaterial3Api::class)

package com.kanbikang.attendance.ui

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import com.kanbikang.attendance.data.ReminderConfig
import com.kanbikang.attendance.data.ReminderSettings
import com.kanbikang.attendance.data.Times
import com.kanbikang.attendance.reminder.ReminderNotifier
import com.kanbikang.attendance.reminder.ReminderScheduler

private enum class ReminderPicker { CHECK_IN, CHECK_OUT }

@Composable
fun ReminderSettingsDialog(onDismiss: () -> Unit) {
    val context = LocalContext.current
    val settings = remember { ReminderSettings(context) }
    var config by remember { mutableStateOf(settings.load()) }
    var picker by remember { mutableStateOf<ReminderPicker?>(null) }
    var notificationsAllowed by remember { mutableStateOf(ReminderNotifier.notificationsAllowed(context)) }
    var exactAllowed by remember { mutableStateOf(ReminderScheduler.canScheduleExact(context)) }

    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        notificationsAllowed = ReminderNotifier.notificationsAllowed(context)
    }

    // 시스템 설정 화면에서 돌아왔을 때 권한 상태를 다시 읽는다.
    LifecycleResumeEffect(Unit) {
        notificationsAllowed = ReminderNotifier.notificationsAllowed(context)
        exactAllowed = ReminderScheduler.canScheduleExact(context)
        onPauseOrDispose { }
    }

    fun update(newConfig: ReminderConfig) {
        config = newConfig
        settings.save(newConfig)
        ReminderScheduler.scheduleAll(context)
    }

    fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        } else {
            context.startActivity(
                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName),
            )
        }
    }

    fun requestExactAlarmPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            context.startActivity(
                Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${context.packageName}")),
            )
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("알림 설정") },
        text = {
            Column {
                ToggleRow("출근 알림", config.checkInEnabled) { update(config.copy(checkInEnabled = it)) }
                if (config.checkInEnabled) {
                    FieldRow("출근 알림 시각", Times.hhmm(config.checkInTime)) { picker = ReminderPicker.CHECK_IN }
                }
                HorizontalDivider()
                ToggleRow("퇴근 알림", config.checkOutEnabled) { update(config.copy(checkOutEnabled = it)) }
                if (config.checkOutEnabled) {
                    FieldRow("퇴근 알림 시각", Times.hhmm(config.checkOutTime)) { picker = ReminderPicker.CHECK_OUT }
                }
                HorizontalDivider()
                ToggleRow("주말에도 알림", config.weekendsToo) { update(config.copy(weekendsToo = it)) }
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "정한 시각까지 버튼을 누르지 않았을 때만 알림이 옵니다. 퇴근 알림은 그날 출근 기록이 있을 때만 옵니다.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (!notificationsAllowed) {
                    PermissionRow("알림 권한이 꺼져 있어 알림이 오지 않습니다.", ::requestNotificationPermission)
                }
                if (!exactAllowed) {
                    PermissionRow("정확한 시각 알림이 꺼져 있어 몇 분 늦게 올 수 있습니다.", ::requestExactAlarmPermission)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("닫기", fontSize = 16.sp) }
        },
    )

    when (picker) {
        ReminderPicker.CHECK_IN -> TimePickDialog(
            title = "출근 알림 시각",
            initial = config.checkInTime,
            onPick = { update(config.copy(checkInTime = it)); picker = null },
            onClear = null,
            onDismiss = { picker = null },
        )
        ReminderPicker.CHECK_OUT -> TimePickDialog(
            title = "퇴근 알림 시각",
            initial = config.checkOutTime,
            onPick = { update(config.copy(checkOutTime = it)); picker = null },
            onClear = null,
            onDismiss = { picker = null },
        )
        null -> Unit
    }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onChange(!checked) }
            .padding(vertical = 6.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = label, modifier = Modifier.weight(1f), fontSize = 16.sp)
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun PermissionRow(message: String, onAllow: () -> Unit) {
    Spacer(modifier = Modifier.height(8.dp))
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = message,
            modifier = Modifier.weight(1f),
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.error,
        )
        TextButton(onClick = onAllow) { Text("허용") }
    }
}
