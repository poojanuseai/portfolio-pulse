-- Portfolio Pulse — Supabase/Postgres schema.
-- Run once in the Supabase SQL editor. Mirrors the SQLite schema in store/db.py.
-- All tables are written only by the poller (service-role key). The dashboard
-- reads with the same key (or a read-only key). No public/anon access.

-- Drop tables from the original broker/DMA-oriented build, if this is being
-- re-run against a project that already had them — this fork has no broker
-- connection and no DMA signal, so these are dead weight.
drop table if exists dma_state;
drop table if exists auth_token;
drop table if exists seen_items;

create table if not exists watchlist (
    symbol      text primary key,
    name        text not null default '',
    kind        text not null default 'watch',   -- 'holding' | 'watch'
    added_at    timestamptz not null default now()
);

create table if not exists holdings_snapshot (
    symbol      text primary key,
    qty         double precision not null default 0,
    avg_price   double precision not null default 0,
    last_price  double precision not null default 0,
    synced_at   timestamptz not null default now()
);

create table if not exists alerts (
    id          bigserial primary key,
    symbol      text not null,
    alert_type  text not null,                    -- taxonomy TBD, see signals/criteria.py
    title       text not null default '',
    summary     text not null default '',
    impact      text not null default '',
    source_url  text not null default '',
    source_type text not null default '',
    qc_status   text not null default '',
    created_at  timestamptz not null default now(),
    delivered   boolean not null default false
);

create table if not exists meta (
    key   text primary key,
    value text
);

create index if not exists idx_alerts_symbol  on alerts(symbol);
create index if not exists idx_alerts_created on alerts(created_at desc);
