# Town-related routes
from flask import Blueprint, session as flask_session, request, jsonify, render_template, redirect, url_for, flash
from db import db_session, Squire, ShopItem, Team, Job, Inventory, WizardItem
import random
from collections import defaultdict
from sqlalchemy import create_engine, func, and_, select
from dotenv import load_dotenv
from openai import OpenAI

import re
import os
import json
import logging


client = OpenAI(api_key=os.getenv("OPENAI_APIKEY"))


from utils.shared import get_inventory
from utils.api_calls import generate_npc_response

load_dotenv()


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

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~NPC interactions
@town_bp.route('/npc', methods=['GET'])
def npc():
    """Handles Wandering Trader encounters and displays hints."""
    npc_message = flask_session.pop("npc_message", "The trader has no hints for you.")
    return render_template("npc.html", npc_message=npc_message)




@town_bp.route('/api/repair_quote', methods=['POST'])
def get_repair_quote():
    try:
        squire_id = flask_session.get('squire_id')
        db = db_session()
        squire = db.query(Squire).get(squire_id)
        team = db.query(Team).get(squire.team_id)
        level = squire.level
        max_uses = level * 4

        data = request.get_json()
        item_id = data.get('item_id')
        item = db.query(Inventory).get(item_id)

        if not item or "magic" in item.description.lower():
            return jsonify({"error": "Invalid or magical item"}), 400

        shop_item = db.query(ShopItem).filter_by(item_name=item.item_name).first()
        if not shop_item:
            return jsonify({"error": "Original item data not found"}), 404

        original_value = shop_item.price
        original_uses = shop_item.uses
        uses_remaining = item.uses_remaining

        # Calculate damage ratio
        if uses_remaining > original_uses:
            damage_ratio = (max_uses - uses_remaining) / max_uses
        else:
            damage_ratio = (original_uses - uses_remaining) / original_uses

        base_quote = round(damage_ratio * original_value)
        pct = random.uniform(0.1, 0.3)  # 10%–30% discount
        discount = round(base_quote * pct)
        quoted_price = max(10, base_quote - discount)  # Minimum 10 bits

        # Set session state for haggling
        flask_session["blacksmith_quote"] = quoted_price
        flask_session["blacksmith_rounds"] = 0
        flask_session["blacksmith_item_id"] = item.id
        flask_session["blacksmith_last_offer"] = None
        flask_session["blacksmith_minimum_price"] = quoted_price
        flask_session["blacksmith_offer"] = quoted_price
        flask_session.modified = True

        # GPT intro message (optional flavor, no counter yet)
        intro_message = (
            f"The blacksmith eyes your {item.item_name} and says, "
            f"'This will cost you {quoted_price} bits to fix it up proper.'"
        )

        return jsonify({
            "quote": quoted_price,
            "message": intro_message,
            "item_id": item.id
        })

    except Exception as e:
        logging.error(f"Error in /api/repair_quote: {e}")
        return jsonify({"error": "Something went wrong."}), 500

    finally:
        db.close()


@town_bp.route('/reset_blacksmith')
def reset_blacksmith():
    for key in ["blacksmith_item_id", "blacksmith_quote", "blacksmith_rounds",
                "blacksmith_minimum_price", "blacksmith_offer", "blacksmith_reply"]:
        flask_session.pop(key, None)
    return redirect(url_for('map_view'))


@town_bp.route('/blacksmith', methods=['GET', 'POST'])
def blacksmith():
    db = db_session()
    try:
        squire_id = flask_session.get("squire_id")
        squire = db.query(Squire).get(squire_id)
        team = db.query(Team).get(squire.team_id)
        max_uses = squire.level * 4

        # Exclude wizard items
        wizard_item_names = db.query(WizardItem.item_name)
        broken_items = (
            db.query(Inventory)
            .filter(
                Inventory.squire_id == squire_id,
                Inventory.item_type == "gear",
                ~Inventory.description.ilike("%magic%"),
                Inventory.uses_remaining < max_uses,
                ~Inventory.item_name.in_(wizard_item_names)
            )
            .all()
        )

        # ✅ If GET and not AJAX → Render page
        if request.method == 'GET':
            return render_template('blacksmith.html',
                                   squire=squire,
                                   team=team,
                                   broken_items=broken_items)

        # ✅ From here: POST logic (haggle or accept)
        accept_json = 'application/json' in request.headers.get('Accept', '')
        item_id = int(request.form.get("item_id", 0))
        offer = int(request.form.get("bitcoin", 0))
        accept_final = request.form.get("accept") == "true"

        # Validate item
        item = db.query(Inventory).get(item_id)
        if not item:
            msg = "Item not found."
            return (jsonify({"error": msg}), 400) if accept_json else redirect(url_for('town.blacksmith'))

        # ✅ Accept Final Offer
        if accept_final:
            if team.gold < offer:
                msg = "Not enough gold!"
                return (jsonify({"error": msg}), 400) if accept_json else redirect(url_for('town.blacksmith'))

            # Repair
            item.uses_remaining = min(max_uses, item.uses_remaining + offer)
            team.gold -= offer
            db.commit()

            # Clear haggle state
            for key in list(flask_session.keys()):
                if key.startswith("blacksmith_"):
                    flask_session.pop(key, None)

            if accept_json:
                return jsonify({
                    "success": True,
                    "message": f"🛠️ Your {item.item_name} is repaired for {offer} ₿!"
                })
            else:
                flask_session["game_message"] = f"🛠️ Your {item.item_name} was repaired!"
                return redirect(url_for('town.map_view'))

        # ✅ Haggle Path
        rounds = flask_session.get("blacksmith_rounds", 0) + 1
        flask_session["blacksmith_rounds"] = rounds

        context = {
            "item_name": item.item_name,
            "offer": offer,
            "base_price": flask_session.get("blacksmith_quote"),
            "original_quote": flask_session.get("blacksmith_quote"),
            "rounds": rounds
        }

        result = generate_npc_response("blacksmith", context)
        reply_text = result["reply_text"]
        counteroffer = result.get("counteroffer")

        # FIX: Better fallback logic when GPT doesn't return a counteroffer
        if not counteroffer:
            # Calculate a reasonable counteroffer instead of using user's offer
            original_quote = flask_session.get("blacksmith_quote", 100)
            previous_offer = flask_session.get("blacksmith_offer", original_quote)

            if offer < previous_offer:
                # User offered less, blacksmith comes down a bit
                reduction = (previous_offer - offer) * 0.3  # 30% of the gap
                counteroffer = max(
                    round(previous_offer - reduction),
                    offer + 5,  # At least 5 more than user's offer
                    round(original_quote * 0.4)  # Never go below 40% of original
                )
            else:
                # User offered more than or equal to current offer, accept it
                counteroffer = offer

        flask_session["blacksmith_offer"] = counteroffer
        flask_session["blacksmith_reply"] = reply_text
        flask_session.modified = True

        if accept_json:
            return jsonify({
                "reply": reply_text,
                "offer": counteroffer,
                "rounds": rounds
            })
        else:
            return redirect(url_for('town.blacksmith'))

    except Exception as e:
        logging.error(f"Error in blacksmith: {e}")
        if 'application/json' in request.headers.get('Accept', ''):
            return jsonify({"error": "Something went wrong"}), 500
        flash("Something went wrong.")
        return redirect(url_for('town.blacksmith'))

    finally:
        db.close()


@town_bp.route('/wandering_trader', methods=['GET', 'POST'])
def wandering_trader():
    trader_is_gone = flask_session.pop("trader_gone", False)  # Clear on reload
    squire_id = flask_session.get('squire_id')
    db = db_session()
    squire = db.query(Squire).get(squire_id)
    team = db.query(Team).get(squire.team_id)
    base_template = 'base.html'

    if request.method == 'POST':
        item_id = int(request.form['item_id'])
        agreed_price = int(request.form.get('agreed_price') or 0)
        shop_item = db.query(ShopItem).get(item_id)

        if agreed_price <= 0:
            agreed_price = int(request.form.get(f'price_{item_id}', shop_item.price))

        if agreed_price > team.gold:
            flash("You can't afford that!", "error")
            return redirect(url_for('town.wandering_trader'))

        reputation_awarded = max(0, (shop_item.price - agreed_price) // 10)
        team.reputation = (team.reputation or 0) + reputation_awarded

        team.gold -= agreed_price
        db.add(Inventory(
            squire_id=squire.id,
            item_name=shop_item.item_name,
            description=shop_item.description,
            uses_remaining=shop_item.uses,
            item_type=shop_item.item_type
        ))
        db.commit()
        message = f"You bought {shop_item.item_name} for {agreed_price} bits!"
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
                           item_info=item_info,
                           base_template=base_template,
                           trader_is_gone=trader_is_gone)

@town_bp.route('/negotiate/<npc_type>', methods=['POST'])
def negotiate(npc_type):
    session_key = f"lowball_strikes_{npc_type}"
    lowball_strikes = flask_session.get(session_key, 0)

    squire_id = flask_session['squire_id']
    db = db_session()
    squire = db.query(Squire).get(squire_id)

    try:
        data = request.get_json(force=True)
        print("📨 Received haggle request data:", data)
    except Exception as e:
        print("❌ Error parsing JSON in haggle route:", e)
        return jsonify({"error": "Invalid JSON"}), 400



    item = data.get('item')
    offer = data.get('offer')
    base_price = data.get('base_price')

    try:
        offer_val = int(offer)
        reputation_change = max(0, (int(base_price) - offer_val) // 10)
    except Exception as e:
        print(f"💥 Offer conversion error: {e}")
        offer_val = int(base_price)
        reputation_change = 0


    if not all([item, offer, base_price]):
        return jsonify({"error": "Missing data in request."}), 400

    # Check if offer is absurdly low
    if int(offer) < int(base_price) * 0.25:
        lowball_strikes += 1
        flask_session[session_key] = lowball_strikes

        if lowball_strikes >= 3:
            npc_reply = (
                "😡 'You mock me for the last time! I won't trade with you anymore.' "
                "The trader grabs their wares and disappears into the woods."
            )
            return jsonify({
                "npc_reply": npc_reply,
                "final_price": None,
                "reputation_awarded": 0,
                "counteroffer": None,
                "trader_gone": True,
                "trader_is_gone": True
            })

        npc_reply = (
            f"The trader frowns deeply. 'You're wasting my time with that kind of offer. "
            f"Try again later... if I’m still here.' [Counteroffer: {base_price}]"
        )
        return jsonify({
            "npc_reply": npc_reply,
            "final_price": int(offer),
            "reputation_awarded": 0,
            "counteroffer": base_price,
            "trader_gone": False,
            "trader_is_gone": False
        })


    personality = {
        "blacksmith": "gruff but fair, values honesty",
        "trader": "wily, smooth-talking, always looking for a profit"
    }.get(npc_type, "neutral")

    system_prompt = f"You are a {npc_type}, {personality}. You're haggling over an item in a fantasy town."

    user_prompt = (
        f"The player offered {offer} gold for '{item}', normally worth {base_price} gold. "
        "Respond as a clever NPC, and include a number for your counteroffer in the reply. "
        "Your response should be short, and end with: [Counteroffer: <amount>]"
    )

    try:
        response = client.chat.completions.create(model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
        npc_reply = response.choices[0].message.content

        match = re.search(r"\[Counteroffer:\s*(\d+)", npc_reply)
        counteroffer = int(match.group(1)) if match else base_price

        print("🤖 NPC reply:", npc_reply)
        print("🔍 Parsed counteroffer:", counteroffer)


    except Exception as e:
        print(f"💥 GPT API error: {e}")
        return jsonify({"error": "NPC is refusing to talk right now."}), 500

    return jsonify({
        "npc_reply": npc_reply,
        "final_price": offer_val,
        "reputation_awarded": reputation_change,
        "counteroffer": counteroffer
    })


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
            return jsonify(success=False, message="Not enough bits to buy this item!"), 400

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
