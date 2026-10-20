-- MALI MODE founder trade and formalisation tables.
-- Run in Supabase SQL Editor if your deployment database user cannot create tables at startup.
-- Existing users/profiles/transactions are not modified by this migration.
create table if not exists supplier_listings (
  id serial primary key,
  owner_user_id integer not null references users(id) on delete cascade,
  supplier_name varchar(180) not null,
  category varchar(100) not null,
  description text not null default '',
  price integer null,
  unit varchar(60) not null default 'unit',
  location varchar(180) not null default '',
  contact_name varchar(180) not null default '',
  contact_email varchar(255) not null default '',
  contact_phone varchar(60) not null default '',
  active boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists ix_supplier_listings_owner_user_id on supplier_listings(owner_user_id);
create index if not exists ix_supplier_listings_active on supplier_listings(active);

create table if not exists business_orders (
  id serial primary key,
  user_id integer not null references users(id) on delete cascade,
  supplier_listing_id integer null references supplier_listings(id) on delete set null,
  supplier_name varchar(180) not null,
  item_or_service varchar(240) not null,
  quantity varchar(40) not null default '1',
  quoted_total integer null,
  delivery_address varchar(300) not null default '',
  notes text not null default '',
  status varchar(40) not null default 'requested',
  created_at timestamptz not null default now()
);
create index if not exists ix_business_orders_user_id on business_orders(user_id);

create table if not exists founder_documents (
  id serial primary key,
  user_id integer not null references users(id) on delete cascade,
  document_type varchar(100) not null,
  title varchar(200) not null,
  content text not null,
  created_at timestamptz not null default now()
);
create index if not exists ix_founder_documents_user_id on founder_documents(user_id);
