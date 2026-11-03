@file:OptIn(ExperimentalMaterial3Api::class)

package com.kanbikang.attendance.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.kanbikang.attendance.data.Times
import com.kanbikang.attendance.data.WorkRecord
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneOffset

private enum class Picker { DATE, CHECK_IN, CHECK_OUT }

/**
 * 기록 추가/수정 대화상자.
 * @param initial null이면 새 기록 추가, 아니면 해당 기록 수정
 * @param onSave (원래 날짜, 저장할 기록)
 */
@Composable
fun RecordEditorDialog(
    initial: WorkRecord?,
    onDismiss: () -> Unit,
    onSave: (originalDate: String?, record: WorkRecord) -> Unit,
    onDelete: (date: String) -> Unit,
) {
    val initialDate = remember(initial) { initial?.let { LocalDate.parse(it.date) } ?: LocalDate.now() }
    var date by remember { mutableStateOf(initialDate) }
    var checkIn by remember {
        mutableStateOf(initial?.checkIn?.let { Times.toLocalDateTime(it).toLocalTime() })
    }
    var checkOut by remember {
        mutableStateOf(initial?.checkOut?.let { Times.toLocalDateTime(it).toLocalTime() })
    }
    var nextDay by remember {
        mutableStateOf(initial?.checkOut?.let { Times.toLocalDateTime(it).toLocalDate() != initialDate } ?: false)
    }
    var error by remember { mutableStateOf<String?>(null) }
    var picker by remember { mutableStateOf<Picker?>(null) }

    fun trySave() {
        val inMs = checkIn?.let { Times.toMillis(date.atTime(it)) }
        val outDate = if (nextDay) date.plusDays(1) else date
        val outMs = checkOut?.let { Times.toMillis(outDate.atTime(it)) }
        when {
            inMs == null && outMs == null -> error = "출근 또는 퇴근 시각을 입력하세요."
            inMs != null && outMs != null && outMs <= inMs ->
                error = "퇴근이 출근보다 빠릅니다. 자정 이후 퇴근이면 '퇴근이 다음날'을 체크하세요."
            else -> onSave(initial?.date, WorkRecord(date = date.toString(), checkIn = inMs, checkOut = outMs))
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "기록 추가" else "기록 수정") },
        text = {
            Column {
                FieldRow(label = "날짜", value = "${date} (${Times.weekdayShort(date)})") { picker = Picker.DATE }
                HorizontalDivider()
                FieldRow(label = "출근", value = checkIn?.let { Times.hhmm(it) } ?: "없음") { picker = Picker.CHECK_IN }
                HorizontalDivider()
                FieldRow(label = "퇴근", value = checkOut?.let { Times.hhmm(it) } ?: "없음") { picker = Picker.CHECK_OUT }
                HorizontalDivider()
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { nextDay = !nextDay },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(checked = nextDay, onCheckedChange = { nextDay = it })
                    Text("퇴근이 다음날 (자정 이후)")
                }
                error?.let {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(it, color = MaterialTheme.colorScheme.error, fontSize = 14.sp)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { trySave() }) { Text("저장", fontSize = 16.sp) }
        },
        dismissButton = {
            Row {
                if (initial != null) {
                    TextButton(onClick = { onDelete(initial.date) }) {
                        Text("삭제", color = MaterialTheme.colorScheme.error, fontSize = 16.sp)
                    }
                }
                TextButton(onClick = onDismiss) { Text("취소", fontSize = 16.sp) }
            }
        },
    )

    when (picker) {
        Picker.DATE -> DatePickDialog(
            initial = date,
            onPick = { date = it; picker = null },
            onDismiss = { picker = null },
        )
        Picker.CHECK_IN -> TimePickDialog(
            title = "출근 시각",
            initial = checkIn ?: LocalTime.of(9, 0),
            onPick = { checkIn = it; error = null; picker = null },
            onClear = { checkIn = null; picker = null },
            onDismiss = { picker = null },
        )
        Picker.CHECK_OUT -> TimePickDialog(
            title = "퇴근 시각",
            initial = checkOut ?: LocalTime.of(18, 0),
            onPick = { checkOut = it; error = null; picker = null },
            onClear = { checkOut = null; picker = null },
            onDismiss = { picker = null },
        )
        null -> Unit
    }
}

@Composable
private fun FieldRow(label: String, value: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 14.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = label, modifier = Modifier.weight(1f), fontSize = 16.sp)
        Text(text = value, fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun DatePickDialog(initial: LocalDate, onPick: (LocalDate) -> Unit, onDismiss: () -> Unit) {
    val state = rememberDatePickerState(
        initialSelectedDateMillis = initial.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(),
    )
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = {
                val ms = state.selectedDateMillis
                if (ms != null) {
                    onPick(Instant.ofEpochMilli(ms).atZone(ZoneOffset.UTC).toLocalDate())
                } else {
                    onDismiss()
                }
            }) { Text("확인") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("취소") } },
    ) {
        DatePicker(state = state)
    }
}

@Composable
private fun TimePickDialog(
    title: String,
    initial: LocalTime,
    onPick: (LocalTime) -> Unit,
    onClear: () -> Unit,
    onDismiss: () -> Unit,
) {
    val state = rememberTimePickerState(
        initialHour = initial.hour,
        initialMinute = initial.minute,
        is24Hour = true,
    )
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { TimePicker(state = state) },
        confirmButton = {
            TextButton(onClick = { onPick(LocalTime.of(state.hour, state.minute)) }) { Text("확인") }
        },
        dismissButton = {
            Row {
                TextButton(onClick = onClear) { Text("지우기") }
                TextButton(onClick = onDismiss) { Text("취소") }
            }
        },
    )
}
