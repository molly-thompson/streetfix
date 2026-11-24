"""Deliver verified report photos without exposing provider URLs."""

from collections.abc import Iterator
from typing import BinaryIO
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import cloudinary.utils
from cloudinary.exceptions import Error as CloudinaryError
from django.core.exceptions import ValidationError

from intake.models import ReportPhotoSlot
from intake.services.photos import fetch_verified_photo


class PhotoUnavailableError(Exception):
    """A photo cannot be safely retrieved from the provider."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class PhotoStream:
    """Bound a provider stream to the verified original asset size."""

    def __init__(self, source: BinaryIO, size: int) -> None:
        """Retain the upstream stream and verified byte limit."""
        self.source = source
        self.size = size

    def __iter__(self) -> Iterator[bytes]:
        """Yield at most the verified number of bytes."""
        remaining = self.size
        while remaining:
            try:
                data = self.source.read(min(64 * 1024, remaining))
            except OSError:
                raise PhotoUnavailableError from None
            if not data:
                break
            data = data[:remaining]
            remaining -= len(data)
            yield data

    def close(self) -> None:
        """Close the provider connection after streaming or disconnect."""
        self.source.close()


def open_report_photo(slot: ReportPhotoSlot) -> PhotoStream:
    """Open only the same authenticated asset and version that was verified."""
    if (
        slot.asset_id is None
        or slot.version is None
        or slot.size_bytes is None
        or not slot.format
    ):
        raise PhotoUnavailableError
    try:
        current = fetch_verified_photo(slot.public_id)
        if (
            current.asset_id != slot.asset_id
            or current.version != slot.version
            or current.format != slot.format
            or current.size_bytes != slot.size_bytes
        ):
            raise PhotoUnavailableError
        url, _ = cloudinary.utils.cloudinary_url(
            slot.public_id,
            resource_type="image",
            type="authenticated",
            secure=True,
            sign_url=True,
            version=slot.version,
            format=slot.format,
        )
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.hostname != "res.cloudinary.com"
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
        ):
            raise PhotoUnavailableError
        request = Request(url, headers={"Accept": "image/*"})  # noqa: S310
        response = build_opener(_NoRedirect()).open(request, timeout=15)
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                if int(length) != slot.size_bytes:
                    raise PhotoUnavailableError
            except ValueError, PhotoUnavailableError:
                response.close()
                raise PhotoUnavailableError from None
        return PhotoStream(response, slot.size_bytes)
    except CloudinaryError, ValidationError, URLError, OSError, TypeError, ValueError:
        raise PhotoUnavailableError from None
