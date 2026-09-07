"""Storage Service — manages blob storage for source documents and generated PDFs.

Based on SDD Section 8.1:
- Source content and generated PDFs stored in Blob Storage with tenant-scoped containers
- Access via short-lived SAS tokens, not public URLs
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from azure.storage.blob.aio import BlobServiceClient
from azure.storage.blob import (
    BlobSasPermissions,
    generate_blob_sas,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Manages Azure Blob Storage for documents and generated content."""

    def __init__(self) -> None:
        self._client: Optional[BlobServiceClient] = None

    async def get_client(self) -> BlobServiceClient:
        if self._client is None:
            self._client = BlobServiceClient.from_connection_string(
                settings.azure_storage_connection_string
            )
        return self._client

    async def upload_document(
        self,
        container_name: str,
        blob_name: str,
        data: bytes,
        overwrite: bool = True,
    ) -> str:
        """Upload a document to blob storage and return its URL."""
        logger.info("Uploading %s to container %s", blob_name, container_name)

        client = await self.get_client()
        container = client.get_container_client(container_name)

        await container.upload_blob(
            name=blob_name,
            data=data,
            overwrite=overwrite,
        )

        return f"https://{client.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

    async def download_document(
        self,
        container_name: str,
        blob_name: str,
    ) -> bytes:
        """Download a document from blob storage."""
        logger.info("Downloading %s from container %s", blob_name, container_name)

        client = await self.get_client()
        container = client.get_container_client(container_name)
        blob = container.get_blob_client(blob_name)

        return await blob.download_blob().readall()

    async def generate_sas_token(
        self,
        container_name: str,
        blob_name: str,
        expiry_hours: int = 1,
        permission: str = "r",
    ) -> str:
        """Generate a short-lived SAS token for accessing a blob.

        Based on SDD: access via short-lived SAS tokens, not public URLs.
        """
        from azure.storage.blob import BlobClient

        client = await self.get_client()
        blob_client = client.get_blob_client(container_name, blob_name)

        sas_token = generate_blob_sas(
            account_name=client.account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
        )

        return f"{blob_client.url}?{sas_token}"

    async def get_blob_url(
        self,
        container_name: str,
        blob_name: str,
        expiry_hours: int = 1,
    ) -> str:
        """Get a URL with SAS token for a blob."""
        sas_token = await self.generate_sas_token(
            container_name, blob_name, expiry_hours=expiry_hours
        )
        return sas_token

    async def close(self) -> None:
        if self._client:
            await self._client.close()