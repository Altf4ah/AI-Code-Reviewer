"""Claude API client for code review analysis."""

import json
import os
from dataclasses import dataclass

import anthropic

from reviewer.prompts import SYSTEM_PROMPT, build_user_prompt, format_comment_body

MODEL = "claude-opus-4-5"
MAX_TOKENS = 4096
MAX_FILES_PER_CHUNK = 8  # Keep each API call focused; split large PRs into chunks


@dataclass
class ReviewResult:
    summary: str
    comments: list  # list of dicts from Claude's JSON


class ClaudeClient:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def review_files(self, file_diffs: list) -> ReviewResult:
        """
        Review all changed files, chunking into multiple API calls if the PR
        is large. Results are merged into a single ReviewResult.
        """
        if not file_diffs:
            return ReviewResult(summary="No reviewable files in this PR.", comments=[])

        chunks = self._chunk_files(file_diffs)
        all_comments: list = []
        summaries: list[str] = []

        for i, chunk in enumerate(chunks):
            print(f"Reviewing chunk {i + 1}/{len(chunks)} ({len(chunk)} file(s))...")
            result = self._call_claude(chunk)
            all_comments.extend(result.comments)
            summaries.append(result.summary)

        merged_summary = (
            summaries[0]
            if len(summaries) == 1
            else "**Multi-chunk review:**\n" + "\n".join(f"- {s}" for s in summaries)
        )

        return ReviewResult(summary=merged_summary, comments=all_comments)

    def build_github_comments(self, result: ReviewResult) -> list:
        """
        Convert ClaudeReviewResult comments into ReviewComment objects
        ready for the GitHub API.
        """
        from reviewer.github_client import ReviewComment

        github_comments = []
        for c in result.comments:
            body = format_comment_body(
                severity=c.get("severity", "info"),
                title=c.get("title", "Issue"),
                body=c.get("body", ""),
            )
            github_comments.append(
                ReviewComment(
                    path=c["path"],
                    line=int(c["line"]),
                    body=body,
                )
            )
        return github_comments

    def _call_claude(self, file_diffs: list) -> ReviewResult:
        """Single API call for a chunk of files. Returns parsed ReviewResult."""
        user_message = build_user_prompt(file_diffs)

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()

        # Strip accidental markdown fences if the model adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"Failed to parse Claude response as JSON: {e}")
            print(f"Raw response: {raw[:500]}")
            return ReviewResult(
                summary="AI reviewer encountered a parsing error. Manual review recommended.",
                comments=[],
            )

        return ReviewResult(
            summary=data.get("summary", ""),
            comments=data.get("comments", []),
        )

    @staticmethod
    def _chunk_files(file_diffs: list) -> list[list]:
        """Split file list into chunks of MAX_FILES_PER_CHUNK."""
        return [
            file_diffs[i : i + MAX_FILES_PER_CHUNK]
            for i in range(0, len(file_diffs), MAX_FILES_PER_CHUNK)
        ]
