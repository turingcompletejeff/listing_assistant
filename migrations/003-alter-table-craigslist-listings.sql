ALTER TABLE craigslist_listings DROP COULMN research_sources;

ALTER TABLE craigslist_listings ADD COLUMN list_price DECIMAL(10,2);

ALTER TABLE craigslist_listings ADD COLUMN sold_price DECIMAL(10,2);