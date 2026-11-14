package com.medsync.gateway;

import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/v1")
class SyncController {
    private final SyncAuth auth;
    private final SyncRecords records;

    SyncController(SyncAuth auth, SyncRecords records) {
        this.auth = auth;
        this.records = records;
    }

    @PostMapping("/auth/register")
    @ResponseStatus(HttpStatus.CREATED)
    SyncAuth.Session register(@RequestBody SyncAuth.Credentials body) {
        return auth.register(body);
    }

    @PostMapping("/auth/login")
    SyncAuth.Session login(@RequestBody SyncAuth.Credentials body) {
        return auth.login(body);
    }

    @PutMapping("/sync/writes/{requestId}")
    SyncRecords.Receipt write(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
                              @PathVariable UUID requestId, @RequestBody SyncRecords.Write body) {
        return records.write(auth.requireAccount(token), requestId, body);
    }

    @GetMapping("/sync/changes")
    SyncRecords.Page changes(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
                             @RequestParam(defaultValue = "0") long after,
                             @RequestParam(defaultValue = "50") int limit) {
        return records.changes(auth.requireAccount(token), after, limit);
    }

    /** 429 with Retry-After; the Android client already backs off exponentially on 429. */
    @ExceptionHandler(RateLimiter.LimitExceeded.class)
    ResponseEntity<Void> rateLimited(RateLimiter.LimitExceeded exception) {
        return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
            .header(HttpHeaders.RETRY_AFTER, Long.toString(exception.retryAfterSeconds)).build();
    }
}
