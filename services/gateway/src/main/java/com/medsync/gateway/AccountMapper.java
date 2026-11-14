package com.medsync.gateway;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
interface AccountMapper {
    record Account(String id, String passwordHash) {}

    void insert(@Param("id") String id, @Param("username") String username, @Param("passwordHash") String passwordHash);

    Account findByUsername(@Param("username") String username);

    /** Row lock on the account; serializes writes and revision allocation in commit order. */
    Long lockRevision(@Param("id") String id);

    void updateRevision(@Param("id") String id, @Param("revision") long revision);
}
