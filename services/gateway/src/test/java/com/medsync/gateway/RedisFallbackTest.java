package com.medsync.gateway;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Redis is an optimisation: these check the service keeps working, correctly, when it is down. */
class RedisFallbackTest {
    private final Clock clock = Clock.fixed(Instant.parse("2026-11-13T10:00:45Z"), ZoneOffset.UTC);

    @Test
    @SuppressWarnings("unchecked")
    void sessionLookupFallsBackToMySqlAndSkipsRedisDuringCoolDown() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.opsForValue()).thenThrow(new RedisConnectionFailureException("down"));
        SessionMapper sessions = mock(SessionMapper.class);
        when(sessions.findActive("hash")).thenReturn(new SessionMapper.ActiveSession("account-1", 600));
        SessionCache cache = new SessionCache(redis, sessions, new RedisGuard(clock));

        assertThat(cache.accountFor("hash")).isEqualTo("account-1");
        assertThat(cache.accountFor("hash")).isEqualTo("account-1");
        verify(sessions, times(2)).findActive("hash");
        verify(redis, times(1)).opsForValue(); // second lookup skipped Redis entirely (cool-down)
    }

    @Test
    @SuppressWarnings("unchecked")
    void cacheHitDoesNotTouchMySqlAndMissIsStoredWithTheSessionTtl() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        SessionMapper sessions = mock(SessionMapper.class);
        SessionCache cache = new SessionCache(redis, sessions, new RedisGuard(clock));

        when(values.get(SessionCache.key("hit"))).thenReturn("account-hit");
        assertThat(cache.accountFor("hit")).isEqualTo("account-hit");
        verify(sessions, never()).findActive("hit");

        when(sessions.findActive("miss")).thenReturn(new SessionMapper.ActiveSession("account-miss", 1234));
        assertThat(cache.accountFor("miss")).isEqualTo("account-miss");
        verify(values).set(SessionCache.key("miss"), "account-miss", java.time.Duration.ofSeconds(1234));

        assertThat(cache.accountFor("unknown")).isNull();
    }

    @Test
    void rateLimiterFailsOpenWhenRedisIsDown() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.execute(any(RedisScript.class), anyList(), anyString()))
            .thenThrow(new RedisConnectionFailureException("down"));
        RateLimiter limiter = new RateLimiter(redis, new RedisGuard(clock), clock, 1, 1);
        limiter.checkAccount("account-1");
        limiter.checkAccount("account-1");
    }

    @Test
    void rateLimiterRejectsOverLimitWithSecondsUntilNextWindow() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.execute(any(RedisScript.class), anyList(), anyString())).thenReturn(1L, 2L, 3L);
        RateLimiter limiter = new RateLimiter(redis, new RedisGuard(clock), clock, 2, 2);
        limiter.checkAccount("a");
        limiter.checkAccount("a");
        assertThatThrownBy(() -> limiter.checkAccount("a"))
            .isInstanceOfSatisfying(RateLimiter.LimitExceeded.class, e -> assertThat(e.retryAfterSeconds).isEqualTo(15));
        verify(redis, times(3)).execute(any(RedisScript.class), eq(List.of("medsync:rate:account:a:" + (clock.millis() / 60_000))), eq("120"));
    }
}
