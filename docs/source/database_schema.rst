Database Schema
===============

.. code-block:: sql


    CREATE TABLE package_rules (
        scan_id UUID NOT NULL,
        rule_id UUID NOT NULL,
        PRIMARY KEY (scan_id, rule_id),
        FOREIGN KEY (scan_id) REFERENCES scans(scan_id),
        FOREIGN KEY (rule_id) REFERENCES rules(id)
    );

    CREATE TABLE scans (
        scan_id UUID PRIMARY KEY,
        name VARCHAR,
        version VARCHAR,
        status VARCHAR,
        score INT,
        inspector_url VARCHAR,
        queued_at TIMESTAMPTZ NULL DEFAULT CURRENT_TIMESTAMP,
        queued_by VARCHAR,
        pending_at TIMESTAMPTZ,
        pending_by VARCHAR,
        finished_at TIMESTAMPTZ,
        finished_by VARCHAR,
        reported_at TIMESTAMPTZ,
        reported_by VARCHAR,
        fail_reason VARCHAR,
        commit_hash VARCHAR ,
        UNIQUE (name, version)
    );


    CREATE UNIQUE INDEX idx_scans_name_version ON scans(name, version);
    CREATE INDEX idx_scans_status ON scans(status) 
        WHERE status IN ('QUEUED', 'PENDING');


    CREATE TABLE download_urls (
        id UUID PRIMARY KEY,
        scan_id UUID NOT NULL,
        url VARCHAR NOT NULL,
        FOREIGN KEY (scan_id) REFERENCES scans(scan_id)
    );


    CREATE TABLE rules (
        id UUID PRIMARY KEY,
        name VARCHAR UNIQUE NOT NULL
    );


.. image:: /images/schema.svg
   :alt: ER Diagram
   :width: 800px
   :align: center


