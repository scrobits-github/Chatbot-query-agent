from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import os
from pathlib import Path

# Create router
upload_router = APIRouter()

# Get documents directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DOCUMENTS_DIR = BASE_DIR / "documents"
ALLOWED_EXTENSIONS = {".pdf", ".docx"}

@upload_router.post("/upload")
async def upload_file(
    file: UploadFile = File(...)
):
    """Upload a PDF or DOCX file and save it to the documents folder."""
    
    # Check if a file was provided
    if not file.filename:
        return JSONResponse(status_code=400, content={"message": "No file provided"})

    # Check file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400, 
            content={"message": f"Unsupported file type: {file_ext}. Only PDF and DOCX files are allowed."}
        )

    try:
        # 2. Ensure directory exists
        os.makedirs(DOCUMENTS_DIR, exist_ok=True)
        
        # 3. Save file
        file_path = DOCUMENTS_DIR / file.filename
        with open(file_path, "wb") as f:
            f.write(await file.read())
            
        return {
            "message": f"Successfully uploaded {file.filename}",
            "path": str(file_path)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")