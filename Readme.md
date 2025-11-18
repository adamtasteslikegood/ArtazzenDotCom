# Artwork Gallery Web Application

ArtazzenDotCom is a FastAPI + Jinja2 project for curating artwork with rich metadata. Images live on disk with JSON “sidecars” that describe each piece, while the app provides both a public gallery and an admin workflow for uploads, reviews, and optional AI assistance.

## For Beginners: Getting Started with a Full-Stack Application

If you're new to web development or the command line, this section will guide you through the setup process step-by-step.

### What is a "Full-Stack" Application?

A full-stack application includes both a **frontend** (what you see in your browser) and a **backend** (the server-side logic that handles data and requests). This project uses:
- **FastAPI:** A Python framework for building the backend API.
- **Jinja2:** A templating engine to create the HTML pages for the frontend.
- **Uvicorn:** A server that runs the FastAPI application.

### Understanding the Command Line

The command line (or "terminal") is a text-based interface for interacting with your computer. We'll use it to set up and run the project.

### Step-by-Step Instructions

1.  **Cloning the Repository:**
    `git clone <repo_url>` downloads a copy of the project from a Git repository (like GitHub) to your local machine.

2.  **Navigating into the Project Directory:**
    `cd <repo_name>` changes the current directory to the newly cloned project folder.

3.  **Creating a Virtual Environment:**
    `python -m venv .venv` creates an isolated environment for the project's Python dependencies. This prevents conflicts with other Python projects on your system.

4.  **Activating the Virtual Environment:**
    `source .venv/bin/activate` (on macOS/Linux) or `.\.venv\Scripts\activate` (on Windows) activates the virtual environment. You'll know it's active when you see `(.venv)` at the beginning of your command prompt.

5.  **Installing Dependencies:**
    `pip install -r requirements.txt` reads the `requirements.txt` file and installs all the necessary Python libraries for the project.

6.  **Running the Application:**
    `uvicorn main:app --reload` starts the web server. The `--reload` flag tells the server to automatically restart when you make changes to the code.

## Build and Run

### Prerequisites
- Python 3.13 (recommended) or 3.10+

### Setup
1. Create virtual environment:
   ```bash
   python -m venv .venv
   ```
2. Activate virtual environment:
   - macOS/Linux:
     ```bash
     source .venv/bin/activate
     ```
   - Windows:
     ```bash
     .\.venv\Scripts\activate
     ```

### Dependencies
Install project dependencies (after activating the venv):
```bash
pip install -r requirements.txt
```

### Execution
Run the FastAPI application:
```bash
uvicorn main:app --reload
```

### Access
- Application: `http://127.0.0.1:8000`
- Admin Dashboard: `http://127.0.0.1:8000/admin`

## Quick Start (Experienced Users)
```bash
git clone <repo_url> && cd <repo_name> && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn main:app --reload
```

## Docker

For a containerized setup, you can use the provided `Dockerfile`, which runs the app with `uvicorn` directly (no Gunicorn wrapper) using `uvloop` and `httptools` when available.

### Building the Docker Image
```bash
docker build -t artazzen-gallery .
```

### Running the Docker Container
```bash
docker run -p 8000:8000 artazzen-gallery
```
The application will be accessible at `http://localhost:8000`.

### Docker Compose + Caddy (reverse proxy)
If you use the provided `docker-compose.yml` to run the app behind Caddy with TLS, pre-create the external image volume and then start the stack:
```bash
docker volume create artazzen_images
docker compose up -d
```
The `artazzen_images` volume keeps your uploaded files and sidecars outside the container lifecycle; `docker compose down` will not remove it.

Optional: seed the empty volume with your local images/sidecars before the first deploy:
```bash
docker run --rm \
  -v artazzen_images:/data \
  -v "$(pwd)/Static/images:/seed:ro" \
  busybox sh -c "mkdir -p /data && cp -r /seed/. /data/"
```
This copies everything from `Static/images` into the Docker volume; future compose runs will reuse that data.

## Testing
Run tests using pytest:
```bash
pytest
```
**Note:** If `pytest` is not found, ensure it is included in your `requirements.txt` file and that your virtual environment is active.

## Project Structure
- `main.py`: FastAPI application entry point.
- `templates/`: Jinja2 HTML templates.
- `Static/`: Static assets (images, CSS).
  - `Static/images/`: Artwork images and their JSON sidecars.
  - `Static/css/`: Stylesheets.
- `requirements.txt`: Project dependencies.

## Contribution Guidelines
- Adhere to PEP 8 style guide.
- Follow commit conventions (imperative, scoped messages).

## License
This project is licensed under the MIT License. See the `LICENSE` file for details.

## Deployment Considerations
For production, run `uvicorn` directly with multiple workers and `uvloop`:
```bash
uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --loop uvloop \
  --http httptools \
  --workers 4
```
When using the Docker image, you can tune concurrency via environment variables:
```bash
docker run -p 8000:8000 \
  -e PORT=8000 \
  -e UVICORN_WORKERS=4 \
  artazzen-gallery
```
**Note on Configuration:** For sensitive information like API keys, it is recommended to use environment variables instead of hardcoding them in the application or image.

## Release Checklist (Pre‑deploy)

Before cutting a release or updating your production container:

- **Configuration**
  - Set `MY_OPENAI_API_KEY` (or legacy `My_OpenAI_APIKey`) in the environment for AI enrichment.
  - Review `ai_config.json` / `/admin` → AI settings (model, temperature, max tokens, startup enrichment).
  - Review `advanced_config.json` / `/admin/advanced` (logging levels, default author/copyright).
- **Data & sidecars**
  - Ensure `Static/images/` and sidecar JSONs are backed up (or mounted as a volume in Docker).
  - Optionally run `python manage_sidecars.py validate` to check sidecars against `ImageSidecar.schema.json`.
- **Build & run**
  - Build the image: `docker build -t artazzen-gallery .`
  - Run a staging container:
    ```bash
    docker run --rm -p 8000:8000 \
      -e PORT=8000 \
      -e UVICORN_WORKERS=4 \
      -e MY_OPENAI_API_KEY=... \
      artazzen-gallery
    ```
- **Smoke tests**
  - Visit `/` (public gallery) and `/admin` (dashboard).
  - Exercise: upload a few images, verify cards appear in “Needs review”, sorting/filtering work, and AI regeneration behaves as expected.
  - Confirm you can edit metadata, Accept, Regenerate, and Delete images without errors in the logs.

## Error Handling
Error handling is implemented within `main.py` to ensure the application remains stable.
