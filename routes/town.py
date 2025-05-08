# Town-related routes
from flask import Blueprint, session as flask_session, request, jsonify, render_template, redirect, url_for, flash
from db import db_session, Squire, ShopItem, Team, Job, Inventory
import random
from collections import defaultdict
from sqlalchemy import create_engine, func, and_

from utils.shared import get_inventory

town_bp = Blueprint('town', __name__)

# inside routes/town.py
def chance_image(chance):
    if chance > 80:
        return "🔥"
    elif chance > 50:
        return "⚔️"
    return "🌿"

town_bp.add_app_template_filter(chance_image, name='chance_image')

#Town Routes here

@town_bp.route('/town', methods=['GET'])
def visit_town():
    """Displays the town menu with options to shop, work, or leave."""
    squire_id   = flask_session.get("squire_id")
    job_message = flask_session.pop("job_message", None)

    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        # Fetch the squire’s level via ORM
        squire = db.query(Squire).get(squire_id)
        level  = squire.level
    finally:
        db.close()

    return render_template(
        "town.html",
        level=level,
        job_message=job_message
    )
#NPC interactions
@town_bp.route('/npc', methods=['GET'])
def npc():
    """Handles Wandering Trader encounters and displays hints."""
    npc_message = flask_session.pop("npc_message", "The trader has no hints for you.")
    return render_template("npc.html", npc_message=npc_message)

@town_bp.route('/blacksmith', methods=['GET', 'POST'])
def blacksmith():
    squire_id = flask_session['squire_id']
    db = db_session()
    # load squire and inventory items that need repair:
    squire = db.query(Squire).get(squire_id)
    team = db.query(Team).get(squire.team_id)  # or use a relationship if defined
    level = squire.level

    max_uses = level * 4

    broken_items = (
        db.query(Inventory)
        .filter(
            Inventory.squire_id == squire_id,
            Inventory.item_type == "gear",
            ~Inventory.description.ilike("%magical%"),
            Inventory.uses_remaining < max_uses
        )
        .all()
    )

    # In your route (after defining broken_items)
    item_info = [
        {
            "id": item.id,
            "name": item.item_name,
            "uses_remaining": item.uses_remaining,
            "max_uses": max_uses  # or item-specific if using a property
        }
        for item in broken_items
    ]


    if request.method == 'POST':
        item_id   = int(request.form['item_id'])
        pay_amount= int(request.form['bitcoin'])
        item = db.query(Inventory).get(item_id)

        # sanity checks
        if pay_amount <= 0 or pay_amount > team.gold:
            flash("Invalid payment amount.", "error")
            return redirect(url_for('blacksmith'))

        # e.g. 1 bitcoin = 1 use repaired
        repaired_uses = pay_amount
        item.uses_remaining = min(50, item.uses_remaining + repaired_uses)
        team.gold -= pay_amount

        db.commit()
        message = f"Your {item.item_name} regained {repaired_uses} uses!"
        flask_session['game_message'] = message
        return redirect(url_for('map_view'))

    return render_template('blacksmith.html',
                           squire=squire,
                           team=team,
                           broken_items=broken_items,
                           item_info=item_info)

@town_bp.route('/wandering_trader', methods=['GET', 'POST'])
def wandering_trader():
    squire_id = flask_session.get('squire_id')
    db = db_session()
    squire = db.query(Squire).get(squire_id)
    team = db.query(Team).get(squire.team_id)

    if request.method == 'POST':
        item_id = int(request.form['item_id'])
        shop_item = db.query(ShopItem).get(item_id)

        if shop_item.price > team.gold:
            flash("You can't afford that!", "error")
            return redirect(url_for('wandering_trader'))

        team.gold -= shop_item.price
        db.add(Inventory(
            squire_id = squire.id,
            item_name = shop_item.item_name,
            description = shop_item.description,
            uses_remaining = shop_item.uses,
            item_type = shop_item.item_type
        ))
        db.commit()
        message = f"You bought {shop_item.item_name} for {shop_item.price} bits!"
        flask_session['game_message'] = message
        return redirect(url_for('map_view'))

    trader_items = (
    db.query(ShopItem)
        .filter(
            ShopItem.available_to_trader == True,
            ShopItem.min_level <= squire.level  # Only show items at or below the squire's level
        )
        .order_by(func.rand())
        .limit(3)
        .all()
    )

    item_info = [
        {
            "id": item.id,
            "name": item.item_name,
            "price": item.price,
            "description": item.description,
            "uses": item.uses,
            "item_type": item.item_type
        }
        for item in trader_items
    ]

    return render_template("wandering_trader.html",
                           squire=squire,
                           team=team,
                           items=trader_items,
                           item_info=item_info)


# 🚶 Game Actions (Movement, Shop, Town, Combat)
# mod for AJAX


@town_bp.route('/inventory', methods=['GET'])
def inventory():
    """Displays the player's inventory on a separate page."""
    squire_id = flask_session.get("squire_id")

    if not squire_id:
        return redirect(url_for("login"))

    conn = db_session()
    inventory = get_inventory(squire_id)  # Fetch inventory items

    return render_template("inventory.html", inventory=inventory)

@town_bp.route('/hall_of_fame', methods=['GET'])
def hall_of_fame():
    """Displays the Hall of Fame leaderboard."""
    db = db_session()
    try:
        # Fetch top 10 players by experience_points
        leaders = (
            db.query(Squire)
              .order_by(Squire.experience_points.desc())
              .limit(10)
              .all()
        )
    finally:
        db.close()

    # You can pass ORM objects directly to Jinja:
    # in the template: {{ leader.squire_name }} & {{ leader.experience_points }}
    return render_template("hall_of_fame.html", leaders=leaders)

@town_bp.route('/team_fame', methods=['GET'])
def team_fame():
    """Displays the Hall of Fame leaderboard for Teams Based on Reputation."""
    db = db_session()
    try:
        # Fetch top 10 players by experience_points
        leaders = (
            db.query(Team)
              .order_by(Team.reputation.desc())
              .limit(10)
              .all()
        )
    finally:
        db.close()

    # You can pass ORM objects directly to Jinja:
    # in the template: {{ leader.squire_name }} & {{ leader.experience_points }}
    return render_template("team_hall.html", leaders=leaders)

@town_bp.route('/town_work', methods=['GET', 'POST'])
def town_work():
    """Allows players to take on jobs to earn gold."""
    squire_id = flask_session.get("squire_id")
    level = flask_session.get("level")

    if not squire_id:
        return redirect(url_for("login"))

    MAX_WORK_SESSIONS = 3

    db = db_session()
    try:
        # 1) Load squire
        squire = db.query(Squire).get(squire_id)
        level  = squire.level
        work_sessions = squire.work_sessions

        # 2) Enforce forced combat if too many work sessions
        if flask_session.get("forced_combat"):
            flask_session["job_message"] = (
                "You must face the dangers beyond town before working again!"
            )
            return redirect(url_for("town.visit_town"))

        if work_sessions >= MAX_WORK_SESSIONS:
            flask_session["forced_combat"] = True
            flask_session["job_message"] = (
                "You must face the dangers beyond town before working again!"
            )
            return redirect(url_for("town.visit_town"))

        # 3) Handle job selection (POST)
        if request.method == 'POST':
            job_id = request.form.get("job_id", type=int)
            job = db.query(Job).get(job_id)
            if not job:
                flask_session["job_message"] = "❌ Invalid job selection!"
                return redirect(url_for("town.town_work"))

            payout = random.randint(job.min_payout, job.max_payout) * level
            flask_session["pending_job"] = {
                "job_id":     job.id,
                "job_name":   job.job_name,
                "min_payout": job.min_payout,
                "max_payout": job.max_payout,
                "level":      level
            }

            return redirect(url_for("questions.answer_question"))

        # 4) GET: fetch all jobs
        jobs = db.query(Job).all()

        for job in jobs:
            job.scaled_min = job.min_payout * level
            job.scaled_max = job.max_payout * level

        return render_template(
            "town_work.html",
            jobs=jobs
        )

    finally:
        db.close()
# 🏪 Shop
@town_bp.route('/shop', methods=['GET'])
def shop():
    """Displays the shop where players can buy items."""
    squire_id = flask_session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        # 1) Get squire level
        squire = db.query(Squire).get(squire_id)
        level  = squire.level

        # 2) Fetch available shop items
        items = (
            db.query(ShopItem)
              .filter(ShopItem.min_level <= level)
              .all()
        )

        grouped_items = defaultdict(list)
        for item in items:
            grouped_items[item.item_type].append(item)

        # 3) Fetch player's team gold balance
        team = db.query(Team).get(squire.team_id)
        player_gold = team.gold

        # 4) Store in session if needed
        flask_session["player_gold"] = player_gold

    finally:
        db.close()

    return render_template(
        "shop.html",
        grouped_items=grouped_items,
        player_gold=player_gold
    )

@town_bp.route('/buy_item', methods=['POST'])
def buy_item():
    """Handle purchasing an item via ORM instead of raw SQL."""
    data = request.get_json() or {}
    item_id = data.get("item_id")
    squire_id = flask_session.get("squire_id")

    if not item_id or not squire_id:
        return jsonify(success=False, message="Invalid request"), 400

    db = db_session()
    try:
        # 1) Load the shop item
        item = db.query(ShopItem).get(item_id)
        if not item:
            return jsonify(success=False, message="Item not found"), 404

        # 2) Load the squire and their team
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return jsonify(success=False, message="Player not found"), 404

        team = db.query(Team).get(squire.team_id)
        if not team:
            return jsonify(success=False, message="Team not found"), 404

        # 3) Check gold balance
        if team.gold < item.price:
            return jsonify(success=False, message="Not enough gold to buy this item!"), 400

        # 4) Deduct gold and add to inventory
        team.gold -= item.price
        new_inv = Inventory(
            squire_id       = squire_id,
            item_name       = item.item_name,
            description     = item.description,
            uses_remaining  = item.uses,
            item_type       = item.item_type
        )
        db.add(new_inv)
        db.commit()

        # 5) Return updated balance
        return jsonify(
            success=True,
            message=f"You bought {item.item_name}!",
            new_gold=team.gold
        )

    except Exception as e:
        db.rollback()
        return jsonify(success=False, message="Something went wrong!"), 500

    finally:
        db.close()
