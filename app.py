#!/usr/bin/env python3
"""
Craigslist Listings Viewer - Flask App
"""

from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras
import json
import os
from datetime import datetime
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
import threading
from scraper import scrape_craigslist

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-in-production')

# Database configuration from environment variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'port': os.getenv('DB_PORT', '5432')
}

# JIRA configuration
JIRA_SITE_URL = os.getenv('JIRA_SITE_URL', 'https://yoursite.atlassian.net')
JIRA_EMAIL = os.getenv('JIRA_EMAIL')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
JIRA_CLOUD_ID = os.getenv('JIRA_CLOUD_ID')

# Upload configuration
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static/uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def trigger_n8n_research(listing_id):
    """Trigger n8n workflow to research a listing"""
    webhook_url = os.getenv('N8N_WEBHOOK_URL')
    if not webhook_url:
        return False
    
    try:
        response = requests.post(
            webhook_url,
            json={'listing_id': listing_id},
            timeout=5
        )
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"n8n webhook error: {e}")
        return False

def get_db_connection():
    """Create database connection"""
    try:
        return psycopg2.connect(**DB_CONFIG)
    except psycopg2.Error as e:
        print(f"Database connection error: {e}")
        raise

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def search_jira_issues(jql):
    """Search JIRA issues using JQL"""
    if not JIRA_EMAIL or not JIRA_API_TOKEN:
        return None
    
    url = f"{JIRA_SITE_URL}/rest/api/3/search/jql"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "jql": jql,
        "maxResults": 50,
        "fields": ["summary", "description", "status", "assignee", "created", "updated"]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, auth=auth)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"JIRA API error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return None

def get_jira_issue(issue_key):
    """Get a specific JIRA issue by key"""
    if not JIRA_EMAIL or not JIRA_API_TOKEN:
        return None
    
    url = f"{JIRA_SITE_URL}/rest/api/3/issue/{issue_key}"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, auth=auth)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"JIRA API error: {e}")
        return None

@app.template_filter('domain_name')
def domain_name_filter(url):
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        domain = domain.replace('www.', '')
        
        # Split by dots
        parts = domain.split('.')
        
        # If there are 3+ parts (like vermont.craigslist.org),
        # use the second-to-last part (the main domain)
        if len(parts) >= 3:
            return parts[-2].capitalize()
        # Otherwise (like ebay.com or packvintage.com), use the first part
        elif len(parts) >= 2:
            return parts[0].capitalize()
        else:
            return parts[0].capitalize()
    except:
        return 'Source'

@app.template_filter('currency')
def currency_filter(amount):
    """Format number as currency"""
    if amount is None:
        return "N/A"
    return f"${amount:,.2f}"

@app.template_filter('datetime')
def datetime_filter(date_obj):
    """Format datetime object"""
    if date_obj is None:
        return "N/A"
    return date_obj.strftime("%Y-%m-%d %H:%M")

# Make JIRA_SITE_URL available to all templates
@app.context_processor
def inject_globals():
    """Inject global variables into all templates"""
    return {
        'jira_site_url': JIRA_SITE_URL
    }

@app.route('/')
@app.route('/listings')
def listings_page():
    """Main listings page with filtering"""
    status_filter = request.args.get('status', 'all')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Get listings based on filter
    if status_filter == 'all':
        cur.execute("""
            SELECT id, jira_issue_key, title, suggested_price, status, 
                   condition, created_at, updated_at
            FROM craigslist_listings 
            ORDER BY created_at DESC
        """)
    else:
        cur.execute("""
            SELECT id, jira_issue_key, title, suggested_price, status, 
                   condition, created_at, updated_at
            FROM craigslist_listings 
            WHERE status = %s
            ORDER BY created_at DESC
        """, (status_filter,))
    
    listings = cur.fetchall()
    
    # Get status counts
    cur.execute("""
        SELECT status, COUNT(*) as count
        FROM craigslist_listings 
        GROUP BY status
    """)
    status_counts = {row['status']: row['count'] for row in cur.fetchall()}
    
    cur.close()
    conn.close()
    
    total_count = sum(status_counts.values())
    
    # Status badge mapping
    status_badges = {
        'draft': 'badge-secondary',
        'researching': 'badge-info',
        'ready': 'badge-success',
        'listed': 'badge-primary',
        'sold': 'badge-warning'
    }
    
    return render_template('listings.html',
                         listings=listings,
                         status_counts=status_counts,
                         total_count=total_count,
                         current_filter=status_filter,
                         status_badges=status_badges)

@app.route('/listing/<int:listing_id>')
def listing_detail(listing_id):
    """Detailed view of a single listing"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, jira_issue_key, title, description, category,
               price_min, price_max, suggested_price, condition,
               measurements, image_paths, research_sources, status,
               created_at, updated_at, listed_at, sold_at
        FROM craigslist_listings
        WHERE id = %s
    """, (listing_id,))

    listing = cur.fetchone()

    if not listing:
        cur.close()
        conn.close()
        return "Listing not found", 404

    # Get scraped sources
    cur.execute("""
        SELECT id, title, url, price, location, posted_date,
               description, condition, measurements, image_url, scraped_at
        FROM craigslist_sources
        WHERE listing_id = %s
        ORDER BY price ASC NULLS LAST
    """, (listing_id,))

    sources = cur.fetchall()

    cur.close()
    conn.close()

    # image_paths is now a native array, no need to parse
    listing['images'] = listing['image_paths'] if listing['image_paths'] else []
    listing['sources'] = sources

    return render_template('listing_detail.html', listing=listing)

@app.route('/listing/<int:listing_id>/update', methods=['POST'])
def update_listing_field(listing_id):
    """Update specific fields of a listing"""
    data = request.json

    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Check if listing exists
        cur.execute("SELECT id FROM craigslist_listings WHERE id = %s", (listing_id,))
        if not cur.fetchone():
            if cur:
                cur.close()
            if conn:
                conn.close()
            return jsonify({'success': False, 'error': 'Listing not found'}), 404

        # Build dynamic UPDATE query for allowed fields
        allowed_fields = ['title', 'status', 'condition', 'measurements', 'description']
        updates = []
        values = []

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        if not updates:
            if cur:
                cur.close()
            if conn:
                conn.close()
            return jsonify({'success': False, 'error': 'No valid fields to update'}), 400

        # Add updated_at timestamp
        updates.append("updated_at = CURRENT_TIMESTAMP")

        # Add listing_id for WHERE clause
        values.append(listing_id)

        # Execute update
        query = f"""
            UPDATE craigslist_listings
            SET {', '.join(updates)}
            WHERE id = %s
        """

        cur.execute(query, values)
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({'success': True, 'message': 'Listing updated successfully'})

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error updating listing: {e}")
        print(error_trace)

        if conn:
            conn.rollback()
        if cur:
            cur.close()
        if conn:
            conn.close()

        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/listing/<int:listing_id>/image/delete', methods=['POST'])
def delete_listing_image(listing_id):
    """Delete an image from a listing"""
    data = request.json
    image_path = data.get('image_path')

    if not image_path:
        return jsonify({'success': False, 'error': 'No image path provided'}), 400

    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get current listing
        cur.execute("""
            SELECT id, image_paths FROM craigslist_listings
            WHERE id = %s
        """, (listing_id,))

        listing = cur.fetchone()

        if not listing:
            if cur:
                cur.close()
            if conn:
                conn.close()
            return jsonify({'success': False, 'error': 'Listing not found'}), 404

        # Remove image_path from array
        current_images = listing['image_paths'] or []

        if image_path not in current_images:
            if cur:
                cur.close()
            if conn:
                conn.close()
            return jsonify({'success': False, 'error': 'Image not found in listing'}), 404

        # Remove from array
        new_images = [img for img in current_images if img != image_path]

        # Update database
        cur.execute("""
            UPDATE craigslist_listings
            SET image_paths = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_images, listing_id))

        conn.commit()

        # Try to delete physical file (optional - may want to keep for recovery)
        try:
            file_path = os.path.join('static', image_path)
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Deleted file: {file_path}")
        except Exception as e:
            print(f"Could not delete file {image_path}: {e}")
            # Don't fail the request if file deletion fails

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Image deleted successfully. {len(new_images)} image(s) remaining.',
            'remaining_count': len(new_images)
        }), 200

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error deleting image: {e}")
        print(error_trace)

        if conn:
            conn.rollback()
        if cur:
            cur.close()
        if conn:
            conn.close()

        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/listing/<int:listing_id>/source/add', methods=['POST'])
def add_source_to_listing(listing_id):
    """Add a new source to a listing from a URL"""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL is required'}), 400
    
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Verify listing exists
        cur.execute("SELECT id, title FROM craigslist_listings WHERE id = %s", (listing_id,))
        listing = cur.fetchone()
        
        if not listing:
            if cur:
                cur.close()
            if conn:
                conn.close()
            return jsonify({'success': False, 'error': 'Listing not found'}), 404
        
        # Extract fields from request (all optional except URL)
        title = data.get('title', 'Untitled Source')
        price = data.get('price')
        location = data.get('location')
        posted_date = data.get('posted_date')
        description = data.get('description')
        condition = data.get('condition')
        measurements = data.get('measurements')
        image_url = data.get('image_url')
        
        # Convert price to decimal if it's a string
        if price and isinstance(price, str):
            try:
                # Remove $ and commas
                price = price.replace('$', '').replace(',', '').strip()
                price = float(price)
            except ValueError:
                price = None
        
        print(f"\nAdding source to listing #{listing_id}:")
        print(f"  URL: {url}")
        print(f"  Title: {title}")
        print(f"  Price: ${price}" if price else "  Price: None")
        
        # Insert the source
        cur.execute("""
            INSERT INTO craigslist_sources
            (listing_id, title, url, price, location, posted_date,
             description, condition, measurements, image_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (listing_id, url) DO UPDATE SET
                title = EXCLUDED.title,
                price = EXCLUDED.price,
                location = EXCLUDED.location,
                posted_date = EXCLUDED.posted_date,
                description = EXCLUDED.description,
                condition = EXCLUDED.condition,
                measurements = EXCLUDED.measurements,
                image_url = EXCLUDED.image_url,
                scraped_at = CURRENT_TIMESTAMP
            RETURNING id
        """, (
            listing_id,
            title,
            url,
            price,
            location,
            posted_date,
            description,
            condition,
            measurements,
            image_url
        ))
        
        result = cur.fetchone()
        source_id = result['id']
        
        # Recalculate price statistics
        cur.execute("""
            SELECT 
                COUNT(*) as source_count,
                MIN(price) as min_price,
                MAX(price) as max_price,
                AVG(price) as avg_price
            FROM craigslist_sources
            WHERE listing_id = %s AND price IS NOT NULL
        """, (listing_id,))
        
        stats = cur.fetchone()
        
        # Update listing with new price info
        if stats and stats['source_count'] > 0:
            cur.execute("""
                UPDATE craigslist_listings 
                SET price_min = %s,
                    price_max = %s,
                    suggested_price = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                stats['min_price'],
                stats['max_price'],
                round(float(stats['avg_price']), 2) if stats['avg_price'] else None,
                listing_id
            ))
        
        conn.commit()
        
        print(f"  ✓ Source added with ID: {source_id}")
        if stats and stats['source_count'] > 0:
            print(f"  Updated pricing: ${stats['min_price']:.2f} - ${stats['max_price']:.2f}")
        
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Source added successfully',
            'source_id': source_id,
            'stats': dict(stats) if stats and stats['source_count'] > 0 else None
        }), 201
        
    except psycopg2.IntegrityError as e:
        if conn:
            conn.rollback()
        if cur:
            cur.close()
        if conn:
            conn.close()
        
        return jsonify({
            'success': False,
            'error': 'This URL already exists for this listing'
        }), 409
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error adding source: {e}")
        print(error_trace)
        
        if conn:
            conn.rollback()
        if cur:
            cur.close()
        if conn:
            conn.close()
        
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/listing/<int:listing_id>/scrape-craigslist', methods=['POST'])
def scrape_craigslist_sources(listing_id):
    """Scrape Craigslist for similar listings"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get listing details
    cur.execute("SELECT id, title, status FROM craigslist_listings WHERE id = %s", (listing_id,))
    listing = cur.fetchone()

    if not listing:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'error': 'Listing not found'}), 404

    # Update status to researching
    cur.execute("""
        UPDATE craigslist_listings
        SET status = 'researching', updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (listing_id,))
    conn.commit()

    try:
        # Scrape Craigslist (Vermont by default)
        print(f"\n{'='*60}")
        print(f"Starting scrape for listing #{listing_id}: {listing['title']}")
        print(f"{'='*60}\n")

        results = scrape_craigslist(listing['title'], region='vermont', max_results=10)

        print(f"\n{'='*60}")
        print(f"Scraper returned {len(results)} results")
        print(f"{'='*60}\n")

        if not results:
            print("WARNING: No results returned from scraper")
            # Still update status to ready even with no results
            cur.execute("""
                UPDATE craigslist_listings
                SET status = 'ready', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (listing_id,))
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({
                'success': True,
                'message': 'No similar listings found',
                'stats': {'source_count': 0}
            })

        # Save results to database
        saved_count = 0
        errors = []

        for i, result in enumerate(results, 1):
            try:
                print(f"\nSaving result {i}/{len(results)}: {result['title'][:50]}...")
                print(f"  URL: {result['url']}")
                print(f"  Price: ${result['price']}")

                cur.execute("""
                    INSERT INTO craigslist_sources
                    (listing_id, title, url, price, location, posted_date,
                     description, condition, measurements, image_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (listing_id, url) DO NOTHING
                    RETURNING id
                """, (
                    listing_id,
                    result['title'],
                    result['url'],
                    result['price'],
                    result['location'],
                    result['posted_date'],
                    result['description'],
                    result['condition'],
                    result['measurements'],
                    result['image_url']
                ))

                inserted = cur.fetchone()
                if inserted:
                    print(f"  ✓ Saved with ID: {inserted['id']}")
                    saved_count += 1
                else:
                    print(f"  ⚠ Duplicate (already exists)")

            except psycopg2.Error as e:
                error_msg = f"Error saving source {i}: {e}"
                print(f"  ✗ {error_msg}")
                errors.append(error_msg)
                conn.rollback()  # Rollback this insert but continue
                continue

        # Commit all successful inserts
        conn.commit()

        print(f"\n{'='*60}")
        print(f"Saved {saved_count} out of {len(results)} results")
        if errors:
            print(f"Errors encountered: {len(errors)}")
            for error in errors:
                print(f"  - {error}")
        print(f"{'='*60}\n")

        # Calculate price statistics
        cur.execute("""
            SELECT
                COUNT(*) as source_count,
                MIN(price) as min_price,
                MAX(price) as max_price,
                AVG(price) as avg_price
            FROM craigslist_sources
            WHERE listing_id = %s AND price IS NOT NULL
        """, (listing_id,))

        stats = cur.fetchone()

        print(f"Price statistics:")
        print(f"  Count: {stats['source_count']}")
        print(f"  Min: ${stats['min_price']}")
        print(f"  Max: ${stats['max_price']}")
        print(f"  Avg: ${stats['avg_price']}")

        # Update listing with price info and status
        if stats and stats['source_count'] > 0:
            cur.execute("""
                UPDATE craigslist_listings
                SET price_min = %s,
                    price_max = %s,
                    suggested_price = %s,
                    status = 'ready',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                stats['min_price'],
                stats['max_price'],
                round(stats['avg_price'], 2) if stats['avg_price'] else None,
                listing_id
            ))
            print(f"\n✓ Updated listing with price range: ${stats['min_price']} - ${stats['max_price']}")
        else:
            # No sources with prices found, just mark as ready
            cur.execute("""
                UPDATE craigslist_listings
                SET status = 'ready', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (listing_id,))
            print(f"\n⚠ No sources with prices found, marked as ready")

        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Found {saved_count} similar listings',
            'stats': dict(stats) if stats else {'source_count': 0},
            'errors': errors if errors else None
        })

    except Exception as e:
        # Reset status on error
        import traceback
        error_trace = traceback.format_exc()
        print(f"\n{'='*60}")
        print(f"ERROR during scraping:")
        print(error_trace)
        print(f"{'='*60}\n")

        try:
            cur.execute("""
                UPDATE craigslist_listings
                SET status = 'draft', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (listing_id,))
            conn.commit()
        except:
            pass

        cur.close()
        conn.close()

        return jsonify({'success': False, 'error': str(e), 'trace': error_trace}), 500

@app.route('/jira-tasks')
def jira_tasks():
    """Show JIRA tasks in TODO status"""
    # Default JQL for listing tasks in TODO status
    jql = 'project = "ecommerce-site" AND status = "TO DO" AND labels = listing ORDER BY created DESC'
    
    # Allow custom JQL from query params
    custom_jql = request.args.get('jql')
    if custom_jql:
        jql = custom_jql
    
    issues_data = search_jira_issues(jql)
    
    if issues_data is None:
        flash('Unable to connect to JIRA. Check your configuration.', 'error')
        issues = []
    else:
        issues = issues_data.get('issues', [])
    
    # Check which issues already have listings
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT jira_issue_key FROM craigslist_listings")
    existing_keys = {row['jira_issue_key'] for row in cur.fetchall()}
    cur.close()
    conn.close()
    
    return render_template('jira_tasks.html', 
                         issues=issues, 
                         existing_keys=existing_keys,
                         current_jql=jql)

@app.route('/create-listing/<issue_key>', methods=['GET', 'POST'])
def create_listing(issue_key):
    """Create a new listing from a JIRA issue"""
    # Get JIRA issue details
    issue = get_jira_issue(issue_key)
    
    if not issue:
        flash(f'Could not find JIRA issue {issue_key}', 'error')
        return redirect(url_for('jira_tasks'))
    
    if request.method == 'POST':
        # Extract form data
        title = request.form.get('title')
        condition = request.form.get('condition')
        measurements = request.form.get('measurements')
        category = request.form.get('category')
        
        # Handle file uploads
        uploaded_files = request.files.getlist('images')
        image_paths = []
        
        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to avoid collisions
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                # Store relative path from static folder
                image_paths.append(f"uploads/{filename}")
        
        # Insert into database
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            INSERT INTO craigslist_listings 
            (jira_issue_key, title, condition, measurements, category, image_paths, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'draft')
            RETURNING id
        """, (issue_key, title, condition, measurements, category, image_paths))
        
        listing_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()
        
        flash(f'Listing created successfully! ID: {listing_id}', 'success')
        return redirect(url_for('listing_detail', listing_id=listing_id))
    
    # GET request - show form
    fields = issue.get('fields', {})
    
    # Extract useful fields from JIRA
    initial_data = {
        'title': fields.get('summary', ''),
        'description': fields.get('description', {}).get('content', [{}])[0].get('content', [{}])[0].get('text', '') if isinstance(fields.get('description'), dict) else '',
        'issue_key': issue_key,
        'issue_url': f"{JIRA_SITE_URL}/browse/{issue_key}"
    }
    
    return render_template('create_listing.html', issue=issue, initial_data=initial_data)

@app.route('/api/listings')
def api_listings():
    """JSON API endpoint for listings"""
    status_filter = request.args.get('status', 'all')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    if status_filter == 'all':
        cur.execute("""
            SELECT id, jira_issue_key, title, suggested_price, status, 
                   condition, created_at, updated_at
            FROM craigslist_listings 
            ORDER BY created_at DESC
        """)
    else:
        cur.execute("""
            SELECT id, jira_issue_key, title, suggested_price, status, 
                   condition, created_at, updated_at
            FROM craigslist_listings 
            WHERE status = %s
            ORDER BY created_at DESC
        """, (status_filter,))
    
    listings = cur.fetchall()
    cur.close()
    conn.close()
    
    # Convert datetime objects to ISO format strings
    for listing in listings:
        if listing['created_at']:
            listing['created_at'] = listing['created_at'].isoformat()
        if listing['updated_at']:
            listing['updated_at'] = listing['updated_at'].isoformat()
    
    return jsonify(listings)

@app.route('/listing/<int:listing_id>/research', methods=['POST'])
def trigger_research(listing_id):
    """Trigger research workflow for a listing"""
    # Check if listing exists
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cur.execute("SELECT id, status FROM craigslist_listings WHERE id = %s", (listing_id,))
    listing = cur.fetchone()
    
    if not listing:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'error': 'Listing not found'}), 404
    
    # Trigger the n8n workflow in a separate thread so we can respond immediately
    def async_trigger():
        trigger_n8n_research(listing_id)
    
    thread = threading.Thread(target=async_trigger)
    thread.start()
    
    cur.close()
    conn.close()
    
    flash('Research started! The page will update as results come in.', 'success')
    return jsonify({'success': True, 'message': 'Research started'})

@app.route('/listing/<int:listing_id>/source/<int:source_id>/delete', methods=['POST', 'DELETE'])
def delete_source(listing_id, source_id):
    """Delete a research source and recalculate pricing"""
    print(f"Delete source called: listing_id={listing_id}, source_id={source_id}")
    
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Verify the source belongs to this listing
        cur.execute("""
            SELECT id FROM craigslist_sources 
            WHERE id = %s AND listing_id = %s
        """, (source_id, listing_id))
        
        source = cur.fetchone()
        
        if not source:
            print(f"Source not found: source_id={source_id}, listing_id={listing_id}")
            if cur:
                cur.close()
            if conn:
                conn.close()
            return jsonify({'success': False, 'error': 'Source not found'}), 404
        
        print(f"Deleting source {source_id}...")
        
        # Delete the source
        cur.execute("DELETE FROM craigslist_sources WHERE id = %s", (source_id,))
        
        # Recalculate price statistics
        cur.execute("""
            SELECT 
                COUNT(*) as source_count,
                MIN(price) as min_price,
                MAX(price) as max_price,
                AVG(price) as avg_price
            FROM craigslist_sources
            WHERE listing_id = %s AND price IS NOT NULL
        """, (listing_id,))
        
        stats = cur.fetchone()
        print(f"Recalculated stats: {stats}")
        
        # Update listing with new price info
        if stats and stats['source_count'] > 0:
            cur.execute("""
                UPDATE craigslist_listings 
                SET price_min = %s,
                    price_max = %s,
                    suggested_price = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                stats['min_price'],
                stats['max_price'],
                round(float(stats['avg_price']), 2) if stats['avg_price'] else None,
                listing_id
            ))
            
            message = f"Source deleted. Updated pricing: ${stats['min_price']:.2f} - ${stats['max_price']:.2f}"
        else:
            # No sources left, clear pricing
            cur.execute("""
                UPDATE craigslist_listings 
                SET price_min = NULL,
                    price_max = NULL,
                    suggested_price = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (listing_id,))
            
            message = "Source deleted. No sources remaining - pricing cleared."
        
        conn.commit()
        print(f"Success: {message}")
        
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': message,
            'stats': dict(stats) if stats and stats['source_count'] > 0 else None
        }), 200
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error deleting source: {e}")
        print(error_trace)
        
        if conn:
            conn.rollback()
        if cur:
            cur.close()
        if conn:
            conn.close()
        
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/listing/<int:listing_id>/sources/delete-all', methods=['POST'])
def delete_all_sources(listing_id):
    """Delete all research sources for a listing"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # Check if listing exists
        cur.execute("SELECT id FROM craigslist_listings WHERE id = %s", (listing_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Listing not found'}), 404
        
        # Get count before deleting
        cur.execute("SELECT COUNT(*) as count FROM craigslist_sources WHERE listing_id = %s", (listing_id,))
        count = cur.fetchone()['count']
        
        # Delete all sources for this listing
        cur.execute("DELETE FROM craigslist_sources WHERE listing_id = %s", (listing_id,))
        
        # Clear pricing from listing
        cur.execute("""
            UPDATE craigslist_listings 
            SET price_min = NULL,
                price_max = NULL,
                suggested_price = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (listing_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Deleted {count} sources. Pricing cleared.'
        })
        
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        print(f"Error deleting all sources: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({'status': 'healthy', 'database': 'connected'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

if __name__ == '__main__':
    # Validate required environment variables
    required_vars = ['DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file")
        exit(1)
    
    port = int(os.getenv('PORT', 8000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() in ['true', '1', 'yes']
    
    print(f"""
╔══════════════════════════════════════════════════════╗
║   Craigslist Listings Viewer (Flask)                 ║
║   Server running at http://localhost:{port}          ║
║                                                       ║
║   Database: {os.getenv('DB_NAME')}@{os.getenv('DB_HOST')}
║   Debug Mode: {debug}                                ║
║                                                       ║
║   Routes:                                             ║
║   - /                    All listings (with filters)  ║
║   - /listing/<id>        Single listing details      ║
║   - /jira-tasks          JIRA tasks to list          ║
║   - /create-listing/<key> Create from JIRA          ║
║   - /api/listings        JSON API                    ║
║   - /health              Health check                ║
║                                                       ║
║   Press Ctrl+C to stop                                ║
╚══════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=port, debug=debug)
