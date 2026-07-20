"""GitHub API client — fetch diffs, file contents, and post reviews."""

from __future__ import annotations

import base64

import httpx

GITHUB_API_URL = "https://api.github.com"
PER_PAGE = 100


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def fetch_pr_files(owner: str, repo: str, pull_number: int, token: str) -> list[dict]:
    """List the files changed in a pull request (``GET /pulls/{pr}/files``), paginated.

    Each entry includes ``filename``, ``status``, and a unified-diff ``patch``
    fragment — GitHub omits ``patch`` for binary files and files whose diff
    exceeds its internal size limit.
    """
    files: list[dict] = []
    page = 1

    async with httpx.AsyncClient(base_url=GITHUB_API_URL, headers=_auth_headers(token)) as client:
        while True:
            response = await client.get(
                f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
                params={"per_page": PER_PAGE, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            files.extend(batch)

            if len(batch) < PER_PAGE:
                break
            page += 1

    return files


async def fetch_diff(owner: str, repo: str, pull_number: int, token: str) -> str:
    """Retrieve the unified diff for a pull request.

    Built by aggregating the per-file ``patch`` fragments from
    ``GET /pulls/{pr}/files`` rather than the ``.diff`` media type, so binary
    and oversized files (no ``patch`` present) are silently skipped.
    """
    files = await fetch_pr_files(owner, repo, pull_number, token)

    parts = []
    for file in files:
        patch = file.get("patch")
        if patch is None:
            continue
        parts.append(f"diff --git a/{file['filename']} b/{file['filename']}\n{patch}")

    return "\n".join(parts)


async def fetch_file_content(owner: str, repo: str, path: str, ref: str, token: str) -> str:
    """Retrieve the full content of a file at a specific commit sha/ref.

    Uses ``GET /repos/{owner}/{repo}/contents/{path}?ref={ref}``, which
    base64-encodes file contents. Raises via ``response.raise_for_status()``
    if the file doesn't exist at that ref; GitHub omits ``content`` for files
    over ~1MB (a different endpoint — the Git Blobs API — is required there).
    """
    async with httpx.AsyncClient(base_url=GITHUB_API_URL, headers=_auth_headers(token)) as client:
        response = await client.get(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        response.raise_for_status()
        data = response.json()

    return base64.b64decode(data["content"]).decode("utf-8")


async def get_readme(owner: str, repo: str, ref: str, token: str) -> str | None:
    """Retrieve the root ``README.md`` at a specific commit ref, or ``None`` if it doesn't exist.

    Uses the same contents API as ``fetch_file_content``, but treats a 404
    (no README at this ref) as a normal, expected outcome rather than an error.
    """
    async with httpx.AsyncClient(base_url=GITHUB_API_URL, headers=_auth_headers(token)) as client:
        response = await client.get(
            f"/repos/{owner}/{repo}/contents/README.md",
            params={"ref": ref},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()

    return base64.b64decode(data["content"]).decode("utf-8")


async def post_review(owner: str, repo: str, pull_number: int, token: str, review_payload: dict) -> dict:
    """Submit a pull request review with inline comments (``POST /pulls/{pr}/reviews``).

    GitHub's review API has no update-in-place endpoint for a review's
    comments/verdict — each call creates a new review. Re-running the
    pipeline on the same PR will post an additional review rather than
    replacing the previous one.
    """
    async with httpx.AsyncClient(base_url=GITHUB_API_URL, headers=_auth_headers(token)) as client:
        response = await client.post(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            json=review_payload,
        )
        response.raise_for_status()
        return response.json()
