# Artwork Gallery Web Application

A FastAPI-based web application for displaying and managing an artwork gallery. This application allows you to showcase images with their associated metadata in a clean, organized web interface.

## Features

- Display artwork images in a responsive gallery layout
- Support for multiple image formats (JPG, PNG, GIF, WEBP, SVG, BMP, TIFF)
- Image metadata support including title, description, and technical details
- Static file serving for images and CSS
- Templated HTML using Jinja2
- Logging system for debugging and monitoring

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
    pip install "fastapi[all]" Pillow 
    pip freeze > requirements.txt

   ```

## Project Structure
```graphql
project_root/ 
├── main.py # Main application file
├── static/ # Static files directory 
│  ├── images/ # Directory for artwork images 
│  └── css/ # CSS stylesheets 
│  └── css/ # CSS stylesheets
└── templates/ # HTML templates 
      └── index.html # Main gallery template
```

## Configuration

1. Place your artwork images in the `static/images/` directory
2. (Optional) Create JSON metadata files for images with the same name as the image file:
   ```
   static/images/artwork1.jpg
   static/images/artwork1.json
   ```

## Running the Application

1. Make sure your virtual environment is activated
2. Run the application:
   ```bash
    uvicorn main:app --reload
   ```
   (The --reload flag automatically restarts the server when code changes)
3. Open your browser and navigate to `http://127.0.0.1:8000`

## Usage

- Add images to the `static/images/` directory
- Create corresponding JSON files for custom metadata (optional)
- Access the gallery through your web browser
- Images will be automatically displayed with their metadata

## Development

- The `--reload` flag enables auto-reload on code changes
- Logging is configured for debugging
- Templates can be modified in the `templates` directory
- Static files (CSS, images) are served from the `static` directory

## License

[Your chosen license]

## Authors

[Adam Schoen, Allison Lunn Gemini 2.5 and Claude 3.5 Sonnet 
## Acknowledgments

- FastAPI framework
- Jinja2 templating engine
- Pillow (PIL) for image processing