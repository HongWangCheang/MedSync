package com.medsync.gateway;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
interface ActionMapper {
    record Row(String stepKey, String planId, int stepIndex, String tool, String fingerprint, String request,
               String status, String result, String reason) {}

    Row find(@Param("account") String account, @Param("stepKey") String stepKey);

    void insert(@Param("account") String account, @Param("stepKey") String stepKey, @Param("planId") String planId,
                @Param("stepIndex") int stepIndex, @Param("tool") String tool,
                @Param("fingerprint") String fingerprint, @Param("request") String request,
                @Param("status") String status);

    /** Moves a step forward; rows already DONE / FAILED / CANCELLED are never rewritten. Returns rows changed. */
    int updateOutcome(@Param("account") String account, @Param("stepKey") String stepKey,
                      @Param("status") String status, @Param("result") String result, @Param("reason") String reason);
}
