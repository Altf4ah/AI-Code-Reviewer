"""
AI PR Reviewer — main entrypoint.

Orchestrates:
  1. Fetch PR diff from GitHub
  2. Send to Claude for structured review
  3. Post inline comments back to the PR
"""

import sys

from reviewer.claude_client import ClaudeClient
from reviewer.github_client import GitHubClient


def main() -> None:
    print("=== AI PR Reviewer starting ===")

    github = GitHubClient()
    claude = ClaudeClient()

    # Step 1: Get the diff
    print("Fetching PR files...")
    file_diffs = github.get_pr_files()

    if not file_diffs:
        print("No reviewable files found. Exiting.")
        sys.exit(0)

    print(f"Reviewing {len(file_diffs)} file(s): {[f.filename for f in file_diffs]}")

    # Step 2: Ask Claude to review
    result = claude.review_files(file_diffs)

    print(f"Claude returned {len(result.comments)} comment(s).")
    print(f"Summary: {result.summary}")

    # Step 3: Post back to GitHub
    github_comments = claude.build_github_comments(result)
    github.post_review(comments=github_comments, summary=result.summary)

    print("=== AI PR Reviewer done ===")


if __name__ == "__main__":
    main()
