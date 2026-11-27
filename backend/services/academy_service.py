"""
FinGroww SaaS Platform — 4-Stage Trading Academy LMS Service (Phase 5).
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.database import db_manager


class AcademyError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_courses_with_progress(user_id: Optional[str] = None) -> Dict[str, Any]:
    courses = list(db_manager.collection("academy_courses").find({}, {"_id": 0}).sort("stage", 1))
    progress_map: Dict[str, Dict[str, Any]] = {}
    if user_id:
        for p in db_manager.collection("academy_progress").find({"user_id": user_id}, {"_id": 0}):
            progress_map[p["course_id"]] = p

    enriched: List[Dict[str, Any]] = []
    total_lessons = 0
    completed_total = 0

    for c in courses:
        cid = c["course_id"]
        lessons = c.get("lessons") or []
        total_lessons += len(lessons)
        prog = progress_map.get(cid, {})
        done_ids = set(prog.get("completed_lessons") or [])
        completed_total += len(done_ids)

        enriched.append({
            **c,
            "completed_lessons": sorted(list(done_ids)),
            "progress_pct": round((len(done_ids) / len(lessons)) * 100.0, 1) if lessons else 0.0,
            "completed": bool(prog.get("completed", False)),
            "quiz_score_pct": prog.get("quiz_score_pct"),
        })

    overall_pct = round((completed_total / total_lessons) * 100.0, 1) if total_lessons > 0 else 0.0
    return {
        "ok": True,
        "overall_progress_pct": overall_pct,
        "completed_lessons_count": completed_total,
        "total_lessons_count": total_lessons,
        "courses": enriched,
    }


def mark_lesson_complete(
    user_id: str,
    course_id: str,
    lesson_id: str,
    quiz_score_pct: Optional[float] = None,
) -> Dict[str, Any]:
    course = db_manager.collection("academy_courses").find_one({"course_id": course_id}, {"_id": 0})
    if not course:
        raise AcademyError("Course not found", 404)

    valid_lessons = {ls["lesson_id"] for ls in (course.get("lessons") or [])}
    if lesson_id not in valid_lessons:
        raise AcademyError("Lesson not found in this course", 404)

    prog_col = db_manager.collection("academy_progress")
    existing = prog_col.find_one({"user_id": user_id, "course_id": course_id}) or {}
    done = set(existing.get("completed_lessons") or [])
    done.add(lesson_id)

    is_course_done = len(done) >= len(valid_lessons)
    now_iso = _now_iso()
    doc = {
        "user_id": user_id,
        "course_id": course_id,
        "completed_lessons": sorted(list(done)),
        "completed": is_course_done,
        "quiz_score_pct": quiz_score_pct if quiz_score_pct is not None else existing.get("quiz_score_pct"),
        "updated_at": now_iso,
    }
    if is_course_done and not existing.get("completed"):
        doc["completed_at"] = now_iso
        db_manager.collection("notifications").insert_one({
            "notification_id": f"NTF-{uuid.uuid4().hex[:8].upper()}",
            "user_id": user_id,
            "title": f"Course Completed: {course['title']}",
            "message": f"Congratulations! You completed all {len(valid_lessons)} lessons in Stage {course['stage']}.",
            "category": "academy",
            "is_read": False,
            "created_at": now_iso,
        })

    prog_col.update_one({"user_id": user_id, "course_id": course_id}, {"$set": doc}, upsert=True)
    return list_courses_with_progress(user_id)
