"""GitHub API client for fetching PR diffs and posting review comments."""

import os
import re
from dataclasses import dataclass
from typing import Optional

import requests

# Files we never want to review (generated, lock files, binaries, etc.)
SKIP_PATTERNS = [
    r".*\.lock$",
    r".*package-lock\.json$",
    r".*yarn\.lock$",
    r".*poetry\.lock$",
    r".*\.min\.(js|css)$",
    r".*\.pb\.go$",
    r".*_generated\..*$",
    r".*\.snap$",
    r"dist/.*",
    r"build/.*",
    r".*\.svg$",
    r".*\.png$",
    r".*\.jpg$",
    r".*\.jpeg$",
    r".*\.gif$",
    r".*\.ico$",
    r".*\.woff.*$",
    r".*\.ttf$",
]

MAX_DIFF_CHARS_PER_FILE = 8_000  # Prevent any single file from blowing the context


@dataclass
class FileDiff:
    filename: str
    patch: str  # The raw unified diff hunk


@dataclass
class ReviewComment:
    path: str
    line: int  # Line number in the NEW file (right side of diff)
    body: str
    side: str = "RIGHT"


class GitHubClient:
    def __init__(self):
        self.token = os.environ["GITHUB_TOKEN"]
        self.repo = os.environ["REPO_NAME"]
        self.pr_number = int(os.environ["PR_NUMBER"])
        self.head_sha = os.environ["HEAD_SHA"]
        self.base_url = "https://api.github.com"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def get_pr_files(self) -> list[FileDiff]:
        """Fetch changed files and their diffs for the PR."""
        url = f"{self.base_url}/repos/{self.repo}/pulls/{self.pr_number}/files"
        response = self.session.get(url, params={"per_page": 100})
        response.raise_for_status()

        files: list[FileDiff] = []
        for f in response.json():
            filename = f["filename"]
            patch = f.get("patch", "")

            # Skip files we don't want to review
            if self._should_skip(filename):
                print(f"Skipping {filename} (matches skip pattern)")
                continue

            if not patch:
                continue  # Binary or new empty file

            # Truncate enormous diffs to avoid token overflows
            if len(patch) > MAX_DIFF_CHARS_PER_FILE:
                patch = patch[:MAX_DIFF_CHARS_PER_FILE] + "\n... [diff truncated]"

            files.append(FileDiff(filename=filename, patch=patch))

        return files

    def post_review(self, comments: list[ReviewComment], summary: str) -> None:
        """Post an inline review with all comments in a single API call."""
        if not comments:
            self._post_summary_comment(summary or "No issues found. LGTM!")
            return

        url = f"{self.base_url}/repos/{self.repo}/pulls/{self.pr_number}/reviews"

        payload = {
            "commit_id": self.head_sha,
            "body": summary,
            "event": "COMMENT",
            "comments": [
                {
                    "path": c.path,
                    "line": c.line,
                    "side": c.side,
                    "body": c.body,
                }
                for c in comments
            ],
        }

        response = self.session.post(url, json=payload)

        if response.status_code == 422:
            # Unprocessable — likely line numbers don't match diff.
            # Fall back: post each comment individually, skip failed ones.
            print("Batch review failed (422). Falling back to individual comments.")
            self._post_comments_individually(comments, summary)
        else:
            response.raise_for_status()
            print(f"Posted review with {len(comments)} inline comment(s).")

    def _post_comments_individually(
        self, comments: list[ReviewComment], summary: str
    ) -> None:
        """Post a general summary comment, then try each inline comment one by one."""
        self._post_summary_comment(summary)

        url = (
            f"{self.base_url}/repos/{self.repo}/pulls/{self.pr_number}/comments"
        )
        posted = 0
        for c in comments:
            payload = {
                "body": c.body,
                "commit_id": self.head_sha,
                "path": c.path,
                "line": c.line,
                "side": c.side,
            }
            r = self.session.post(url, json=payload)
            if r.status_code == 201:
                posted += 1
            else:
                print(
                    f"Could not post comment on {c.path}:{c.line} — {r.status_code}"
                )

        print(f"Posted {posted}/{len(comments)} individual inline comments.")

    def _post_summary_comment(self, body: str) -> None:
        """Post a plain PR comment (not inline)."""
        url = f"{self.base_url}/repos/{self.repo}/issues/{self.pr_number}/comments"
        response = self.session.post(url, json={"body": body})
        response.raise_for_status()

    @staticmethod
    def _should_skip(filename: str) -> bool:
        return any(re.match(p, filename) for p in SKIP_PATTERNS)
