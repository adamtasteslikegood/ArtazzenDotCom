from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import json
from typing import List

app = FastAPI()

# Create directories if they don't exist
os.makedirs("static/images", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("static/css", exist_ok=True)


app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

IMAGE_DIR = "static/images"

def get_artwork():
    artwork = []
    for filename in os.listdir(IMAGE_DIR):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            json_path = os.path.join(IMAGE_DIR, f"{os.path.splitext(filename)[0]}.json")
            if os.path.exists(json_path):
                with open(json_path, 'r') as f:
                    metadata = json.load(f)
            else:
                metadata = {"title": "Untitled", "description": "", "tags": []}
            
            artwork.append({
                "filename": filename,
                "url": f"/static/images/{filename}",
                "title": metadata.get("title", "Untitled"),
                "description": metadata.get("description", ""),
                "tags": metadata.get("tags", ["tag1", "tag2", "tag3"]) # Placeholder tags
            })
    return artwork

@app.get("/artwork/{filename}", response_class=HTMLResponse)
async def artwork_highlight(request: Request, filename: str):
    artwork = None
    for art in get_artwork():
        if art['filename'] == filename:
            artwork = art
            break
    
    if not artwork:
        return HTMLResponse(content="Artwork not found", status_code=404)
        
    return templates.TemplateResponse("artwork_highlight.html", {"request": request, "artwork": artwork})


@app.get("/", response_class=HTMLResponse)
async def gallery(request: Request):
    artwork = get_artwork()
    return templates.TemplateResponse("index.html", {"request": request, "artwork_files": artwork})

@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request):
    artwork = get_artwork()
    return templates.TemplateResponse("admin.html", {"request": request, "artwork_files": artwork})

@app.post("/admin/upload")
async def upload_image(files: List[UploadFile] = File(...)):
    for file in files:
        file_path = os.path.join(IMAGE_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
        
        # Create a default json sidecar
        json_path = os.path.join(IMAGE_DIR, f"{os.path.splitext(file.filename)[0]}.json")
        if not os.path.exists(json_path):
            with open(json_path, 'w') as f:
                json.dump({"title": "Untitled", "description": ""}, f, indent=4)

    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/update-metadata/{filename}")
async def update_metadata(filename: str, title: str = Form(...), description: str = Form(...)):
    json_path = os.path.join(IMAGE_DIR, f"{os.path.splitext(filename)[0]}.json")
    
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            metadata = json.load(f)
    else:
        metadata = {}
        
    metadata['title'] = title
    metadata['description'] = description
    
    with open(json_path, 'w') as f:
        json.dump(metadata, f, indent=4)
        
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete/{filename}")
async def delete_artwork(filename: str):
    # Delete image
    image_path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(image_path):
        os.remove(image_path)
        
    # Delete sidecar json
    json_path = os.path.join(IMAGE_DIR, f"{os.path.splitext(filename)[0]}.json")
    if os.path.exists(json_path):
        os.remove(json_path)
        
    return RedirectResponse(url="/admin", status_code=303)
