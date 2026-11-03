package com.kanbikang.attendance.data

import android.content.Context
import kotlinx.coroutines.flow.Flow
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.YearMonth

/** 출퇴근 규칙(중복 출근 무시, 퇴근 갱신, 자정 넘김 처리)을 담당한다. */
class AttendanceRepository private constructor(private val dao: WorkRecordDao) {

    /** 출근: 같은 날 첫 기록만 유지한다. */
    suspend fun checkIn(now: LocalDateTime = Times.now()): String {
        val today = now.toLocalDate().toString()
        val existing = dao.get(today)
        if (existing?.checkIn != null) {
            return "이미 출근 ${Times.hhmm(existing.checkIn)} 기록됨"
        }
        val nowMs = Times.toMillis(now)
        dao.upsert((existing ?: WorkRecord(today)).copy(checkIn = nowMs))
        return "출근 ${Times.hhmm(nowMs)} 저장"
    }

    /** 퇴근: 마지막으로 누른 시각으로 갱신한다. 자정을 넘겼으면 전날 출근 기록에 붙인다. */
    suspend fun checkOut(now: LocalDateTime = Times.now()): String {
        val target = activeRecord(now)
        val nowMs = Times.toMillis(now)
        dao.upsert(target.copy(checkOut = nowMs))
        val prefix = if (target.date != now.toLocalDate().toString()) "어제 출근분 퇴근" else "퇴근"
        return "$prefix ${Times.hhmm(nowMs)} 저장"
    }

    /**
     * 지금 시점에 "진행 중"인 기록을 고른다.
     * 1) 오늘 기록이 있으면 오늘
     * 2) 오늘 기록이 없고, 어제 출근 후 24시간이 지나지 않았으며 아직 퇴근 전(또는 자정 이후 퇴근)이면 어제
     * 3) 그 외에는 비어 있는 오늘 기록
     */
    suspend fun activeRecord(now: LocalDateTime = Times.now()): WorkRecord {
        val today = now.toLocalDate()
        dao.get(today.toString())?.let { return it }

        val yesterday = dao.get(today.minusDays(1).toString())
        val yIn = yesterday?.checkIn
        if (yesterday != null && yIn != null) {
            val inTime = Times.toLocalDateTime(yIn)
            val within24h = Duration.between(inTime, now).toHours() < 24
            val out = yesterday.checkOut
            val openOrCrossed = out == null || !Times.toLocalDateTime(out).toLocalDate().isBefore(today)
            if (within24h && openOrCrossed) return yesterday
        }
        return WorkRecord(today.toString())
    }

    suspend fun widgetState(now: LocalDateTime = Times.now()): WidgetState {
        val record = activeRecord(now)
        val recordDate = LocalDate.parse(record.date)
        val title = if (recordDate == now.toLocalDate()) {
            Times.dateLabel(recordDate)
        } else {
            "어제 ${Times.dateLabel(recordDate)} 출근분"
        }
        return WidgetState(
            title = title,
            checkIn = Times.timeLabel(record.checkIn, recordDate),
            checkOut = Times.timeLabel(record.checkOut, recordDate),
        )
    }

    fun observeMonth(ym: YearMonth): Flow<List<WorkRecord>> =
        dao.observeBetween(ym.atDay(1).toString(), ym.atEndOfMonth().toString())

    suspend fun monthRecords(ym: YearMonth): List<WorkRecord> =
        dao.listBetween(ym.atDay(1).toString(), ym.atEndOfMonth().toString())

    /** 수동 저장. 날짜를 바꾼 경우 이전 날짜의 기록은 지운다. */
    suspend fun save(originalDate: String?, record: WorkRecord) {
        if (originalDate != null && originalDate != record.date) {
            dao.deleteByDate(originalDate)
        }
        dao.upsert(record)
    }

    suspend fun delete(date: String) = dao.deleteByDate(date)

    companion object {
        @Volatile
        private var instance: AttendanceRepository? = null

        fun get(context: Context): AttendanceRepository = instance ?: synchronized(this) {
            instance ?: AttendanceRepository(AppDatabase.get(context).workRecordDao()).also { instance = it }
        }
    }
}
