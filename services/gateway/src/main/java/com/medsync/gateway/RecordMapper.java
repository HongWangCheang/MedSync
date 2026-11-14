package com.medsync.gateway;

import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
interface RecordMapper {
    record RequestReceipt(String fingerprint, long revision) {}
    record Row(String recordId, String kind, String body, long revision) {}

    RequestReceipt findRequest(@Param("account") String account, @Param("requestId") String requestId);

    int countRecord(@Param("account") String account, @Param("recordId") String recordId);

    void insertRecord(@Param("account") String account, @Param("recordId") String recordId, @Param("kind") String kind,
                      @Param("body") String body, @Param("revision") long revision);

    void insertRequest(@Param("account") String account, @Param("requestId") String requestId,
                       @Param("fingerprint") String fingerprint, @Param("revision") long revision);

    List<Row> changesAfter(@Param("account") String account, @Param("after") long after, @Param("limit") int limit);
}
