from src.utils.vector_db.index_strategies.base import VectorIndexStrategy
from settings import PINECONE_API_KEY, PINECONE_INDEX_NAME
from pinecone import Pinecone

class PineconeVectorIndex(VectorIndexStrategy):
    def  __init__ (self, embeddings):
        self.__collection_name = PINECONE_INDEX_NAME
        self.__api_key = Pinecone(api_key=PINECONE_API_KEY)
        self.__embeddings = embeddings
        self.__collection = False

    def create_or_load_vector_index(self, markdown_text: str, chunker=None):
        if self.__collection:
            return self

        index = self.__api_key.Index(self.__collection_name)
        # Use provided chunker callable if supplied; it may return Documents or strings
        if chunker is not None:
            chunk_outputs = chunker(markdown_text)
            if chunk_outputs and hasattr(chunk_outputs[0], "page_content"):
                chunk_texts = [c.page_content for c in chunk_outputs]
            else:
                chunk_texts = list(chunk_outputs)
        else:
            # Fallback: no chunker provided; treat whole markdown as a single chunk
            chunk_texts = [markdown_text] if markdown_text else []
        if not chunk_texts:
            self.__collection = True
            return self

        # Embed documents using langchain's HuggingFaceEmbeddings
        vectors = self.__embeddings.embed_documents(chunk_texts)
        pinecone_vectors = []
        for i, (values, chunk_text) in enumerate(zip(vectors, chunk_texts)):
            pinecone_vectors.append({
                "id": f"chunk_{i}",
                "values": values,
                "metadata": {
                    "chunk_text": chunk_text,
                    "chunk_id": i,
                    "source": "documents_folder"
                }
            })

        # Upsert to Pinecone
        index.upsert(vectors=pinecone_vectors)
        print(f"Uploaded {len(pinecone_vectors)} chunks to Pinecone index '{self.__collection_name}'")
        self.__collection = True
        return self
    
    def semantic_search(self, embeded_query: list[float]) -> str:
        index = self.__api_key.Index(self.__collection_name)
        response = index.query(
            vector=embeded_query,
            top_k=50,
            include_metadata=True,
            score_threshold=0.3
        )
        if response.get("matches"):
            # Combine top 10 matches to get better context
            matches = response["matches"]
            context_list = []
            for match in matches[:10]:
                text = match["metadata"].get("chunk_text", "")
                if text:
                    context_list.append(text)
            
            context = "\n\n---\n\n".join(context_list)
            return context or "No relevant context found for the question."
        else:
            print("DEBUG: No matches found in Pinecone above threshold.")
            return "No relevant context found for the question."
