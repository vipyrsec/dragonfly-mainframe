Database Schema
===============

.. code-block:: sql

    CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;

    CREATE TYPE public.status AS ENUM (
        'QUEUED',
        'PENDING',
        'FINISHED',
        'FAILED'
    );

    CREATE TABLE public.download_urls (
        id uuid NOT NULL,
        scan_id uuid NOT NULL,
        url text NOT NULL
    );

    CREATE TABLE public.package_rules (
        scan_id uuid NOT NULL,
        rule_id uuid NOT NULL
    );

    CREATE TABLE public.rules (
        name text NOT NULL,
        id uuid NOT NULL
    );

    CREATE TABLE public.scans (
        scan_id uuid NOT NULL,
        name text NOT NULL,
        status public.status NOT NULL,
        score integer,
        version text NOT NULL,
        queued_at timestamp without time zone,
        pending_at timestamp without time zone,
        finished_at timestamp without time zone,
        reported_at timestamp without time zone,
        inspector_url text,
        reported_by text,
        queued_by text NOT NULL,
        pending_by text,
        finished_by text,
        commit_hash text,
        fail_reason text,
        files jsonb
    );

    ALTER TABLE ONLY public.download_urls
        ADD CONSTRAINT download_urls_pkey PRIMARY KEY (id);

    ALTER TABLE ONLY public.scans
        ADD CONSTRAINT name_version_unique UNIQUE (name, version);

    ALTER TABLE ONLY public.package_rules
        ADD CONSTRAINT package_rules_pkey PRIMARY KEY (scan_id, rule_id);

    ALTER TABLE ONLY public.scans
        ADD CONSTRAINT packages_pkey PRIMARY KEY (scan_id);

    ALTER TABLE ONLY public.rules
        ADD CONSTRAINT rules_name_key UNIQUE (name);

    ALTER TABLE ONLY public.rules
        ADD CONSTRAINT rules_pkey PRIMARY KEY (id);

    CREATE INDEX ix_download_urls_scan_id ON public.download_urls USING btree (scan_id);

    CREATE INDEX ix_scans_finished_at ON public.scans USING btree (finished_at);

    CREATE INDEX ix_scans_status ON public.scans USING btree (status) WHERE ((status = 'QUEUED'::public.status) OR (status = 'PENDING'::public.status));

    ALTER TABLE ONLY public.download_urls
        ADD CONSTRAINT download_urls_scan_id_fkey FOREIGN KEY (scan_id) REFERENCES public.scans(scan_id);

    ALTER TABLE ONLY public.package_rules
        ADD CONSTRAINT package_rules_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.rules(id);

    ALTER TABLE ONLY public.package_rules
        ADD CONSTRAINT package_rules_scan_id_fkey FOREIGN KEY (scan_id) REFERENCES public.scans(scan_id);

.. image:: /images/schema.svg
   :alt: ER Diagram
   :width: 800px
   :align: center
