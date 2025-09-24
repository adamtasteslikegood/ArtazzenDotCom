# Artwork Gallery Web Application

A FastAPI-based web application for displaying and managing an artwork gallery. This application allows you to showcase images with their associated metadata in a clean, organized web interface.

## Features

- Display artwork images in a responsive gallery layout
- Support for multiple image formats (JPG, PNG, GIF, WEBP, SVG, BMP, TIFF)
- Image metadata support including title and description
- Static file serving for images and CSS
- Templated HTML using Jinja2
- Logging system for debugging and monitoring
- Admin dashboard for uploading images, detecting new files, and editing metadata before publication
- Per-image JSON sidecars as the source of truth (no shared manifest)
- Startup validation/migration of sidecars against `ImageSidecar.schema.json`

## Prerequisites

- Python 3.4 or higher
- pip (Python package installer)

## Installation

1. Clone the repository:
    - GItHub https://github.com/adamtasteslikegood/ArtazzenDotCom.git

   ```Bash
    git clone [your-repository-url] 
    cd [repository-name]
   ```

2. Create and activate a virtual environment:

   ```Bash
    python -m venv .venv
    source .venv/bin/activate #(or .\venv\Scripts\activate on Windows)
   ```

3. Install required packages:

   ```bash
   pip install -r requirements.txt
   ```

## Project Structure
```
project_root/ 
├── main.py # Main application file
├── Static/ # Static files directory
│  ├── images/ # Directory for artwork images
│  └── css/ # CSS stylesheets
└── templates/ # HTML templates 
      └── index.html # Main gallery template
└── ImageSidecar.schema.json # JSON Schema for sidecar files
└── manage_sidecars.py # CLI to validate/migrate sidecars
```

## Data Model & Configuration

1. Place your artwork images in the `Static/images/` directory
2. Sidecar JSON: for each image `foo.jpg`, the app expects `foo.json` next to it. If absent, the app creates it at detection time with fields:
   - `title` (string), `description` (string), `reviewed` (boolean), `detected_at` (number)
3. Schema: sidecars are validated at server startup against `ImageSidecar.schema.json`. Missing fields are defaulted and simple types coerced.

## Running the Application

1. Make sure your virtual environment is activated
2. Run the application:
   ```bash
    uvicorn main:app --reload
   ```
   (The --reload flag automatically restarts the server when code changes)
3. Open your browser and navigate to `http://127.0.0.1:8000`

### Optional: AI Metadata Generation

- Set an API key to auto-generate missing `title`/`description` using OpenAI:

  ```bash
  export MY_OPENAI_API_KEY=sk-...              # preferred env var
  # or legacy name also supported:
  export My_OpenAI_APIKey=sk-...
  # Optional model override (default: gpt-4o-mini)
  export OPENAI_IMAGE_METADATA_MODEL=gpt-4o-mini
  ```

- The server will attempt generation when new/unreviewed images are detected and on the review page for an image.

## Usage

- Add images to the `Static/images/` directory
- (Optional) create corresponding JSON files for custom metadata
- If no JSON exists, the app will read embedded EXIF captions and titles
- Access the gallery through your web browser
- Images will be automatically displayed with their metadata

### Admin dashboard

- Navigate to `http://127.0.0.1:8000/admin` to open the administrative tools
- Drag-and-drop or browse to upload new artwork files (image formats or JSON sidecars)
- Provide an absolute server path to import images that already exist on disk
- Newly detected files appear in a review queue where you can inspect thumbnails and detected metadata
- Selecting **Review details** opens a form that lets you edit the title and description that will be saved to the JSON sidecar file
- Once metadata is saved, the entry is marked as `reviewed: true` and removed from the pending list

## Maintenance

- Validate/migrate all sidecars against the current schema at any time:

  ```bash
  python manage_sidecars.py validate
  ```

- Example API checks:

  ```bash
  curl http://127.0.0.1:8000/admin/api/new-files
  curl -F "files=@/path/to/image.jpg" http://127.0.0.1:8000/admin/upload
  ```

### AI metadata configuration

- Runtime AI settings persist in `ai_config.json` at the project root.
- Configure via the admin UI (Admin → AI Metadata Settings) or directly by editing `ai_config.json`.
- Startup defaults come from environment variables and are overridden by `ai_config.json` if present.

## Development

- The `--reload` flag enables auto-reload on code changes
- Logging is configured for debugging
- Templates can be modified in the `templates` directory
- Static files (CSS, images) are served from the `Static` directory on disk and mounted at `/static` in the application

## License

[Your chosen license]

## Authors

[Adam Schoen, Allison Lunn Gemini 2.5 and Claude 3.5 Sonnet 
## Acknowledgments

- FastAPI framework
- Jinja2 templating engine
- Pillow (PIL) for image processing
