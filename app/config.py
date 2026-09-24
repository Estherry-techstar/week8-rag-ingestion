from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings. Any value can be overridden in a .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Upload safety (step 2) ---
    max_upload_mb: int = 10
    allowed_types: set[str] = {"pdf", "txt", "md"}
    upload_dir: str = "data/uploads"

    # --- Chunking (steps 4-5) ---
    chunk_tokens: int = 400
    chunk_overlap_tokens: int = 60
    tokenizer_encoding: str = "cl100k_base"

    # --- Embeddings (step 6) ---
    embedding_provider: str = "local"                     # "local" or "openai"
    local_embedding_model: str = "all-MiniLM-L6-v2"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_api_key: str | None = None

    # --- Vector store (step 7) ---
    chroma_dir: str = "chroma_db"
    collection_name: str = "documents"


settings = Settings()