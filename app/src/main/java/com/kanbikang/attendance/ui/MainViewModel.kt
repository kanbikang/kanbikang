package com.kanbikang.attendance.ui

import android.app.Application
import android.content.Context
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.glance.appwidget.updateAll
import com.kanbikang.attendance.data.AttendanceRepository
import com.kanbikang.attendance.data.CsvExporter
import com.kanbikang.attendance.data.WorkRecord
import com.kanbikang.attendance.widget.AttendanceWidget
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.YearMonth

@OptIn(ExperimentalCoroutinesApi::class)
class MainViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = AttendanceRepository.get(app)

    private val _month = MutableStateFlow(YearMonth.now())
    val month: StateFlow<YearMonth> = _month

    val records: StateFlow<List<WorkRecord>> = _month
        .flatMapLatest { repo.observeMonth(it) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    fun previousMonth() {
        _month.value = _month.value.minusMonths(1)
    }

    fun nextMonth() {
        _month.value = _month.value.plusMonths(1)
    }

    fun save(originalDate: String?, record: WorkRecord) {
        viewModelScope.launch {
            repo.save(originalDate, record)
            refreshWidget()
        }
    }

    fun delete(date: String) {
        viewModelScope.launch {
            repo.delete(date)
            refreshWidget()
        }
    }

    suspend fun exportIntent(context: Context): Intent = withContext(Dispatchers.IO) {
        val ym = _month.value
        CsvExporter.shareIntent(context, ym, repo.monthRecords(ym))
    }

    private suspend fun refreshWidget() {
        AttendanceWidget().updateAll(getApplication())
    }
}
