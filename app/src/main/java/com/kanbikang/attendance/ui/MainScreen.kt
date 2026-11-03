@file:OptIn(ExperimentalMaterial3Api::class)

package com.kanbikang.attendance.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.kanbikang.attendance.data.Times
import com.kanbikang.attendance.data.WorkRecord
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.YearMonth

private sealed interface EditorTarget {
    data object Add : EditorTarget
    data class Edit(val record: WorkRecord) : EditorTarget
}

@Composable
fun MainScreen(viewModel: MainViewModel = viewModel()) {
    val month by viewModel.month.collectAsStateWithLifecycle()
    val records by viewModel.records.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var editor by remember { mutableStateOf<EditorTarget?>(null) }

    Scaffold(
        topBar = { TopAppBar(title = { Text("출퇴근 기록") }) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { editor = EditorTarget.Add },
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text("기록 추가") },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            MonthHeader(
                month = month,
                onPrevious = viewModel::previousMonth,
                onNext = viewModel::nextMonth,
            )
            SummaryCard(
                records = records,
                onExport = {
                    scope.launch {
                        context.startActivity(viewModel.exportIntent(context))
                    }
                },
            )
            if (records.isEmpty()) {
                EmptyHint()
            } else {
                RecordList(records = records, onClick = { editor = EditorTarget.Edit(it) })
            }
        }
    }

    editor?.let { target ->
        RecordEditorDialog(
            initial = (target as? EditorTarget.Edit)?.record,
            onDismiss = { editor = null },
            onSave = { originalDate, record ->
                viewModel.save(originalDate, record)
                editor = null
            },
            onDelete = { date ->
                viewModel.delete(date)
                editor = null
            },
        )
    }
}

@Composable
private fun MonthHeader(month: YearMonth, onPrevious: () -> Unit, onNext: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        IconButton(onClick = onPrevious) {
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, contentDescription = "이전 달")
        }
        Text(
            text = Times.monthLabel(month),
            fontSize = 22.sp,
            fontWeight = FontWeight.Bold,
        )
        IconButton(onClick = onNext) {
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = "다음 달")
        }
    }
}

@Composable
private fun SummaryCard(records: List<WorkRecord>, onExport: () -> Unit) {
    val workDays = records.count { it.checkIn != null }
    val totalMinutes = records.sumOf { Times.workedMinutes(it) ?: 0L }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = "근무일수  ${workDays}일", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                Spacer(modifier = Modifier.height(4.dp))
                Text(text = "근무시간  ${Times.durationLabel(totalMinutes)}", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            }
            OutlinedButton(onClick = onExport, enabled = records.isNotEmpty()) {
                Icon(Icons.Filled.Share, contentDescription = null)
                Spacer(modifier = Modifier.padding(horizontal = 4.dp))
                Text("CSV")
            }
        }
    }
}

@Composable
private fun EmptyHint() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "이 달의 기록이 없습니다.\n홈 화면 위젯의 [출근] [퇴근] 버튼을 누르면 여기에 쌓입니다.",
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontSize = 16.sp,
        )
    }
}

@Composable
private fun RecordList(records: List<WorkRecord>, onClick: (WorkRecord) -> Unit) {
    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 6.dp),
        ) {
            HeaderCell("날짜", 1.3f)
            HeaderCell("출근", 1f)
            HeaderCell("퇴근", 1.1f)
            HeaderCell("근무시간", 1.3f)
        }
        HorizontalDivider()
        LazyColumn(modifier = Modifier.fillMaxSize()) {
            items(records, key = { it.date }) { record ->
                RecordRow(record = record, onClick = { onClick(record) })
                HorizontalDivider()
            }
            item { Spacer(modifier = Modifier.height(96.dp)) }
        }
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.HeaderCell(text: String, weight: Float) {
    Text(
        text = text,
        modifier = Modifier.weight(weight),
        fontSize = 14.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun RecordRow(record: WorkRecord, onClick: () -> Unit) {
    val date = LocalDate.parse(record.date)
    val minutes = Times.workedMinutes(record)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = Times.dateLabel(date), modifier = Modifier.weight(1.3f), fontSize = 16.sp, fontWeight = FontWeight.Medium)
        Text(text = Times.timeLabel(record.checkIn, date), modifier = Modifier.weight(1f), fontSize = 16.sp)
        Text(text = Times.timeLabel(record.checkOut, date), modifier = Modifier.weight(1.1f), fontSize = 16.sp)
        Text(text = Times.durationLabel(minutes), modifier = Modifier.weight(1.3f), fontSize = 16.sp)
    }
}
