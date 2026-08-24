from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RagDocument(Base):
    """A catalog row for one piece of workspace knowledge (RAG).

    This is only the CATALOG: the row records what was ingested (title, kind,
    identity hash, how many chunks it produced) so an admin can list and delete
    it. The retrievable text lives as chunks in the workspace's ChromaDB
    collection ("{workspace_slug}__rag_kb"), keyed back here by `rag_document_id`.
    Deleting the row must also delete those chunks — see rag_admin_service.

    `sha` is the sha256 of the whitespace-normalised extracted text, reused from
    services/file_text.py semantics. It is the identity: re-adding the same
    document (same words) is a replace, not a duplicate — hence the
    (workspace_id, sha) unique constraint.
    """

    __tablename__ = "rag_documents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha", name="uq_rag_workspace_sha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # Human-facing name shown in the dashboard list.
    title: Mapped[str] = mapped_column(String, nullable=False)
    # What the content is: text | pdf | docx | markdown | url | image.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # Where it came from: paste | upload | url | ocr.
    source: Mapped[str] = mapped_column(String, nullable=False)
    # Original filename or URL, for display/debugging. Null for pasted text.
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    # sha256 of the normalised extracted text — the document's identity.
    sha: Mapped[str] = mapped_column(String, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Size in bytes of the raw input as the admin gave it to us: the pasted
    # text's UTF-8 encoding, the uploaded file's bytes, or the fetched page's
    # bytes. This is what the dashboard shows as "file size" - char_count is
    # extracted-text length, which is not the same number for a PDF/DOCX.
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Count of chunks actually indexed in Chroma right now - only updated when
    # ingestion FINISHES. While status="processing" this still reflects the
    # previous version (0 for a brand-new document), never the in-flight count.
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # processing | ready | failed. A document is safe to ground answers with
    # only once "ready" - see rag_admin_service.run_ingest.
    status: Mapped[str] = mapped_column(String, nullable=False, default="ready", server_default="ready")
    # Chunks embedded so far / total chunks to embed, for the in-flight job.
    # Embedding is the only ingestion phase whose cost scales with chunk count,
    # so it is the one honest unit of progress - see docs/... note in rag_service.
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship(  # noqa: F821
        "Workspace", back_populates="rag_documents"
    )
