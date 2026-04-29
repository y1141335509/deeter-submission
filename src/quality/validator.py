from typing import List
from src.models.post import ProcessedPost, QualityReport


def validate(post: ProcessedPost) -> QualityReport:
    """
    Score a processed post for quality. Returns a QualityReport with
    a 0.0–1.0 score and a list of specific issues found.

    Scoring: start at 1.0, subtract penalties for each issue.
    Hard failures (missing ID, removed/deleted content) mark is_valid=False.
    """
    issues: List[str] = []
    penalty = 0.0

    # Hard failures
    if not post.post_id:
        return QualityReport(is_valid=False, issues=["missing post_id"], quality_score=0.0)

    body_lower = post.body.lower().strip()
    if body_lower in ("[removed]", "[deleted]"):
        return QualityReport(is_valid=False, issues=["content removed/deleted"], quality_score=0.0)

    # Soft quality checks
    if not post.title or len(post.title.strip()) < 5:
        issues.append("title too short (<5 chars)")
        penalty += 0.3

    if not post.body:
        issues.append("empty body")
        penalty += 0.1

    if not (0.0 <= post.upvote_ratio <= 1.0):
        issues.append(f"invalid upvote_ratio={post.upvote_ratio}")
        penalty += 0.2

    if not (-1.0 <= post.sentiment_compound <= 1.0):
        issues.append(f"sentiment_compound out of range: {post.sentiment_compound}")
        penalty += 0.2

    if post.created_utc <= 0:
        issues.append("invalid created_utc")
        penalty += 0.2

    quality_score = round(max(0.0, 1.0 - penalty), 3)
    return QualityReport(is_valid=True, issues=issues, quality_score=quality_score)
