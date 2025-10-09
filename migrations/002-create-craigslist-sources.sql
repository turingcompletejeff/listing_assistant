-- Create table for storing scraped Craigslist sources
CREATE TABLE IF NOT EXISTS craigslist_sources (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES craigslist_listings(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    price DECIMAL(10, 2),
    location TEXT,
    posted_date TEXT,
    description TEXT,
    condition TEXT,
    measurements TEXT,
    image_url TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(listing_id, url)  -- Prevent duplicate sources for same listing
);

CREATE INDEX idx_craigslist_sources_listing_id ON craigslist_sources(listing_id);

GRANT ALL PRIVILEGES ON TABLE craigslist_sources TO flasker;
