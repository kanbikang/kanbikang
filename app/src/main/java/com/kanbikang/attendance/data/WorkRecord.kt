package com.kanbikang.attendance.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * 하루치 출퇴근 기록.
 * @param date 근무일 (yyyy-MM-dd). 자정을 넘겨 퇴근해도 출근한 날짜가 기준이다.
 * @param checkIn 출근 시각 (epoch millis)
 * @param checkOut 퇴근 시각 (epoch millis). 다음날 새벽일 수 있다.
 */
@Entity(tableName = "work_records")
data class WorkRecord(
    @PrimaryKey val date: String,
    val checkIn: Long? = null,
    val checkOut: Long? = null,
)
