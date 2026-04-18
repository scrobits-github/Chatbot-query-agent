from src.utils.vector_db.loader_strategies.base import DocumentLoaderStrategy
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
import os

class LocalLoader(DocumentLoaderStrategy):
    def load_documents(self, path):
        file_ext = os.path.splitext(str(path))[1].lower()
        
        if file_ext == ".pdf":
            # Use PyPDFLoader for PDF files
            loader = PyPDFLoader(str(path))
            pages = loader.load()
            return "\n".join([page.page_content for page in pages])
        
        elif file_ext == ".docx":
            # Use Docx2txtLoader for Word files
            loader = Docx2txtLoader(str(path))
            pages = loader.load()
            return "\n".join([page.page_content for page in pages])
        
        else:
            raise ValueError(f"Unsupported file extension: {file_ext}")

if __name__ == "__main__":
    loader = LocalLoader()
    # Replace with a valid local path for testing
    # loader.load_documents(path="documents/MIREMS.pdf")
