
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'history') THEN
        CREATE TYPE history AS (
            id text,
            event text,
            severity text,
            status text,
            value text,
            text text,
            type text,
            update_time timestamp without time zone,
            "user" text,
            timeout integer
        );
    ELSE
        BEGIN
            ALTER TYPE history ADD ATTRIBUTE "user" text CASCADE;
        EXCEPTION
            WHEN duplicate_column THEN RAISE NOTICE 'column "user" already exists in history type.';
        END;
        BEGIN
            ALTER TYPE history ADD ATTRIBUTE timeout integer CASCADE;
        EXCEPTION
            WHEN duplicate_column THEN RAISE NOTICE 'column "timeout" already exists in history type.';
        END;
    END IF;
END$$;


CREATE TABLE IF NOT EXISTS alerts (
    id text PRIMARY KEY,
    resource text NOT NULL,
    event text NOT NULL,
    environment text,
    severity text,
    correlate text[],
    status text,
    service text[],
    "group" text,
    value text,
    text text,
    tags text[],
    attributes jsonb,
    origin text,
    type text,
    create_time timestamp without time zone,
    timeout integer,
    raw_data text,
    customer text,
    duplicate_count integer,
    repeat boolean,
    previous_severity text,
    trend_indication text,
    receive_time timestamp without time zone,
    last_receive_id text,
    last_receive_time timestamp without time zone,
    history history[]
);

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS update_time timestamp without time zone;


CREATE TABLE IF NOT EXISTS notes (
    id text PRIMARY KEY,
    text text,
    "user" text,
    attributes jsonb,
    type text NOT NULL,
    create_time timestamp without time zone NOT NULL,
    update_time timestamp without time zone,
    alert text,
    customer text
);


CREATE TABLE IF NOT EXISTS blackouts (
    id text PRIMARY KEY,
    priority integer NOT NULL,
    environment text NOT NULL,
    service text[],
    resource text,
    event text,
    "group" text,
    tags text[],
    customer text,
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone NOT NULL,
    duration integer
);

ALTER TABLE blackouts
ADD COLUMN IF NOT EXISTS "user" text,
ADD COLUMN IF NOT EXISTS create_time timestamp without time zone,
ADD COLUMN IF NOT EXISTS text text,
ADD COLUMN IF NOT EXISTS origin text;


CREATE TABLE IF NOT EXISTS customers (
    id text PRIMARY KEY,
    match text NOT NULL,
    customer text
);

ALTER TABLE customers DROP CONSTRAINT IF EXISTS customers_match_key;


CREATE TABLE IF NOT EXISTS heartbeats (
    id text PRIMARY KEY,
    origin text NOT NULL,
    tags text[],
    type text,
    create_time timestamp without time zone,
    timeout integer,
    receive_time timestamp without time zone,
    customer text
);

ALTER TABLE heartbeats ADD COLUMN IF NOT EXISTS attributes jsonb;


CREATE TABLE IF NOT EXISTS keys (
    id text PRIMARY KEY,
    key text UNIQUE NOT NULL,
    "user" text NOT NULL,
    scopes text[],
    text text,
    expire_time timestamp without time zone,
    count integer,
    last_used_time timestamp without time zone,
    customer text
);


CREATE TABLE IF NOT EXISTS metrics (
    "group" text NOT NULL,
    name text NOT NULL,
    title text,
    description text,
    value integer,
    count integer,
    total_time integer,
    type text NOT NULL,
    CONSTRAINT metrics_pkey PRIMARY KEY ("group", name, type)
);
ALTER TABLE metrics ALTER COLUMN total_time TYPE BIGINT;
ALTER TABLE metrics ALTER COLUMN count TYPE BIGINT;


CREATE TABLE IF NOT EXISTS perms (
    id text PRIMARY KEY,
    match text UNIQUE NOT NULL,
    scopes text[]
);


CREATE TABLE IF NOT EXISTS users (
    id text PRIMARY KEY,
    name text,
    email text UNIQUE,
    password text NOT NULL,
    status text,
    roles text[],
    attributes jsonb,
    create_time timestamp without time zone NOT NULL,
    last_login timestamp without time zone,
    text text,
    update_time timestamp without time zone,
    email_verified boolean,
    hash text
);
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;

DO $$
BEGIN
    ALTER TABLE users ADD COLUMN login text UNIQUE;
    UPDATE users SET login = email;
    ALTER TABLE users ALTER COLUMN login SET NOT NULL;
EXCEPTION
    WHEN duplicate_column THEN RAISE NOTICE 'column "login" already exists in users.';
END$$;

CREATE TABLE IF NOT EXISTS groups (
    id text PRIMARY KEY,
    name text UNIQUE NOT NULL,
    users text[],
    text text,
    tags text[],
    attributes jsonb,
    update_time timestamp without time zone
);


-- Not creating index as this backend allows alerts with same environment, resource, event and customer.
-- CREATE UNIQUE INDEX IF NOT EXISTS env_res_evt_cust_key ON alerts USING btree (environment, resource, event, (COALESCE(customer, ''::text)));
DROP INDEX IF EXISTS env_res_evt_cust_key;

CREATE UNIQUE INDEX IF NOT EXISTS org_cust_key ON heartbeats USING btree (origin, (COALESCE(customer, ''::text)));

CREATE TABLE IF NOT EXISTS alerter_status (
    alert_id text NOT NULL,
    alerter text NOT NULL,
    status text NOT NULL,
    CONSTRAINT alerter_status_pkey PRIMARY KEY (alert_id, alerter),
    CONSTRAINT alerter_status_fkey_alert_id FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alerter_data (
    id bigserial PRIMARY KEY,
    alert_id text NOT NULL,
    alerter text NOT NULL,
    operation text NOT NULL,
    received_time timestamp without time zone,
    start_time timestamp without time zone,
    end_time timestamp without time zone,
    success boolean,
    skipped boolean,
    retries integer,
    response jsonb,
    reason text,
    bg_task_id text,
    task_chain_info jsonb,
    CONSTRAINT alerter_data_fkey_alert_id FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recovery_action_data (
    alert_id text NOT NULL PRIMARY KEY,
    provider text NOT NULL,
    actions text[] NOT NULL,
    status text NOT NULL,
    received_time timestamp without time zone,
    start_time timestamp without time zone,
    end_time timestamp without time zone,
    recovery_time timestamp without time zone,
    alerting_time timestamp without time zone,
    success boolean,
    retries integer,
    response jsonb,
    job_id text,
    bg_task_id text,
    CONSTRAINT recovery_action_data_fkey_alert_id FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS alerter_data_oper_key_unique ON alerter_data
USING btree (alert_id, alerter, operation) WHERE operation in ('new', 'recovery');

CREATE INDEX IF NOT EXISTS alerter_data_oper_key ON alerter_data
USING btree (alert_id, alerter, operation) WHERE operation not in ('new', 'recovery');

CREATE INDEX IF NOT EXISTS alerter_data_key ON alerter_data
USING btree (alert_id, alerter);

CREATE TABLE IF NOT EXISTS key_value_store (
    key VARCHAR(50) NOT NULL PRIMARY KEY,
    value text
);

CREATE SEQUENCE IF NOT EXISTS alert_contextual_rules_id_seq;

CREATE TABLE IF NOT EXISTS alert_contextual_rules (
    id integer DEFAULT nextval('alert_contextual_rules_id_seq') PRIMARY KEY,
    name text NOT NULL UNIQUE,
    rules jsonb NOT NULL,
    context jsonb NOT NULL,
    priority integer NOT NULL,
    last_check boolean DEFAULT FALSE
);

ALTER SEQUENCE alert_contextual_rules_id_seq
OWNED BY alert_contextual_rules.id;

ALTER TABLE alert_contextual_rules
ADD COLUMN IF NOT EXISTS append_lists boolean DEFAULT TRUE;

-- Table to store task/alert_id mapping for end-to-end async processing

CREATE TABLE IF NOT EXISTS async_alert (
    bg_task_id text NOT NULL PRIMARY KEY,
    alert_id text,
    errors jsonb,
    CONSTRAINT async_alert_fkey_alert_id FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

-- Table to store references to client event managers to send updates to.

CREATE TABLE IF NOT EXISTS external_references (
    alert_id text NOT NULL,
    platform text NOT NULL,
    reference text NOT NULL,
    CONSTRAINT external_references_pkey PRIMARY KEY (alert_id, platform, reference),
    CONSTRAINT external_references_fkey_alert_id FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS external_references_by_platform ON external_references
USING btree (alert_id, platform);

-- Table to store dependencies between alerts --
CREATE TABLE IF NOT EXISTS alert_dependency (
    resource text NOT NULL,
    event text NOT NULL,
    dependencies jsonb,
    CONSTRAINT alert_dependency_pkey PRIMARY KEY (resource, event)
);