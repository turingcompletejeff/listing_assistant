CREATE TABLE craigslist_listings (
    id SERIAL PRIMARY KEY,
    jira_issue_key VARCHAR(20),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    price_min DECIMAL(10,2),
    price_max DECIMAL(10,2),
    suggested_price DECIMAL(10,2),
    condition VARCHAR(50),
    measurements TEXT,
    image_paths TEXT[], -- Array of image file paths
    research_sources JSONB, -- Store source links with prices
    status VARCHAR(50) DEFAULT 'draft', -- draft, ready, listed, sold
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    listed_at TIMESTAMP,
    sold_at TIMESTAMP
);

CREATE INDEX idx_jira_issue ON craigslist_listings(jira_issue_key);
CREATE INDEX idx_status ON craigslist_listings(status);

GRANT ALL PRIVILEGES ON TABLE craigslist_listings TO flasker;