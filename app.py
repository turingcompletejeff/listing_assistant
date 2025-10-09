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
    cur.close()
    conn.close()
    
    if not listing:
        return "Listing not found", 404
    
    # Parse JSON fields
    if listing['research_sources']:
        listing['sources'] = json.loads(listing['research_sources']) if isinstance(listing['research_sources'], str) else listing['research_sources']
    else:
        listing['sources'] = []
    
    # image_paths is now a native array, no need to parse
    listing['images'] = listing['image_paths'] if listing['image_paths'] else []
    
    return render_template('listing_detail.html', listing=listing)

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
