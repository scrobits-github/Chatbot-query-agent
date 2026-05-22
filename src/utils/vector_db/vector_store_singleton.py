from src.utils.vector_db.loader_strategies.base import DocumentLoaderStrategy
from src.utils.vector_db.index_strategies.base import VectorIndexStrategy
from langchain_text_splitters import RecursiveCharacterTextSplitter
from settings import BASE_DIR
DOCUMENTS_FOLDER = BASE_DIR / "documents"

class VectorStoreSingleton():
    _instance = None

    vector_store = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(VectorStoreSingleton, cls).__new__(cls)
        return cls._instance

    def __init__(self, embeddings_model, document_loader_strategy: DocumentLoaderStrategy, vector_index_strategy: VectorIndexStrategy):
        if not hasattr(self, '_initialized'):
            self.embeddings_model = embeddings_model
            self.document_loader_strategy = document_loader_strategy
            self.vector_index_strategy = vector_index_strategy
            self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            def character_chunker(markdown_text: str):
                return self.text_splitter.create_documents([markdown_text])
            self.chunker = character_chunker
            self._initialized = True 

    def _build_vectorstore(self):
        """Orchestrates the document loading and vector store creation for all files in the documents folder."""
        if self.vector_store is None:
            print("--- Building Vector Store ---")
            
            # Direct cloud loading: skip heavy parsing if index already exists
            if hasattr(self.vector_index_strategy, "has_existing_vectors") and self.vector_index_strategy.has_existing_vectors():
                print("Pinecone index already contains vectors. Loading cloud index instantly!")
                self.vector_store = self.vector_index_strategy.create_or_load_vector_index("")
                print("--- Vector Store Loaded from Cloud Instantly ---")
                return self.vector_store

            all_markdown = ""
            # Search for PDF, DOCX, DOC, TXT, and MD files
            pdf_files = list(DOCUMENTS_FOLDER.glob("*.pdf"))
            docx_files = list(DOCUMENTS_FOLDER.glob("*.docx"))
            doc_files = list(DOCUMENTS_FOLDER.glob("*.doc"))
            txt_files = list(DOCUMENTS_FOLDER.glob("*.txt"))
            md_files = list(DOCUMENTS_FOLDER.glob("*.md"))
            all_document_files = pdf_files + docx_files + doc_files + txt_files + md_files
            
            if not all_document_files:
                print(f"Warning: No supported document files (.pdf, .docx, .doc, .txt, .md) found in {DOCUMENTS_FOLDER}")
                return None

            for doc_path in all_document_files:
                print(f"Indexing: {doc_path.name}")
                try:
                    all_markdown += self.document_loader_strategy.load_documents(path=doc_path) + "\n\n"
                except Exception as e:
                    print(f"Error loading {doc_path.name}: {e}")

            if not all_markdown.strip():
                print("No content extracted from documents.")
                return None

            # Build or load the backing vector index using provided embeddings
            self.vector_store = self.vector_index_strategy.create_or_load_vector_index(
                all_markdown,
                chunker=self.chunker
            )
            print("--- Vector Store Built Successfully ---")
        return self.vector_store


    def query(self, query_text: str):
        # HuggingFaceEmbeddings from langchain exposes embed_query for single strings
        query_embedding = self.embeddings_model.embed_query(query_text)
        """The main query method."""
        if self.vector_store is None:
            self._build_vectorstore()
        results = self.vector_index_strategy.semantic_search(embeded_query=query_embedding)
        return results
