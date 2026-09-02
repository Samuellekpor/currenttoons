-- Banque de personnages (alternative à Google Sheets).
-- Run in the Supabase SQL editor once per project.

create table if not exists public.personnages (
  id bigint generated always as identity primary key,
  nom text not null,
  photo_reference_url text,
  caricature_url text,
  date_generation timestamptz default now(),
  nb_utilisations integer not null default 0,
  feature_emphasis text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists personnages_nom_normalized_idx
  on public.personnages (lower(trim(nom)));

comment on table public.personnages is
  'Public figures caricatured once, then reused across videos.';
