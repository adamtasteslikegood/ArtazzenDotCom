# Project Overview

This project is a FastAPI and Jinja2 web application for an artwork gallery. It provides a public gallery to display artwork and an admin dashboard for uploading images, managing metadata, and configuring optional AI-powered metadata generation.

The application serves images from the `Static/images` directory. Each image has a corresponding JSON "sidecar" file with the same name (e.g., `my_art.jpg` and `my_art.json`). These sidecar files store the image's title, description, and other metadata.

The admin dashboard allows users to:
- Upload new images.
- Review and edit image metadata.
- Configure and use OpenAI's API to automatically generate titles and descriptions for images.

# Project Structure

-   `main.py`: The main FastAPI application file.
-   `templates/`: Contains the Jinja2 templates for the HTML pages.
    -   `index.html`: The main gallery page.
    -   `reviewAddedFiles.html`: The admin page for reviewing and editing new images.
    -   `previewImageText.html`: The page for previewing an image with its metadata.
-   `Static/`: Contains the static files (CSS, images, etc.).
    -   `css/`: Contains the CSS files for styling the application.
    -   `images/`: Contains the artwork images and their JSON sidecar files.
-   `requirements.txt`: The list of Python dependencies.
-   `GEMINI.md`: This file.

# Building and Running

To build and run the project, follow these steps:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/adamtasteslikegood/ArtazzenDotCom.git
    cd ArtazzenDotCom
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows, use: .\.venv\Scripts\activate
    ```

3.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the application:**
    ```bash
    uvicorn main:app --reload
    ```

The application will be available at `http://127.0.0.1:8000`. The admin dashboard is at `http://127.0.0.1:8000/admin`.

# Development Conventions

-   **Code Style:** The project follows the PEP 8 style guide with 4-space indentation and type hints.
-   **Logging:** Use the built-in `logging` module instead of `print` for debugging and informational messages.
-   **Asynchronous Code:** Keep FastAPI route handlers asynchronous and avoid blocking I/O operations.
-   **Testing:** The project uses `pytest` and `httpx` for testing. Tests should be placed in the `tests/` directory.
-   **Commits:** Commits should be small, imperative, and scoped (e.g., "Add admin metadata review").
-   **Pull Requests:** Document UI changes with screenshots and verification steps in pull requests.