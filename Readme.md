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

For a containerized setup, you can use the provided `Dockerfile`.

### Building the Docker Image
```bash
docker build -t artazzen-gallery .
```

### Running the Docker Container
```bash
docker run -p 8000:8000 artazzen-gallery
```
The application will be accessible at `http://localhost:8000`.

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
For production, use a WSGI server like Gunicorn:
```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
```
**Note on Configuration:** For sensitive information like API keys, it is recommended to use environment variables instead of hardcoding them in the application.

## Error Handling
Error handling is implemented within `main.py` to ensure the application remains stable.
