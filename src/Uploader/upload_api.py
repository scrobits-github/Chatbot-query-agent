from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import os
from pathlib import Path

# Create router
upload_router = APIRouter()

# Get documents directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DOCUMENTS_DIR = BASE_DIR / "documents"
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

@upload_router.post("/upload")
async def upload_file(
    file: UploadFile = File(...)
):
    """Upload a single PDF, DOCX, or DOC file."""
    return await save_file(file)

@upload_router.post("/upload-multiple")
async def upload_multiple_files(
    files: list[UploadFile] = File(...)
):
    """Upload multiple PDF, DOCX, or DOC files."""
    results = []
    for file in files:
        try:
            res = await save_file(file)
            results.append(res)
        except HTTPException as e:
            results.append({"filename": file.filename, "error": e.detail})
        except Exception as e:
            results.append({"filename": file.filename, "error": str(e)})
    
    return {"results": results}

async def save_file(file: UploadFile):
    # Check if a file was provided
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Check file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type: {file_ext}. Only PDF, DOCX, and DOC files are allowed."
        )

    try:
        # Ensure directory exists
        os.makedirs(DOCUMENTS_DIR, exist_ok=True)
        
        # Save file
        file_path = DOCUMENTS_DIR / file.filename
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
            
        return {
            "filename": file.filename,
            "message": "Successfully uploaded",
            "path": str(file_path)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed for {file.filename}: {str(e)}")