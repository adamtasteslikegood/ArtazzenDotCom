"""Thin wrapper over the S3-compatible Railway bucket.

All keys pass through :meth:`Storage.key`, which applies the optional
``UPSCALER_BUCKET_PREFIX`` so a local run can share the production bucket
without touching production objects.
"""

from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from upscaler.config import Settings


class Storage:
    def __init__(self, client: Any, bucket: str, prefix: str = "") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix

    @classmethod
    def from_settings(cls, settings: Settings) -> Storage:
        client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint or None,
            aws_access_key_id=settings.access_key_id or None,
            aws_secret_access_key=settings.secret_access_key or None,
            region_name=settings.region,
            # Railway buckets use virtual-hosted-style URLs.
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                # boto3 >= 1.36 sends CRC checksums on every upload by
                # default; some S3-compatible stores reject them. Only send
                # them when an operation requires one.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        return cls(client, settings.bucket, settings.bucket_prefix)

    def key(self, name: str) -> str:
        return f"{self.prefix}{name}"

    def put_bytes(self, name: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=self.key(name), Body=data, ContentType=content_type
        )

    def put_json(self, name: str, obj: Any) -> None:
        self.put_bytes(
            name, json.dumps(obj, indent=2).encode("utf-8"), "application/json"
        )

    def get_bytes(self, name: str) -> bytes | None:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=self.key(name))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
        return resp["Body"].read()

    def get_json(self, name: str) -> Any | None:
        data = self.get_bytes(name)
        return None if data is None else json.loads(data)

    def list_names(self, prefix: str) -> list[str]:
        """Every object name under ``prefix`` (without the bucket prefix)."""
        names: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.key(prefix)):
            for obj in page.get("Contents", []):
                names.append(obj["Key"][len(self.prefix) :])
        return names

    def delete(self, name: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self.key(name))

    def presign_get(self, name: str, expires: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self.key(name)},
            ExpiresIn=expires,
        )
