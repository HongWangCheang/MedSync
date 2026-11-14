package com.medsync.gateway;

import java.time.Duration;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

/**
 * Cache-aside lookup of token hash -> account id. Entries expire exactly when the session row does, so the cache can
 * never keep an expired token alive. MySQL stays the source of truth.
 */
@Service
class SessionCache {
    private final StringRedisTemplate redis;
    private final SessionMapper sessions;
    private final RedisGuard guard;

    SessionCache(StringRedisTemplate redis, SessionMapper sessions, RedisGuard guard) {
        this.redis = redis;
        this.sessions = sessions;
        this.guard = guard;
    }

    static String key(String tokenHash) {
        return "medsync:session:" + tokenHash;
    }

    /** Returns the account id, or null if the token is unknown or expired. */
    String accountFor(String tokenHash) {
        String cached = guard.call(() -> redis.opsForValue().get(key(tokenHash)), null);
        if (cached != null) {
            return cached;
        }
        SessionMapper.ActiveSession session = sessions.findActive(tokenHash);
        if (session == null) {
            return null;
        }
        if (session.ttlSeconds() > 0) {
            guard.call(() -> {
                redis.opsForValue().set(key(tokenHash), session.accountId(), Duration.ofSeconds(session.ttlSeconds()));
                return null;
            }, null);
        }
        return session.accountId();
    }
}
