--
-- PostgreSQL database dump
--

\restrict jOJyaHj0QvRguqo7wD7Igv9chIUUq0dYDOeLa3y1DrXHTxSFO58MZxETJXIlfz6

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg13+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: fuzzystrmatch; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS fuzzystrmatch WITH SCHEMA public;


--
-- Name: EXTENSION fuzzystrmatch; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION fuzzystrmatch IS 'determine similarities and distance between strings';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: dictionary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dictionary (
    ancient_word character varying NOT NULL,
    modern_definition text NOT NULL,
    modern_word text,
    status text DEFAULT 'pending'::text,
    error text
);


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id character varying NOT NULL,
    json_data jsonb NOT NULL,
    modernized_content text,
    embedding public.vector(1024),
    raw_content text GENERATED ALWAYS AS (COALESCE((json_data ->> 'description'::text), ''::text)) STORED,
    search_tsvector tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, COALESCE((json_data ->> 'description'::text), ''::text))) STORED,
    embed_text text
);


--
-- Name: dictionary dictionary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dictionary
    ADD CONSTRAINT dictionary_pkey PRIMARY KEY (ancient_word);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: documents_embedding_hnsw_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documents_embedding_hnsw_idx ON public.documents USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: documents_raw_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documents_raw_trgm_idx ON public.documents USING gin (raw_content public.gin_trgm_ops);


--
-- Name: documents_search_tsvector_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documents_search_tsvector_idx ON public.documents USING gin (search_tsvector);


--
-- PostgreSQL database dump complete
--

\unrestrict jOJyaHj0QvRguqo7wD7Igv9chIUUq0dYDOeLa3y1DrXHTxSFO58MZxETJXIlfz6

