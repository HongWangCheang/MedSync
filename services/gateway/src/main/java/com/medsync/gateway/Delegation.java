package com.medsync.gateway;

import java.security.SecureRandom;
import java.util.Base64;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * Least-privilege access for the agent side. A delegated token:
 * - is minted per dispatch, only for the step that needs it (ask_pharmacist → read medications);
 * - lives 2 minutes and carries one scope;
 * - has its own format ("dlg_" + 43 chars), which the normal Bearer check (exactly 43 chars) never accepts,
 *   so it cannot sync, submit actions or log in;
 * - travels to the agent in a header, never in the step body, so it is not stored in the ledger or checkpoints.
 */
@Service
class Delegation {
    static final String MEDICATIONS_READ = "medications:read";
    static final long TTL_SECONDS = 120;
    private static final String PREFIX = "dlg_";

    private final DelegationMapper mapper;
    private final RateLimiter limiter;
    private final SecureRandom random = new SecureRandom();

    Delegation(DelegationMapper mapper, RateLimiter limiter) {
        this.mapper = mapper;
        this.limiter = limiter;
    }

    String issue(String account, String scope) {
        mapper.deleteExpired();
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String token = PREFIX + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        mapper.insert(SyncAuth.digest(token), account, scope, TTL_SECONDS);
        return token;
    }

    String requireAccount(String authorization, String scope) {
        if (authorization == null || !authorization.matches("Bearer " + PREFIX + "[a-zA-Z0-9_-]{43}")) {
            throw unauthorized();
        }
        String account = mapper.findAccount(SyncAuth.digest(authorization.substring(7)), scope);
        if (account == null) {
            throw unauthorized();
        }
        limiter.checkAccount(account);
        return account;
    }

    List<DelegationMapper.Medication> medications(String account) {
        return mapper.recentMedications(account, 90, 50);
    }

    private static ResponseStatusException unauthorized() {
        return new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or expired delegation");
    }
}
