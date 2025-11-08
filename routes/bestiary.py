from flask import Blueprint, request, render_template, jsonify, current_app
from db import db_session, Enemy
from sqlalchemy import or_, between, cast, Integer

bestiary_bp = Blueprint("bestiary", __name__)

PAGE_SIZE_DEFAULT = 12
PAGE_SIZE_MAX = 48

@bestiary_bp.route("/bestiary")
def bestiary_index():
    db = db_session()
    try:
        page = max(int(request.args.get("page", 1)), 1)
        page_size = min(int(request.args.get("per" , PAGE_SIZE_DEFAULT)), PAGE_SIZE_MAX)
        q = (request.args.get("q") or "").strip()
        min_level = request.args.get("min_level", type=int)
        max_level = request.args.get("max_level", type=int)
        boss = request.args.get("boss")  # '1', '0', or None
        rarity = (request.args.get("rarity") or "").strip().lower() or None

        query = db.query(Enemy)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Enemy.enemy_name.ilike(like), Enemy.description.ilike(like)))
        if min_level is not None and max_level is not None:
            query = query.filter(between(cast(Enemy.min_level, Integer), min_level, max_level))
        elif min_level is not None:
            query = query.filter(cast(Enemy.min_level, Integer) >= min_level)
        elif max_level is not None:
            query = query.filter(cast(Enemy.min_level, Integer) <= max_level)

        if boss in ("0", "1"):
            query = query.filter(Enemy.is_boss == (boss == "1"))

        total = query.count()
        items = (query
                 .order_by(Enemy.is_boss.desc(), Enemy.min_level.asc(), Enemy.enemy_name.asc())
                 .offset((page - 1) * page_size)
                 .limit(page_size)
                 .all())

        # map for view
        s3 = current_app.config.get("S3_CLIENT")
        rows = []
        for e in items:
            rows.append({
                "id": e.id,
                "name": e.enemy_name,
                "level": e.min_level,
                "boss": e.is_boss,
                "weakness": e.weakness,
                "gold": e.gold_reward,
                "xp": e.xp_reward,
                "img": e.static_image,
                "desc": (e.description or "").strip(),
            })

        return render_template(
            "bestiary.html",
            enemies=rows,
            page=page,
            page_size=page_size,
            total=total,
            q=q,
            min_level=min_level,
            max_level=max_level,
            boss=boss,
            )
    finally:
        db.close()


@bestiary_bp.route("/api/bestiary")
def bestiary_api():
    # Lightweight JSON for future front-end filters or mobile use
    db = current_app.config["DB_SESSION_FACTORY"]()
    try:
        q = (request.args.get("q") or "").strip()
        query = db.query(Enemy)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Enemy.enemy_name.ilike(like), Enemy.description.ilike(like)))
        items = query.order_by(Enemy.min_level, Enemy.enemy_name).limit(200).all()
        s3 = current_app.config.get("S3_CLIENT")
        data = [{
            "id": e.id,
            "name": e.enemy_name,
            "level": e.min_level,
            "boss": e.is_boss,
            "img": enemy_image_url(e, s3_client=s3),
        } for e in items]
        return jsonify({"results": data})
    finally:
        db.close()
