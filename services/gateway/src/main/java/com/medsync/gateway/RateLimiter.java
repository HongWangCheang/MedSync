package com.medsync.gateway;

import java.time.Clock;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

/**
 * Fixed one-minute window counters in Redis. INCR and EXPIRE run in one Lua script so a crash between them can't leave
 * a counter without a TTL. If Redis is down the limiter fails open: sync keeps working, it is just not rate limited.
 */
@Service
class RateLimiter {
    static class LimitExceeded extends RuntimeException {
        final long retryAfterSeconds;

        LimitExceeded(long retryAfterSeconds) {
            super("Rate limit exceeded");
            this.retryAfterSeconds = retryAfterSeconds;
        }
    }

    private static final DefaultRedisScript<Long> INCREMENT = new DefaultRedisScript<>("""
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
        return count
        """, Long.class);

    private final StringRedisTemplate redis;
    private final RedisGuard guard;
    private final Clock clock;
    private final int requestsPerMinute;
    private final int loginsPerMinute;

    @Autowired
    RateLimiter(StringRedisTemplate redis, RedisGuard guard,
                @Value("${medtrack.rate-limit.requests-per-minute}") int requestsPerMinute,
                @Value("${medtrack.rate-limit.logins-per-minute}") int loginsPerMinute) {
        this(redis, guard, Clock.systemUTC(), requestsPerMinute, loginsPerMinute);
    }

    RateLimiter(StringRedisTemplate redis, RedisGuard guard, Clock clock, int requestsPerMinute, int loginsPerMinute) {
        this.redis = redis;
        this.guard = guard;
        this.clock = clock;
        this.requestsPerMinute = requestsPerMinute;
        this.loginsPerMinute = loginsPerMinute;
    }

    void checkAccount(String accountId) {
        check("medsync:rate:account:" + accountId, requestsPerMinute);
    }

    /** Per-username login attempts, to slow password guessing against one account. */
    void checkLogin(String username) {
        check("medsync:rate:login:" + username, loginsPerMinute);
    }

    private void check(String prefix, int limit) {
        long second = clock.millis() / 1000;
        long window = second / 60;
        Long count = guard.call(() -> redis.execute(INCREMENT, List.of(prefix + ":" + window), "120"), null);
        if (count != null && count > limit) {
            throw new LimitExceeded(60 - second % 60);
        }
    }
}
