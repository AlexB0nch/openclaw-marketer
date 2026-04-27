"""PostgreSQL backup to S3.

Sprint 7: nightly pg_dump + upload to S3. Silently skips if AWS not configured.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import logging
import os
import tempfile
from datetime import datetime

from app.config import Settings

logger = logging.getLogger(__name__)


class BackupManager:
    """Run pg_dump and upload result to S3."""

    async def run_backup(self, settings: Settings) -> str:
        """Run pg_dump → gzip → S3 upload. Returns S3 key, or "" if skipped."""
        if not settings.aws_access_key_id or not settings.aws_s3_backup_bucket:
            logger.warning("Backup skipped: AWS credentials not configured")
            return ""

        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        date_part = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"backups/{date_part}/{ts}.sql.gz"

        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            env = os.environ.copy()
            env["PGPASSWORD"] = settings.postgres_password

            proc = await asyncio.create_subprocess_exec(
                "pg_dump",
                "-h",
                settings.postgres_host,
                "-p",
                str(settings.postgres_port),
                "-U",
                settings.postgres_user,
                "-d",
                settings.postgres_db,
                "--no-owner",
                "--no-acl",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"pg_dump failed (rc={proc.returncode}): {stderr.decode(errors='replace')}"
                )

            with gzip.open(tmp_path, "wb") as gz:
                gz.write(stdout)

            try:
                import aioboto3  # type: ignore
            except ImportError:
                logger.warning("aioboto3 not installed; backup file written locally only")
                return ""

            session = aioboto3.Session(
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )
            async with session.client("s3") as s3:
                with open(tmp_path, "rb") as fp:
                    await s3.put_object(
                        Bucket=settings.aws_s3_backup_bucket,
                        Key=key,
                        Body=fp.read(),
                    )

            logger.info("Backup uploaded to s3://%s/%s", settings.aws_s3_backup_bucket, key)
            return key
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
