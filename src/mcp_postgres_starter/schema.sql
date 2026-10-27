-- Demo store schema. Swap it for your own tables: only queries.py knows these names.

CREATE TABLE IF NOT EXISTS customers (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    email       text NOT NULL UNIQUE,
    country     text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
    id           bigserial PRIMARY KEY,
    sku          text NOT NULL UNIQUE,
    name         text NOT NULL,
    category     text NOT NULL,
    price_cents  integer NOT NULL CHECK (price_cents >= 0),
    stock        integer NOT NULL CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    id           bigserial PRIMARY KEY,
    customer_id  bigint NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    status       text NOT NULL CHECK (status IN ('pending', 'paid', 'shipped', 'cancelled', 'refunded')),
    created_at   timestamptz NOT NULL,
    due_date     date NOT NULL,
    paid_at      timestamptz
);
CREATE INDEX IF NOT EXISTS orders_created_at ON orders (created_at);
CREATE INDEX IF NOT EXISTS orders_status_due ON orders (status, due_date);

CREATE TABLE IF NOT EXISTS order_items (
    order_id          bigint NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    product_id        bigint NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    quantity          integer NOT NULL CHECK (quantity > 0),
    unit_price_cents  integer NOT NULL CHECK (unit_price_cents >= 0),
    PRIMARY KEY (order_id, product_id)
);

-- Every tool call, allowed or refused. Kept in the database so it survives restarts and can be queried.
CREATE TABLE IF NOT EXISTS audit_log (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    client_id   text NOT NULL,
    tool        text NOT NULL,
    arguments   jsonb NOT NULL,
    ok          boolean NOT NULL,
    rows        integer,
    duration_ms integer NOT NULL,
    error       text
);
