import pytest
from fastapi.testclient import TestClient
import os
from main import app, IMAGES_DIR

@pytest.fixture(scope="function")
def client():
    """Create a TestClient instance for the app."""
    with TestClient(app) as c:
        yield c

def setup_function(function):
    """Create a dummy image file for testing."""
    if not IMAGES_DIR.exists():
        IMAGES_DIR.mkdir(parents=True)
    dummy_image_path = IMAGES_DIR / "test_image.jpg"
    if not dummy_image_path.exists():
        dummy_image_path.touch()
    
    # Create a dummy sidecar file
    dummy_sidecar_path = IMAGES_DIR / "test_image.json"
    if not dummy_sidecar_path.exists():
        with open(dummy_sidecar_path, "w") as f:
            f.write('{"title": "Test Image", "description": "A test image."}')

def teardown_function(function):
    """Remove dummy files after tests."""
    dummy_image_path = IMAGES_DIR / "test_image.jpg"
    if dummy_image_path.exists():
        os.remove(dummy_image_path)
    
    dummy_sidecar_path = IMAGES_DIR / "test_image.json"
    if dummy_sidecar_path.exists():
        os.remove(dummy_sidecar_path)

def test_read_root(client: TestClient):
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Artwork Gallery" in response.text

def test_artwork_detail(client: TestClient):
    """Test the artwork detail endpoint."""
    response = client.get("/artwork/test_image.jpg")
    assert response.status_code == 200
    assert "Test Image" in response.text
