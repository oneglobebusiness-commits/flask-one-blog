import os
import uuid

from flask import current_app


def blog_dir():
    path = os.path.join(current_app.config["UPLOAD_DIR"], "blogs")
    os.makedirs(path, exist_ok=True)
    return path


def save_image(data, extension="png"):
    file_name = f"{uuid.uuid4()}.{extension}"
    path = os.path.join(blog_dir(), file_name)
    with open(path, "wb") as handle:
        handle.write(data)
    return {
        "provider": "local",
        "fileName": file_name,
        "localPath": path,
        "url": f"/uploads/blogs/{file_name}",
        "mimeType": f"image/{extension}",
        "size": len(data),
    }


def find_local_image(hero):
    """Return an existing image path. Old records may hold a path from another server."""
    if not hero:
        return None
    candidates = []
    if hero.get("fileName"):
        candidates.append(os.path.join(blog_dir(), os.path.basename(hero["fileName"])))
    if hero.get("localPath"):
        candidates.append(hero["localPath"])
    return next((path for path in candidates if os.path.isfile(path)), None)
