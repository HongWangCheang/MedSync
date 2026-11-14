package com.medsync.gateway;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
interface SessionMapper {
    /** ttlSeconds is computed by MySQL so the cache TTL never depends on app/DB clock or time-zone agreement. */
    record ActiveSession(String accountId, long ttlSeconds) {}

    void insert(@Param("tokenHash") String tokenHash, @Param("accountId") String accountId);

    ActiveSession findActive(@Param("tokenHash") String tokenHash);
}
