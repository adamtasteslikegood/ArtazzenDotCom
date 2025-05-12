import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import logging  # Import logging
import json
from PIL import Image
from PIL.ExifTags import TAGS
from datetime import datetime

# --- Configuration ---
# Get the directory where this script is located
BASE_DIR = Path(__file__).resolve().parent
# Define directories relative to the base directory
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
TEMPLATES_DIR = BASE_DIR / "templates"

# Create the necessary directories if they don't exist
# parents=True creates any necessary parent directories
# exist_ok=True prevents an error if the directory already exists
STATIC_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)  # For optional CSS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FastAPI App Setup ---
app = FastAPI(title="Artwork Gallery")

# Mount the 'static' directory. This makes files under 'static/'
# accessible via URLs starting with '/static'. For example,
# '/static/images/my_art.jpg' will serve the file 'static/images/my_art.jpg'.
# The 'name="static"' allows generating URLs using url_for('static', path=...) in templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Set up Jinja2 templating. This allows using HTML files from the 'templates'
# directory to render responses.
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Helper Function ---
def get_image_metadata(file_path):
    """
    Extract metadata from image file and optional JSON metadata file
    """
    metadata = {
        "name": file_path.name,
        "title": file_path.stem,  # Default to filename without extension
        "description": "",
        "date_added": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
        "size": file_path.stat().st_size
    }
    
    # Try to load additional metadata from a companion JSON file
    json_path = file_path.with_suffix('.json')
    if json_path.exists():
        try:
            with open(json_path, 'r') as f:
                custom_metadata = json.load(f)
                metadata.update(custom_metadata)
        except json.JSONDecodeError as e:
            logger.error(f"Error reading metadata file {json_path}: {e}")

    # Try to get image-specific metadata using PIL
    try:
        with Image.open(file_path) as img:
            # Get basic image info
            metadata.update({
                "width": img.width,
                "height": img.height,
                "format": img.format,
            })
            
            # Try to get EXIF data if available
            if hasattr(img, '_getexif') and img._getexif():
                exif = img._getexif()
                if exif:
                    for tag_id in exif:
                        tag = TAGS.get(tag_id, tag_id)
                        data = exif.get(tag_id)
                        if tag in ['ImageDescription', 'UserComment']:
                            metadata['description'] = str(data)
                        elif tag == 'DateTime':
                            metadata['date_taken'] = data
                            
    except Exception as e:
        logger.error(f"Error reading image metadata for {file_path}: {e}")
    
    return metadata

def get_artwork_files():
    """
    Scans the IMAGES_DIR and returns a list of dictionaries,
    each containing the URL, name, and metadata of an image file.
    """
    artwork = []
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff"}
    logger.info(f"Scanning for artwork in: {IMAGES_DIR}")
    
    if IMAGES_DIR.exists() and IMAGES_DIR.is_dir():
        try:
            for filename in os.listdir(IMAGES_DIR):
                file_path = IMAGES_DIR / filename
                if file_path.is_file():
                    file_ext = file_path.suffix.lower()
                    if file_ext in allowed_extensions:
                        # Get metadata for the image
                        metadata = get_image_metadata(file_path)
                        
                        # Construct the web-accessible URL path
                        image_url = f"/static/images/{filename}"
                        
                        # Combine URL and metadata
                        artwork_item = {
                            "url": image_url,
                            "metadata": metadata
                        }
                        
                        artwork.append(artwork_item)
                        logger.debug(f"Found artwork with metadata: {filename}")
            
        except OSError as e:
            logger.error(f"Error reading image directory {IMAGES_DIR}: {e}")
            return []
    else:
        logger.warning(f"Images directory not found or is not a directory: {IMAGES_DIR}")

    logger.info(f"Found {len(artwork)} artwork files.")
    return artwork

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    Handles requests to the root URL ('/').
    It gets the list of artwork files and renders the index.html template.
    """
    logger.info("Request received for root path ('/')")
    artwork_list = get_artwork_files()

    # Data to pass to the HTML template
    context = {
        "request": request,  # Required by Jinja2Templates
        "artwork_files": artwork_list,
        "gallery_title": "My Girlfriend's Artwork Gallery"  # Customizable title
    }

    # Render the HTML template with the context data
    return templates.TemplateResponse("index.html", context)

# --- Running the App ---
# To run this app:
# 1. Save this code as 'main.py'.
# 2. Make sure you have the 'static/images' and 'templates' directories set up.
# 3. Put artwork images in 'static/images'.
# 4. Create 'templates/index.html' (code provided separately).
# 5. Create `static/css/styles.css` (code provided separately).
# 6. Create a virtual environment: python -m venv .venv
# 7. Activate it: source .venv/bin/activate (or .\venv\Scripts\activate on Windows)
# 8. Install the necessary libraries: pip install "fastapi[all]"
# 9. Freeze requirements: pip freeze > requirements.txt
# 10. Run from your terminal in the directory containing 'main.py':
#     uvicorn main:app --reload
#     (The --reload flag automatically restarts the server when code changes)
