package com.kanbikang.attendance.data

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface WorkRecordDao {
    @Query("SELECT * FROM work_records WHERE date = :date LIMIT 1")
    suspend fun get(date: String): WorkRecord?

    @Query("SELECT * FROM work_records WHERE date BETWEEN :from AND :to ORDER BY date DESC")
    fun observeBetween(from: String, to: String): Flow<List<WorkRecord>>

    @Query("SELECT * FROM work_records WHERE date BETWEEN :from AND :to ORDER BY date ASC")
    suspend fun listBetween(from: String, to: String): List<WorkRecord>

    @Upsert
    suspend fun upsert(record: WorkRecord)

    @Query("DELETE FROM work_records WHERE date = :date")
    suspend fun deleteByDate(date: String)
}
