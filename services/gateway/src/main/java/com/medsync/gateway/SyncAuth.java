package com.medsync.gateway;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Locale;
import java.util.UUID;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
class SyncAuth {
    record Credentials(String username, String password) {}
    record Session(String accountId, String token) {}
    private final AccountMapper accounts;
    private final SessionMapper sessions;
    private final SessionCache cache;
    private final RateLimiter limiter;
    private final BCryptPasswordEncoder bcrypt = new BCryptPasswordEncoder(12);
    private final SecureRandom random = new SecureRandom();
    private final String missingAccountHash = bcrypt.encode(UUID.randomUUID().toString());

    SyncAuth(AccountMapper accounts, SessionMapper sessions, SessionCache cache, RateLimiter limiter) {
        this.accounts = accounts;
        this.sessions = sessions;
        this.cache = cache;
        this.limiter = limiter;
    }

    @Transactional
    public Session register(Credentials input) {
        String name = username(input);
        String id = UUID.randomUUID().toString();
        try {
            accounts.insert(id, name, bcrypt.encode(input.password()));
        } catch (DuplicateKeyException exception) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Username already exists");
        }
        return issue(id);
    }

    public Session login(Credentials input) {
        String name = username(input);
        limiter.checkLogin(name);
        AccountMapper.Account account = accounts.findByUsername(name);
        boolean valid = bcrypt.matches(input.password(), account == null ? missingAccountHash : account.passwordHash());
        if (!valid || account == null) {
            throw unauthorized();
        }
        return issue(account.id());
    }

    private String username(Credentials input) {
        if (input == null || input.username() == null || input.password() == null ||
                !input.username().matches("[a-zA-Z0-9_.-]{3,40}") || input.password().length() < 8 ||
                input.password().getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid username or password format");
        }
        return input.username().toLowerCase(Locale.ROOT);
    }

    private Session issue(String accountId) {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        sessions.insert(digest(token), accountId);
        return new Session(accountId, token);
    }

    String requireAccount(String authorization) {
        if (authorization == null || !authorization.matches("Bearer [a-zA-Z0-9_-]{43}")) {
            throw unauthorized();
        }
        String account = cache.accountFor(digest(authorization.substring(7)));
        if (account == null) {
            throw unauthorized();
        }
        limiter.checkAccount(account);
        return account;
    }

    static String digest(String input) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(input.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }

    private static ResponseStatusException unauthorized() {
        return new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or expired credentials");
    }
}
