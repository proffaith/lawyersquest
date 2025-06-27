from db import Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest, SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem, Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus, TeamMessage, TreasureChest, XpThreshold, ChestHint

from flask import Blueprint, session as flask_session, request, jsonify, redirect, url_for, render_template
from services.progress import update_squire_progress
import random
import logging
from sqlalchemy import or_, func, and_, asc, not_, desc


from utils.shared import get_squire_stats
from utils.shared import check_quest_completion
from utils.shared import complete_quest
from utils.shared import calculate_hit_chance
from utils.shared import calculate_enemy_encounter_probability
from utils.shared import update_work_for_combat
from utils.shared import get_player_max_hunger
from utils.shared import mod_enemy_hunger
from utils.shared import combat_mods
from utils.shared import hunger_mods
from utils.shared import degrade_gear
from utils.shared import ishint
from utils.shared import iswordcounthint
from utils.shared import iswordlengthhint
from utils.shared import flee_safely
from utils.shared import calc_flee_safely
#from utils.filters import chance_image
from utils.shared import add_team_message

combat_bp = Blueprint('combat', __name__)

@combat_bp.app_template_filter('the_image')
def the_image(chance):
    try:
        chance = int(chance)
    except:
        return "unknown.png"

    if chance >= 80:
        return "chance_high.png"
    elif chance >= 50:
        return "chance_medium.png"
    else:
        return "chance_low.png"

@combat_bp.route('/ajax_handle_combat', methods=['POST'])
def ajax_handle_combat():
    """Handles combat via AJAX by updating hunger levels and returning JSON."""
    enemy = flask_session.get("enemy")
    squire_id = flask_session.get("squire_id")
    player_current_hunger = flask_session["player_current_hunger"]
    enemy_current_hunger = flask_session["enemy_current_hunger"]
    player_max_hunger = flask_session["player_max_hunger"]
    mod_enemy_max_hunger = flask_session["mod_enemy_max_hunger"]
    hit_chance = flask_session["hit_chance"]
    mod_for_distance = flask_session["mod_for_distance"]
    flask_session.pop("success",None)
    outcome=[]

    db=db_session()

    if not enemy:
        return jsonify({"redirect": url_for("map_view")})

    # Initialize combat if not already active
    if "combat_active" not in flask_session or not flask_session["combat_active"]:
        flask_session["player_current_hunger"] = 0
        flask_session["enemy_current_hunger"] = 0
        flask_session["battle_log"] = []
        flask_session["combat_active"] = True

    # route based on the button pushed by the user
    action = request.form.get("action")

    if action == "flee":

        if flee_safely(mod_enemy_max_hunger,player_max_hunger, hit_chance) == False:
            flask_session["combat_result"] = "🏃 You managed to escape safely!"
            flask_session["success"] = True
        else:
            degrade_gear(squire_id, enemy["weakness"])
            flask_session["combat_result"] = "🏃 You managed to escape but your armor was damaged during the retreat."
            flask_session["success"] = False
        # Clear session combat variables
        flask_session.pop("enemy", None)
        flask_session.pop("player_current_hunger", None)
        flask_session.pop("enemy_current_hunger", None)
        flask_session.pop("combat_active", None)
        flask_session.pop("battle_log", None)
        flask_session.pop("success",None)
        return jsonify({"redirect": url_for("combat.combat_results")})
    elif action == "question":
        #re-route player to answer a question
        # Clear session combat variables
        flask_session.pop("enemy", None)
        flask_session.pop("player_current_hunger", None)
        flask_session.pop("enemy_current_hunger", None)
        flask_session.pop("combat_active", None)
        flask_session.pop("battle_log", None)
        return jsonify({"redirect": url_for("questions.answer_question")})

    else:
        battle_log = []

        # Player attack attempt
        if random.randint(1, 100) <= hit_chance:
            enemy_current_hunger += 1
            battle_log.append(f"💥 You hit the {enemy['name']} with your {enemy['weakness']}! They are getting hungrier.")
        else:
            player_current_hunger += 1
            battle_log.append(f"❌ Ouch! Bad Touch, {enemy['name']}! You are getting hungrier.")

    # Check for combat end conditions
        # result if player lost
        if int(player_current_hunger) >= int(player_max_hunger):
            degrade_gear(squire_id, enemy["weakness"])

            # load the Squire
            squire = db.query(Squire).get(squire_id)
            # subtract XP but never go below zero
            squire.experience_points = max(0, squire.experience_points - enemy["xp_reward"])
            db.commit()

            outcome = f"🛑 You are too hungry to continue fighting! The enemy forces you to flee and damages your gear.\n❌ You lose some XP."
            flask_session["combat_result"] = outcome
            flask_session["success"] = False

            # Clear session variables
            flask_session.pop("enemy", None)
            flask_session.pop("player_current_hunger", None)
            flask_session.pop("enemy_current_hunger", None)
            flask_session.pop("combat_active", None)
            flask_session.pop("battle_log", None)

            return jsonify({"redirect": url_for("combat.combat_results")})

        # result if player won
        if int(enemy_current_hunger) >= int(mod_enemy_max_hunger):
            xp = enemy["xp_reward"]
            bitcoin = enemy["gold_reward"]
            # Apply additional modifiers based on location
            if enemy.get("in_forest"):
                xp += 10
            if 51 <= mod_for_distance <= 150:
                xp += 5 if not enemy.get("in_forest") else 15
                bitcoin += 10
            elif 151 <= mod_for_distance <= 500:
                xp += 10 if not enemy.get("in_forest") else 30
                bitcoin += 20
            elif 501 <= mod_for_distance <= 1000:
                xp += 20 if not enemy.get("in_forest") else 40
                bitcoin += 25
            elif mod_for_distance > 1000:
                xp += 25 if not enemy.get("in_forest") else 55
                bitcoin += 100

            outcome.append(update_squire_progress(squire_id,  xp, bitcoin))
            degrade_gear(squire_id, enemy["weakness"])
            outcome.append(f"🍕 The {enemy['name']} is too hungry to continue! They run off to eat a pizza.\nYou gain {xp} XP and {bitcoin} bits.")

            message = " ".join([str(m) for m in outcome if m])
            flask_session["combat_result"] = message

            # ✅ Reset combat flag and work sessions after combat
            flask_session["forced_combat"] = False
            flask_session["success"] = True
            db.query(Squire) \
              .filter(Squire.id == squire_id) \
              .update({ Squire.work_sessions: 0 }, synchronize_session='fetch')
            db.commit()

            toast = f"{flask_session['squire_name']} defeated {enemy['name']} and gained {xp} XP and {bitcoin} bits."
            add_team_message(flask_session['team_id'],toast)

            # Clear combat session variables
            flask_session.pop("enemy", None)
            flask_session.pop("player_current_hunger", None)
            flask_session.pop("enemy_current_hunger", None)
            flask_session.pop("combat_active", None)
            flask_session.pop("battle_log", None)


            return jsonify({"redirect": url_for("combat.combat_results")})


    # Save updated values in session
    flask_session["player_current_hunger"] = player_current_hunger
    flask_session["enemy_current_hunger"] = enemy_current_hunger
    flask_session["battle_log"] = battle_log

    # Return updated combat data as JSON
    return jsonify({
        "player_current_hunger": player_current_hunger,
        "enemy_current_hunger": enemy_current_hunger,
        "battle_log": battle_log,
        "hit_chance": hit_chance,
        "player_max_hunger": player_max_hunger,
        "mod_enemy_max_hunger": mod_enemy_max_hunger
    })


@combat_bp.route('/combat_results', methods=['GET'])
def combat_results():
    if flask_session.get("leveled_up"):
        return redirect(url_for("level_up"))

    return render_template(
        "combat_results.html",
        success=flask_session.pop("success", None),
        combat_result=flask_session.pop("combat_result", "")
    )



# ⚔️ Combat
@combat_bp.route('/combat', methods=['GET', 'POST'])
def combat():
    """Displays combat screen where player chooses to fight or flee."""
    enemy = flask_session.get('enemy')
    squire_id = flask_session.get("squire_id")
    db=db_session()

    if not enemy:
        logging.debug("No enemy found in session, redirecting to map.")
        return redirect(url_for('map_view'))  # No enemy data? Go back to map.

    x, y, level = (
        db.query(
            Squire.x_coordinate,
            Squire.y_coordinate,
            Squire.level
        )
        .filter(Squire.id == squire_id)
        .one()
    )

    #return necessary initial values for combat
    update_work_for_combat(squire_id)
    max_hunger, food = get_player_max_hunger(squire_id)
    base_hit_chance = calculate_hit_chance(squire_id, level)
    hit_chance = int(min(base_hit_chance + combat_mods(squire_id, enemy["name"], level), 95))
    player_max_hunger = min(max_hunger + hunger_mods(squire_id), 8)


    mod_for_distance = abs(x * y)
    enemy_max_hunger_base = enemy["max_hunger"]
    enemy_in_forest = enemy.get("in_forest")
    enemy_in_mountain = enemy.get("in_mountain")
    logging.debug(f"Dist / Base / F / M: {mod_for_distance} {enemy_max_hunger_base} {enemy_in_forest}  {enemy_in_mountain}")
    mod_enemy_max_hunger = mod_enemy_hunger(mod_for_distance, enemy_max_hunger_base, enemy_in_forest, enemy_in_mountain)
    logging.debug(f"mod_enemy_max_hunger = {mod_enemy_max_hunger}")
    safe_chances = calc_flee_safely(mod_enemy_max_hunger, player_max_hunger, hit_chance)

    # initialize session variables for battle
    player_current_hunger = 0
    enemy_current_hunger = 0
    battle_log = flask_session.get("battle_log", [])

    # Save updated values in session
    flask_session["player_current_hunger"] = player_current_hunger
    flask_session["enemy_current_hunger"] = enemy_current_hunger
    flask_session["player_max_hunger"] = player_max_hunger
    flask_session["mod_enemy_max_hunger"] = mod_enemy_max_hunger
    flask_session["hit_chance"] = hit_chance
    flask_session["mod_for_distance"] = mod_for_distance
    flask_session["safe_chances"] = safe_chances

    return render_template('combat.html', enemy=enemy)

@combat_bp.route('/encounter_enemy', methods=['GET'])
def encounter_enemy():
    """Handles an enemy encounter with a choice between knowledge and combat."""
    squire_id = flask_session.get("squire_id")
    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()
    try:
        # 1) Get squire position and level
        x, y, level = (
            db.query(
                Squire.x_coordinate,
                Squire.y_coordinate,
                Squire.level
            )
            .filter(Squire.id == squire_id)
            .one()
        )

        # 2) Determine terrain
        in_forest = (
            db.query(func.count(MapFeature.id))
              .filter(
                  MapFeature.x_coordinate == x,
                  MapFeature.y_coordinate == y,
                  MapFeature.terrain_type  == 'forest'
              )
              .scalar() > 0
        )
        in_mountain = (
            db.query(func.count(MapFeature.id))
              .filter(
                  MapFeature.x_coordinate == x,
                  MapFeature.y_coordinate == y,
                  MapFeature.terrain_type  == 'mountain'
              )
              .scalar() > 0
        )

        # 3) Pick a random non‑boss enemy appropriate to level
        enemy = (
            db.query(Enemy)
              .filter(
                  Enemy.is_boss   == False,
                  Enemy.min_level <= level
              )
              .order_by(func.rand())
              .first()
        )

        if enemy:
            # 4) Check for required weapon in inventory
            has_weapon = (
                db.query(func.count(Inventory.id))
                  .filter(
                      Inventory.squire_id == squire_id,
                      Inventory.item_name   == enemy.weakness
                  )
                  .scalar() > 0
            )

            # 5) Store JSON‑safe enemy data in session
            flask_session['enemy'] = {
                "id":           enemy.id,
                "name":         enemy.enemy_name,
                "description":  enemy.description,
                "weakness":     enemy.weakness,
                "gold_reward":  enemy.gold_reward,
                "xp_reward":    enemy.xp_reward,
                "max_hunger":   enemy.max_hunger,
                "in_forest":    in_forest,
                "in_mountain":  in_mountain,
                "has_weapon":   has_weapon,
                "static_image": enemy.static_image,
                "min_level": enemy.min_level
            }

        return redirect(url_for('combat.combat'))

    finally:
        db.close()

@combat_bp.route('/encounter_boss', methods=['GET'])
def encounter_boss():
    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")
    if not squire_id:
        return redirect(url_for("login"))

    db = db_session()

    if quest_id == 14:
        try:
            # 1) Fetch squire’s position & level
            x, y, level = (
                db.query(
                    Squire.x_coordinate,
                    Squire.y_coordinate,
                    Squire.level
                )
                .filter(Squire.id == squire_id)
                .one()
            )

            # 2) Fetch the boss by name pattern
            boss = (
                db.query(Enemy)
                  .filter(Enemy.enemy_name.ilike("%Lexiconis%"))
                  .first()
            )

            if boss:
                # 3) Store JSON‑safe boss data in session
                flask_session['boss'] = {
                    "id":           boss.id,
                    "name":         boss.enemy_name,
                    "description":  boss.description,
                    "weakness":     boss.weakness,
                    "gold_reward":  boss.gold_reward,
                    "xp_reward":    boss.xp_reward,
                    "max_hunger":   boss.max_hunger
                }

            return redirect(url_for('combat.boss_combat'))

        finally:
            db.close()

    if quest_id == 28:
        return redirect(url_for('questions.answer_MC_question'))


@combat_bp.route('/boss_combat', methods=['GET', 'POST'])
def boss_combat():
    """Displays combat screen where player chooses to fight or flee."""
    boss = flask_session.get('boss')
    squire_id = flask_session.get("squire_id")
    quest_id = flask_session.get("quest_id")

    db = db_session()

    if not boss:
        logging.debug("Guess the boss is out to lunch: redirecting to map.")
        return redirect(url_for('map_view'))  # No enemy data? Go back to map.

    x, y, level = (
        db.query(
            Squire.x_coordinate,
            Squire.y_coordinate,
            Squire.level
        )
        .filter(Squire.id == squire_id)
        .one()
    )

    max_hunger, food = get_player_max_hunger(squire_id)
    player_max_hunger = min(max_hunger + hunger_mods(squire_id), 8)
    boss_max_hunger = boss["max_hunger"]

    # initialize session variables for battle
    if flask_session.get("player_current_hunger") is None:
        flask_session["player_current_hunger"] = 0
    if flask_session.get("boss_current_hunger") is None:
        flask_session["boss_current_hunger"] = 0

    flask_session["player_max_hunger"] = int(player_max_hunger)
    flask_session["boss_max_hunger"] = int(boss_max_hunger)

    return render_template('boss_combat.html', boss=boss)

@combat_bp.route('/ajax_handle_boss_combat', methods=['POST', 'GET'])
def ajax_handle_boss_combat():
    """Handles combat via AJAX by updating hunger levels and returning JSON."""
    boss = flask_session.get("boss")
    squire_id = flask_session.get("squire_id")

    if not boss or not squire_id:
        logging.error("Missing boss or squire_id in session")
        return jsonify({"redirect": url_for("map_view")})

    try:
        player_current_hunger = flask_session.get("player_current_hunger", 0)
        boss_current_hunger = flask_session.get("boss_current_hunger", 0)
        player_max_hunger = flask_session.get("player_max_hunger", 0)
        boss_max_hunger = flask_session.get("boss_max_hunger", 0)


        logging.debug(f"Boss Status: {boss_current_hunger} / {boss_max_hunger} Player Status {player_current_hunger} / {player_max_hunger}")

        # route based on the button pushed by the user
        action = request.form.get("action")

        if action == "flee":
            if flee_safely(boss_max_hunger, player_max_hunger, 0) == False:
                session["combat_result"] = "🏃 You managed to escape safely!"
            else:
                degrade_gear(squire_id, boss["weakness"])
                session["combat_result"] = "🏃 You managed to escape but your armor was damaged during the retreat."
            # Clear session combat variables
            cleanup_session()
            return jsonify({"redirect": url_for("combat.combat_results")})

        else: #answer questions
            return jsonify({"redirect": url_for("combat.answer_MC_question")})

    except Exception as e:
        logging.error(f"Error in boss combat: {str(e)}")
        return jsonify({"error": "An error occurred during combat"}), 500
