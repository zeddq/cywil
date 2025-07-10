--
-- PostgreSQL database dump
--

-- Dumped from database version 15.13
-- Dumped by pg_dump version 17.5

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: paralegal
--

INSERT INTO public.users (email, full_name, role, is_active, is_verified, id, hashed_password, created_at, updated_at, last_login) VALUES ('zeddq1@gmail.com', 'Cezary Marczak', 'admin', true, true, '2331cff6-82aa-4230-8a51-65732bc7a745', '$2b$12$Z/RKUBn9OQ3gcrHJTEG3e.PcO4M43GSFX04bkaGmrWC4MfxHuAY5.', '2025-07-05 21:21:40.571642', '2025-07-07 23:53:53.988477', '2025-07-07 23:53:53.982072');


--
-- PostgreSQL database dump complete
--

