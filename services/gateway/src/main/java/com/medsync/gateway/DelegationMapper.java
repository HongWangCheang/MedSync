package com.medsync.gateway;

import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
interface DelegationMapper {
    record Medication(String name, long lastTakenAt, int timesRecorded) {}

    void insert(@Param("tokenHash") String tokenHash, @Param("accountId") String accountId,
                @Param("scope") String scope, @Param("ttlSeconds") long ttlSeconds);

    /** Account for an unexpired token of exactly this scope, or null. Expiry is checked by MySQL's clock. */
    String findAccount(@Param("tokenHash") String tokenHash, @Param("scope") String scope);

    int deleteExpired();

    /** What the user has recorded taking recently, one row per drug name, newest first. */
    List<Medication> recentMedications(@Param("account") String account, @Param("days") int days,
                                       @Param("limit") int limit);
}
