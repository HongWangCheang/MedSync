package com.medsync.gateway;

import java.util.List;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/** Endpoints reachable only with a delegated token (see {@link Delegation}). */
@RestController
class DelegatedController {
    record Medications(List<DelegationMapper.Medication> medications) {}

    private final Delegation delegation;

    DelegatedController(Delegation delegation) {
        this.delegation = delegation;
    }

    @GetMapping("/v1/delegated/medications")
    Medications medications(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token) {
        return new Medications(delegation.medications(delegation.requireAccount(token, Delegation.MEDICATIONS_READ)));
    }
}
