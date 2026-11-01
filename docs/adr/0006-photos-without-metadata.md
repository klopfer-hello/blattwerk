# 0006 Photos are re-encoded without metadata and stay on the host
- Status: accepted
- Date: 2026-11-01

## Context
The plant doctor and plant ID take photos from phones. Phone photos carry GPS position and device data, can be
large, and an upload route is the one place where the API accepts something other than small JSON.

## Decision
The browser shrinks photos to at most 1600 px (canvas, which drops metadata). The server accepts exactly one
non-JSON route, `POST /api/photos` (JPEG/PNG/WebP, max 8 MB, same-origin), verifies the image with Pillow, refuses
decompression bombs and stores a fresh JPEG without EXIF/GPS in PostgreSQL. Photos go to Claude only for the
answer they belong to; unsent uploads are limited per day and purged after a day.

## Alternatives
- Trusting the client to strip metadata: a modified client or another app would not.
- Files on disk: a second store for backups and permissions.

## Consequences
- One code path for every photo; backups contain them with the rest of the data.
- Large originals never reach the database.
