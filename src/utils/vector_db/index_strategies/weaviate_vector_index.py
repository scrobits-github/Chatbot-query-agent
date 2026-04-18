import weaviate
from weaviate.classes.init import Auth
from src.utils.vector_db.index_strategies.base import VectorIndexStrategy
from settings import WEAVIATE_URL, WEAVIATE_API_KEY

class WeaviateVectorIndex(VectorIndexStrategy):
    def __init__(self, embeddings):
        self.__embeddings = embeddings
        self.__collection_name = "DocumentChunks"
        
        # Initialize client
        if WEAVIATE_URL and "weaviate.cloud" in WEAVIATE_URL:
            # Cloud Connection
            self.client = weaviate.connect_to_weaviate_cloud(
                cluster_url=WEAVIATE_URL,
                auth_credentials=Auth.api_key(WEAVIATE_API_KEY)
            )
        elif WEAVIATE_API_KEY:
            # Local with Auth (e.g. Docker with API Key)
            self.client = weaviate.connect_to_local(
                host=WEAVIATE_URL or "localhost",
                auth_credentials=Auth.api_key(WEAVIATE_API_KEY)
            )
        else:
            # Assume local development or no auth
            self.client = weaviate.connect_to_local(host=WEAVIATE_URL or "localhost")

    def create_or_load_vector_index(self, markdown_text: str, chunker=None):
        """Creates a new Weaviate collection and uploads vectors."""
        # Ensure collection exists
        if not self.client.collections.exists(self.__collection_name):
            self.client.collections.create(
                name=self.__collection_name,
                vectorizer_config=None, # We provide our own vectors
            )
        
        collection = self.client.collections.get(self.__collection_name)
        
        # Use provided chunker
        if chunker is not None:
            chunk_outputs = chunker(markdown_text)
            if chunk_outputs and hasattr(chunk_outputs[0], "page_content"):
                chunk_texts = [c.page_content for c in chunk_outputs]
            else:
                chunk_texts = list(chunk_outputs)
        else:
            chunk_texts = [markdown_text] if markdown_text else []

        if not chunk_texts:
            return self

        # Embed documents
        vectors = self.__embeddings.embed_documents(chunk_texts)
        
        # Batch upload
        with collection.batch.dynamic() as batch:
            for i, (text, vector) in enumerate(zip(chunk_texts, vectors)):
                batch.add_object(
                    properties={
                        "chunk_text": text,
                        "chunk_id": i,
                        "source": "documents_folder"
                    },
                    vector=vector
                )
        
        print(f"Uploaded {len(chunk_texts)} chunks to Weaviate collection '{self.__collection_name}'")
        return self

    def semantic_search(self, embeded_query: list[float]) -> str:
        """Performs semantic search in Weaviate."""
        collection = self.client.collections.get(self.__collection_name)
        
        response = collection.query.near_vector(
            near_vector=embeded_query,
            limit=10,
            return_metadata=weaviate.classes.query.MetadataQuery(distance=True)
        )
        
        context_list = []
        for obj in response.objects:
            # Weaviate distance < threshold (smaller is better for cosine distance usually)
            # You might want to filter by distance here if needed
            text = obj.properties.get("chunk_text", "")
            if text:
                context_list.append(text)
        
        context = "\n\n---\n\n".join(context_list)
        return context or "No relevant context found for the question."

    def __del__(self):
        if hasattr(self, 'client'):
            self.client.close()
