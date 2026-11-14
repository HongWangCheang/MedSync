CREATE TABLE IF NOT EXISTS sync_account (
    id CHAR(36) PRIMARY KEY,
    username VARCHAR(40) NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sync_session (
    token_hash CHAR(64) PRIMARY KEY,
    account_id CHAR(36) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (account_id) REFERENCES sync_account (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sync_record (
    account_id CHAR(36) NOT NULL,
    record_id CHAR(36) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    body JSON NOT NULL,
    revision BIGINT NOT NULL,
    PRIMARY KEY (account_id, record_id),
    UNIQUE KEY sync_record_revision (account_id, revision),
    FOREIGN KEY (account_id) REFERENCES sync_account (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sync_request (
    account_id CHAR(36) NOT NULL,
    request_id CHAR(36) NOT NULL,
    fingerprint CHAR(64) NOT NULL,
    revision BIGINT NOT NULL,
    PRIMARY KEY (account_id, request_id),
    FOREIGN KEY (account_id) REFERENCES sync_account (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- MedSync: one row per logical agent step. step_key is generated on the device when the step is planned, so every
-- retry, app restart and re-dispatch of the same step lands on this row instead of creating a new side effect.
CREATE TABLE IF NOT EXISTS action_ledger (
    account_id CHAR(36) NOT NULL,
    step_key CHAR(64) NOT NULL,
    plan_id VARCHAR(64) NOT NULL,
    step_index INT NOT NULL,
    tool VARCHAR(64) NOT NULL,
    fingerprint CHAR(64) NOT NULL,
    request JSON NOT NULL,
    status VARCHAR(16) NOT NULL,
    result JSON NULL,
    reason VARCHAR(500) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, step_key),
    KEY action_ledger_plan (account_id, plan_id),
    FOREIGN KEY (account_id) REFERENCES sync_account (id) ON DELETE CASCADE
) ENGINE=InnoDB;
