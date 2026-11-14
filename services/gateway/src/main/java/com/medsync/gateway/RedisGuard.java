package com.medsync.gateway;

import java.time.Clock;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;

/**
 * Runs Redis calls so that an outage degrades the service instead of failing requests. After a failure, Redis is
 * skipped for a short cool-down so every request doesn't pay the connect timeout while it is down.
 */
@Component
class RedisGuard {
    private static final Logger log = LoggerFactory.getLogger(RedisGuard.class);
    static final long COOL_DOWN_MILLIS = 10_000;

    private final Clock clock;
    private volatile long skipUntil;

    RedisGuard() {
        this(Clock.systemUTC());
    }

    RedisGuard(Clock clock) {
        this.clock = clock;
    }

    <T> T call(Supplier<T> action, T fallback) {
        if (clock.millis() < skipUntil) {
            return fallback;
        }
        try {
            return action.get();
        } catch (DataAccessException exception) {
            skipUntil = clock.millis() + COOL_DOWN_MILLIS;
            log.warn("Redis unavailable, falling back for {} ms: {}", COOL_DOWN_MILLIS, exception.getMessage());
            return fallback;
        }
    }
}
