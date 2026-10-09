"""Schema and rows for the sample custom-format dump."""

from __future__ import annotations

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE customers (
        id integer PRIMARY KEY,
        email text NOT NULL
    )
    """,
    """
    CREATE TABLE orders (
        id integer PRIMARY KEY,
        customer_id integer NOT NULL REFERENCES customers (id),
        created_at timestamptz NOT NULL
    )
    """,
    """
    INSERT INTO customers (id, email) VALUES
        (1, 'a@example.com'),
        (2, 'b@example.com')
    """,
    """
    INSERT INTO orders (id, customer_id, created_at) VALUES
        (1, 1, CURRENT_TIMESTAMP),
        (2, 2, CURRENT_TIMESTAMP - INTERVAL '5 minutes')
    """,
)
