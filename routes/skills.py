# routes/skills.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session as flask_session
from sqlalchemy import select, func
from db import db_session, Skill, SquireSkillPoint, LevelSkillGrant
from flask_login import current_user, login_required, LoginManager


skills_bp = Blueprint("skills", __name__, url_prefix="/skills")

def get_skill_state(session, squire_id: int, current_level: int):
    """Returns (skills, allocated_by_skill_id, total_granted, total_allocated, available)."""
    player_id = flask_session.get("squire_id")
    # total granted up to current_level
    total_granted = session.scalar(
        select(func.coalesce(func.sum(LevelSkillGrant.points_granted), 0))
        .where(LevelSkillGrant.level <= current_level)
    ) or 0

    # current allocations
    rows = session.execute(
        select(SquireSkillPoint.skill_id, SquireSkillPoint.points)
        .where(SquireSkillPoint.squire_id == player_id)
    ).all()
    allocated = {sid: pts for sid, pts in rows}
    total_allocated = sum(allocated.values())

    # all skills catalog
    skills = session.execute(select(Skill).order_by(Skill.name)).scalars().all()

    available = max(0, total_granted - total_allocated)
    return skills, allocated, total_granted, total_allocated, available

@skills_bp.route("/", methods=["GET"])
def manage_skills():
    db = db_session()
    try:
        squire_id = flask_session.get("squire_id")  # adapt if your Squire id lives elsewhere
        current_level = flask_session.get("level")  # or however you store level

        skills, allocated, total_granted, total_allocated, available = get_skill_state(
            db, squire_id, current_level
        )
        return render_template(
            "../templates/manage_skills.html",
            skills=skills,
            allocated=allocated,
            available=available,
            total_granted=total_granted,
            total_allocated=total_allocated,
        )
    finally:
        db.close()

@skills_bp.route("/allocate", methods=["POST"])
def allocate_skills():
    db = db_session()
    try:
        squire_id = flask_session.get("squire_id")
        current_level = flask_session.get("level")

        # Recompute server-side truth
        skills, allocated, _, _, available = get_skill_state(db, squire_id, current_level)

        # Parse incoming desired absolute totals per skill: points[skill_id] = int
        form_points = {}
        for s in skills:
            val = request.form.get(f"points[{s.id}]", "")
            if val == "":
                continue
            try:
                form_points[s.id] = max(0, int(val))
            except ValueError:
                form_points[s.id] = allocated.get(s.id, 0)

        # Enforce per-skill caps
        for s in skills:
            if s.id in form_points and form_points[s.id] > s.max_points:
                form_points[s.id] = s.max_points

        # Compute delta budget
        new_total_alloc = sum(form_points.get(s.id, allocated.get(s.id, 0)) for s in skills)
        delta = new_total_alloc - sum(allocated.values())

        if delta > available:
            flash(f"Not enough unspent points. You tried to spend {delta} but only {available} available.", "warning")
            return redirect(url_for("skills.manage_skills"))

        # Persist (upsert)
        for s in skills:
            target = form_points.get(s.id, allocated.get(s.id, 0))
            current = allocated.get(s.id, 0)
            if target == current:
                continue
            # Fetch or create row
            psp = db.get(SquireSkillPoint, {"squire_id": squire_id, "skill_id": s.id})
            if not psp:
                psp = SquireSkillPoint(squire_id=squire_id, skill_id=s.id, points=0)
                db.add(psp)
            psp.points = target

        db.commit()
        flash("Skill points updated.", "success")
        return redirect(url_for("skills.manage_skills"))
    except Exception as e:
        db.rollback()
        flash(f"Error allocating skills: {e}", "danger")
        return redirect(url_for("skills.manage_skills"))
    finally:
        db.close()
