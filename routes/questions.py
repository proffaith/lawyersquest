# Question-related routes
from flask import Blueprint, session as flask_session, request, jsonify, render_template, redirect, url_for, flash
from db import db_session, Squire, TrueFalseQuestion, SquireQuestion, MultipleChoiceQuestion, Team
from services.progress import update_squire_progress
from sqlalchemy import func, and_
import random
import logging
import uuid

from utils.shared import add_team_message
from utils.shared import degrade_gear
from utils.api_calls import generate_openai_question

questions_bp = Blueprint('questions', __name__)



@questions_bp.route('/npc_encounter/<int:quest_id>', methods=['GET'])
def npc_encounter(quest_id):
    excerpt = get_random_excerpt_from_textbook(quest_id)

    if should_use_api():
        question = generate_openai_question(excerpt)
        source = "openai"
    else:
        question = get_question_from_db(quest_id)
        source = "db"

    return render_template("npc_encounter.html", question=question, source=source)


@questions_bp.route('/handle_true_false_question', methods=['POST'])
def handle_true_false_question():
    """Allows the player to defeat the enemy by answering a True/False question."""
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    enemy     = flask_session.get("enemy", {})
    has_weapon= enemy.get("has_weapon", False)
    win_msg = []

    if not all([squire_id, quest_id, enemy]):
        return jsonify(success=False,
                       message="Session expired. Please log in again."), 400

    db = db_session()
    try:
        # 1) Fetch a random True/False question not yet seen twice
        #    (assumes your SquireQuestion model has a times_encountered field)
        tq = (
            db.query(
                TrueFalseQuestion.id,
                TrueFalseQuestion.question,
                TrueFalseQuestion.correct_answer
            )
            .outerjoin(
                SquireQuestion,
                and_(
                    SquireQuestion.question_id == TrueFalseQuestion.id,
                    SquireQuestion.squire_id  == squire_id
                )
            )
            .filter(
                TrueFalseQuestion.quest_id == quest_id,
                # either never seen or seen fewer than 2 times
                (SquireQuestion.times_encountered == None) |
                (SquireQuestion.times_encountered < 2)
            )
            .order_by(func.rand())
            .first()
        )

        # 2) No question available
        if not tq:
            if not has_weapon:
                # force flee: lose XP and damage gear
                degrade_gear(squire_id, "zip")
                squire = db.query(Squire).get(squire_id)
                squire.experience_points = max(0, squire.experience_points - 10)
                db.commit()

                flee_msg = (
                    "🛑 The enemy forces you to flee because you are unarmed.\n"
                    "❌ You lose 10 XP and your gear is damaged."
                )
                flask_session['message'] = flee_msg

                return jsonify(
                    success=False,
                    message=flee_msg,
                    flee=True
                )

            # armed but no question left
            return jsonify(
                success=False,
                message="❌ No question available. You must fight!",
                redirect=url_for("ajax_handle_combat")
            )

        # 3) Validate answer
        user_answer = request.json.get("answer", "").strip().upper()
        if user_answer not in ("T", "F"):
            return jsonify(
                success=False,
                message="Invalid answer. Please submit 'T' or 'F'."
            ), 400

        correct_bool = bool(tq.correct_answer)
        is_correct = (user_answer == "T" and correct_bool) or \
                     (user_answer == "F" and not correct_bool)

        # 4) Handle correct
        if is_correct:
            xp_gain   = enemy['xp_reward']
            gold_gain = enemy['gold_reward']
            win_msg.append(update_squire_progress(db, squire_id, xp_gain, gold_gain))

            win_msg.append (
                f"✅ Correct! The enemy is defeated! "
                f"You gain {xp_gain} XP and {gold_gain} bits."
            )
            flask_session['message'] = win_msg

            # Broadcast to team
            toast = (
                f"{flask_session['squire_name']} defeated "
                f"{enemy['name']} and gained {xp_gain} XP "
                f"and {gold_gain} bits."
            )
            add_team_message(flask_session['team_id'], toast)

            db.commit()

            return jsonify(
                success=True,
                message=win_msg,
                xp_reward=xp_gain,
                gold_reward=gold_gain,
                defeated=True,
                leveled_up=flask_session.get("leveled_up", False)
            )

        # 5) Handle incorrect
        if has_weapon:
            # still armed, can retry/fight
            return jsonify(
                success=False,
                message="❌ Wrong answer! En Garde!",
                redirect=url_for("ajax_handle_combat")
            )

        # unarmed & wrong: forced to flee
        degrade_gear(squire_id, "zip")
        squire = db.query(Squire).get(squire_id)
        squire.experience_points = max(0, squire.experience_points - 10)
        db.commit()

        flee_msg = (
            "🛑 The enemy forces you to flee by your wrong answer.\n"
            "❌ You lose 10 XP and your gear is damaged."
        )
        flask_session['message'] = flee_msg

        return jsonify(
            success=False,
            message=flee_msg,
            flee=True
        )

    finally:
        db.close()

@questions_bp.route('/answer_question', methods=['GET'])
def answer_question():
    """Displays a True/False question before the player submits an answer."""
    squire_id = flask_session.get("squire_id")
    quest_id  = flask_session.get("quest_id")
    level = flask_session.get("level")
    pending_job  = flask_session.get("pending_job")

    if not (squire_id and quest_id):
        return redirect(url_for('login'))

    db = db_session()

    if pending_job:
        if pending_job["job_id"] > 2:
            question_type = random.choice(["true_false", "multiple_choice"])
        else:
            question_type = "true_false"

    else:
        enemy = flask_session.get("enemy")
        enemylevel = enemy["min_level"]

        if level > 2 and enemylevel > 2:
            question_type = random.choice(["true_false", "multiple_choice", "api_question"])
        else:
            question_type = "true_false"

    if question_type == "true_false":
        try:
            # 1) Total questions in this quest
            total_qs = (
                db.query(TrueFalseQuestion)
                  .filter(TrueFalseQuestion.quest_id == quest_id)
                  .count()
            )

            # 2) Which question_ids has this squire already encountered?
            answered_rows = (
                db.query(SquireQuestion.question_id)
                  .filter(
                      SquireQuestion.squire_id   == squire_id,
                      SquireQuestion.question_type == 'true_false'
                  )
                  # only consider those tied to this quest
                  .join(TrueFalseQuestion,
                        SquireQuestion.question_id == TrueFalseQuestion.id)
                  .filter(TrueFalseQuestion.quest_id == quest_id)
                  .all()
            )
            answered_ids = {qid for (qid,) in answered_rows}
            answered_count = len(answered_ids)

            # 3) Build the base query
            q = (
                db.query(
                    TrueFalseQuestion.id,
                    TrueFalseQuestion.question,
                    TrueFalseQuestion.correct_answer
                )
                .filter(TrueFalseQuestion.quest_id == quest_id)
            )

            # 4) If not yet answered all, exclude those already seen
            if answered_count < total_qs:
                q = q.filter(~TrueFalseQuestion.id.in_(answered_ids))

            # 5) Grab a random one
            question_row = q.order_by(func.rand()).first()

            # 6) No question left?
            if not question_row:
                flask_session["battle_summary"] = "No question available. You must fight!"
                return redirect(url_for("ajax_handle_combat"))

            # 7) Store for validation and render
            flask_session["current_question"] = {
                "id":   question_row.id,
                "text": question_row.question
            }
            return render_template(
                "answer_question.html",
                question={
                    "id":   question_row.id,
                    "question": question_row.question,
                    # note: template probably doesn’t need correct_answer
                }
            )
        finally:
            db.close()

    elif question_type == "api_question":

        try:
            q_data = generate_openai_question(quest_id)

            # Save it in session for validation
            flask_session["current_question"] = {
                "id": "api",  # No DB ID
                "type": "api_generated",
                "text": q_data["question"],
                "options": q_data["options"],
                "correct_answer": q_data["correct_answer"]
            }

            return render_template("answer_question_mc.html", question=flask_session["current_question"])
        except Exception as e:
            flask_session["battle_summary"] = f"OpenAI Error: {e}"
            return redirect(url_for("ajax_handle_combat"))

    else:
        # Grab answered multiple choice question IDs
        mc_answered_rows = (
            db.query(SquireQuestion.question_id)
              .filter(
                  SquireQuestion.squire_id == squire_id,
                  SquireQuestion.question_type == 'multiple_choice'
              )
              .join(MultipleChoiceQuestion,
                    SquireQuestion.question_id == MultipleChoiceQuestion.id)
              .filter(MultipleChoiceQuestion.quest_id == quest_id)
              .all()
        )
        mc_answered_ids = {qid for (qid,) in mc_answered_rows}
        mc_total_qs = (
            db.query(MultipleChoiceQuestion)
              .filter(MultipleChoiceQuestion.quest_id == quest_id)
              .count()
        )
        mc_q = (
            db.query(
                MultipleChoiceQuestion.id,
                MultipleChoiceQuestion.question_text,
                MultipleChoiceQuestion.optionA,
                MultipleChoiceQuestion.optionB,
                MultipleChoiceQuestion.optionC,
                MultipleChoiceQuestion.optionD,
                MultipleChoiceQuestion.correctAnswer
            )
            .filter(MultipleChoiceQuestion.quest_id == quest_id)
        )
        if len(mc_answered_ids) < mc_total_qs:
            mc_q = mc_q.filter(~MultipleChoiceQuestion.id.in_(mc_answered_ids))

        mc_question = mc_q.order_by(func.rand()).first()
        if not mc_question:
            flask_session["battle_summary"] = "No question available. You must fight!"
            return redirect(url_for("ajax_handle_combat"))

        flask_session["current_question"] = {
            "id": mc_question.id,
            "text": mc_question.question_text,
            "type": "multiple_choice",
            "options": {
                "A": mc_question.optionA,
                "B": mc_question.optionB,
                "C": mc_question.optionC,
                "D": mc_question.optionD
            }
        }
        return render_template("answer_question_mc.html", question=flask_session["current_question"])

@questions_bp.route('/check_true_false_question', methods=['POST'])
def check_true_false_question():
    """Validates the player's True/False answer."""
    squire_id    = flask_session.get("squire_id")
    question_id  = request.form.get("question_id")
    user_answer  = request.form.get("answer", "").strip().upper()
    enemy        = flask_session.get("enemy", {})
    pending_job  = flask_session.pop("pending_job", None)
    flask_session.pop("success", None)
    toast =[]

    if not (squire_id and question_id):
        flask_session["battle_summary"] = "Error: Missing session or question."
        return redirect(url_for("combat_results"))

    db = db_session()
    try:
        # 1) Load question
        q = db.query(TrueFalseQuestion).get(int(question_id))
        if not q:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat_results"))

        correct_int = 1 if q.correct_answer else 0
        user_int    = 1 if user_answer == "T" else 0

        logging.debug(f"TF Check: squire={squire_id}, qid={question_id}, "
                      f"user={user_int}, correct={correct_int}")

        # 2) Record as answered correctly if matches
        if user_int == correct_int:
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=q.id,
                      question_type='true_false'
                  )
                  .one_or_none()
            )
            if not sq:
                sq = SquireQuestion(
                    squire_id=squire_id,
                    question_id=q.id,
                    question_type='true_false',
                    answered_correctly=True
                )
                db.add(sq)
            else:
                sq.answered_correctly = True
            db.commit()

            # 3a) Pending job payout
            if pending_job:
                squire = db.query(Squire).get(squire_id)
                level  = squire.level
                payout = random.randint(
                    pending_job["min_payout"],
                    pending_job["max_payout"]
                ) * level

                # Pay team
                team = db.query(Team).get(squire.team_id)
                team.gold += payout
                # Increment work sessions
                squire.work_sessions += 1

                db.commit()

                msg = (f"✅ You completed '{pending_job['job_name']}' "
                       f"and earned 💰 {payout} bits!")
                flask_session["job_message"] = msg

                toast.append (f"{flask_session['squire_name']} completed "
                         f"'{pending_job['job_name']}' and earned 💰 {payout} bits.")
                add_team_message(squire.team_id, toast)

                return redirect(url_for("town.visit_town"))

            # 3b) Combat reward
            flask_session["forced_combat"] = False
            xp_gain   = enemy.get("xp_reward", 0)
            gold_gain = enemy.get("gold_reward", 0)
            toast.append(update_squire_progress(squire_id, xp_gain, gold_gain))

            toast.append (
                f"{flask_session['squire_name']} defeated "
                f"{enemy.get('name')} and gained "
                f"{xp_gain} XP and {gold_gain} bits."
            )
            message = " ".join([str(m) for m in toast if m])
            add_team_message(flask_session['team_id'], message)
            db.commit()

            flask_session["combat_result"] = (
                f"✅ Correct! You have defeated the enemy "
                f"and earned {xp_gain} XP and {gold_gain} bits."
            )
            flask_session["success"] = True
            if flask_session.get("leveled_up"):
                #return jsonify({"redirect": url_for("level_up")})
                return redirect(url_for("level_up"))

        else:
            # 4) Incorrect answer handling
            if question_id:
                question = db.query(TrueFalseQuestion).get(question_id)
                hint = question.hint if question else None
            else:
                hint = None

            if pending_job:
                flask_session["job_message"] = (
                    f"❌ Incorrect! You failed the task and earned nothing but this hint: {hint}."
                )
                return redirect(url_for("town.visit_town"))

            # Damage gear and penalize XP
            degrade_gear(squire_id, enemy.get("weakness"))
            squire = db.query(Squire).get(squire_id)
            squire.experience_points = max(
                0,
                squire.experience_points - enemy.get("xp_reward", 0)
            )
            db.commit()

            flask_session["combat_result"] = (
                f"❌ Incorrect! You are defeated by "
                f"{enemy.get('name')} and lose some experience points! \n"
                f"{hint}"
            )
            flask_session["success"] = False

        # 5) Show results
        return render_template(
            "combat_results.html",
            success=flask_session.pop("success", None),
            combat_result=flask_session.pop("combat_result", "")
        )
    finally:
        db.close()

#present questions
@questions_bp.route('/answer_MC_question', methods=['GET'])
def answer_MC_question():
    """Displays a random multiple‐choice question for boss combat."""
    boss       = flask_session.get('boss')
    squire_id  = flask_session.get("squire_id")
    quest_id   = flask_session.get("quest_id")

    if not (boss and squire_id and quest_id):
        return redirect(url_for("login"))

    # pull in hunger if needed elsewhere
    player_current_hunger = flask_session.get("player_current_hunger")
    boss_current_hunger   = flask_session.get("boss_current_hunger")

    db = db_session()
    try:
        # 1) Find which MC questions this squire has already seen
        answered_rows = (
            db.query(SquireQuestion.question_id)
              .filter(
                  SquireQuestion.squire_id    == squire_id,
                  SquireQuestion.question_type == 'multiple_choice'
              )
              .all()
        )
        answered_ids = {qid for (qid,) in answered_rows}

        # 2) Fetch a random MCQ with quest_id < current and not yet seen
        mcq = (
            db.query(MultipleChoiceQuestion)
              .filter(
                  MultipleChoiceQuestion.quest_id < quest_id,
                  ~MultipleChoiceQuestion.id.in_(answered_ids)
              )
              .order_by(func.rand())
              .first()
        )

        if not mcq:
            flask_session["battle_summary"] = "No question available. You must flee!"
            return redirect(url_for("ajax_handle_boss_combat"))

        # 3) Store for validation in session
        flask_session["current_question"] = {
            "id":            mcq.id,
            "text":          mcq.question_text,
            "optionA":       mcq.optionA,
            "optionB":       mcq.optionB,
            "optionC":       mcq.optionC,
            "optionD":       mcq.optionD,
            "correctAnswer": mcq.correctAnswer
        }

        return render_template('boss_combat.html', boss=boss)

    finally:
        db.close()


#then need a route to check if the question was answered correctly so that that can be recorded as either
#increasing the player's hunger or the enemy's hunger
@questions_bp.route('/check_MC_question', methods=['POST'])
def check_MC_question():
    """Validates the player's multiple-choice answer for boss combat."""
    boss               = flask_session.get('boss', {})
    squire_id          = flask_session.get('squire_id')
    question_id        = request.form.get("question_id", type=int)
    user_answer        = request.form.get("selected_option")
    player_hunger      = flask_session.get("player_current_hunger", 0)
    boss_hunger        = flask_session.get("boss_current_hunger", 0)
    player_max_hunger  = flask_session.get("player_max_hunger", 0)
    boss_max_hunger    = flask_session.get("boss_max_hunger", 0)

    logging.debug(f"Check_MC_question qid/user_answer {question_id}/{user_answer}")
    db = db_session()
    try:
        # 1) Load the MC question
        mcq = db.query(MultipleChoiceQuestion).get(question_id)
        if not mcq:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat_results"))

        # 2) Determine correctness
        correct = (user_answer == mcq.correctAnswer)

        # 3) Record attempt if correct
        if correct:
            # Upsert SquireQuestion
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=mcq.id,
                      question_type='multiple_choice'
                  )
                  .one_or_none()
            )
            if not sq:
                sq = SquireQuestion(
                    squire_id=squire_id,
                    question_id=mcq.id,
                    question_type='multiple_choice',
                    answered_correctly=True
                )
                db.add(sq)
            else:
                sq.answered_correctly = True
            db.commit()

            # 4a) Increase boss hunger
            boss_hunger += 1
            flask_session["boss_current_hunger"] = boss_hunger
            flask_session["question_id"] = None
            enemy_message = f"💥 Good Answer! {boss.get('name')} is getting hungrier."
            flask_session["enemy_message"] = enemy_message

        else:
            # 4b) Player hunger
            player_hunger += 1
            flask_session["player_current_hunger"] = player_hunger
            flask_session["question_id"] = None
            player_message = "❌ Not good, Squire! You are getting hungrier."
            flask_session["player_message"] = player_message

        # 5) Check victory: boss too hungry
        if boss_hunger >= boss_max_hunger:
            flask_session["boss_defeated"] = True
            xp = boss.get("xp_reward", 0)
            gold = boss.get("gold_reward", 0)
            result.append(update_squire_progress(db, squire_id, xp, gold))

            result.append (
                f"🍕 The {boss.get('name')} is too hungry to continue! "
                f"They run off to eat a pizza.\nYou gain {xp} XP and {gold} bits."
            )

            message = " ".join([str(m) for m in result if m])

            flask_session["combat_result"] = message

            # Clean up combat state
            for key in ("boss", "player_current_hunger", "boss_current_hunger"):
                flask_session.pop(key, None)

            toast = (
                f"{flask_session['squire_name']} defeated {boss.get('name')} "
                f"and gained {xp} XP and {gold} bits."
            )
            add_team_message(flask_session['team_id'], toast)
            db.commit()
            return redirect(url_for("combat_results"))

        # 6) Check defeat: player too hungry
        if player_hunger >= player_max_hunger:
            degrade_gear(squire_id, boss.get("weakness"))
            squire = db.query(Squire).get(squire_id)
            squire.experience_points = max(0, squire.experience_points - 100)
            db.commit()

            flask_session["combat_result"] = (
                "🛑 You are too hungry to continue fighting! "
                "The enemy forces you to flee.\n❌ You lose 100 XP."
            )
            for key in ("boss", "player_current_hunger", "boss_current_hunger"):
                flask_session.pop(key, None)
            return redirect(url_for("combat_results"))

        # 7) Continue boss combat
        return redirect(url_for("boss_combat"))

    finally:
        db.close()

@questions_bp.route('/check_MC_question_enemy', methods=['POST'])
def check_MC_question_enemy():
    """Validates the player's True/False answer."""
    squire_id    = flask_session.get("squire_id")
    enemy        = flask_session.get("enemy", {})
    pending_job  = flask_session.pop("pending_job", None)
    user_answer  = request.form.get("answer", "").strip().upper()
    question_id  = request.form.get("question_id")

    flask_session.pop("success", None)

    db = db_session()

    logging.debug(f"Check_MC_question qid/user_answer {question_id}/{user_answer}")

    if not (squire_id and question_id):
        flask_session["battle_summary"] = "Error: Missing session or question."
        return redirect(url_for("combat.combat_results"))

    if question_id == "api":
        try:
            toast =[]

            current_q = flask_session.get("current_question")
            if not current_q:
                flask_session["combat_result"] = "Error: Question not found in session."
                return redirect(url_for("combat.combat_results"))

            correct = (user_answer == current_q["correct_answer"])

            if correct:
                # Maybe add a new table: SquireApiQuestion (squire_id, question_text, answered_correctly, timestamp)
                sq = SquireQuestion (
                    squire_id=squire_id,
                    question_id=-int(uuid.uuid4().int % 1000000000),
                    question_type='multiple_choice',
                    answered_correctly=True,
                    is_api=True
                )
                db.add(sq)

                # Reputation gain? Bits?
                team = db.query(Team).get(flask_session['team_id'])
                team.reputation += 1
                db.commit()

                # 3b) Combat reward
                flask_session["forced_combat"] = False
                xp_gain   = enemy.get("xp_reward", 0)
                gold_gain = enemy.get("gold_reward", 0)
                toast.append(update_squire_progress(squire_id, xp_gain, gold_gain))

                toast.append (
                    f"{flask_session['squire_name']} defeated "
                    f"{enemy.get('name')} and gained "
                    f"{xp_gain} XP and {gold_gain} bits."
                )
                message = " ".join([str(m) for m in toast if m])
                add_team_message(flask_session['team_id'], message)
                db.commit()

                flask_session["combat_result"] = (
                    f"✅ Correct! You have defeated the enemy "
                    f"and earned {xp_gain} XP and {gold_gain} bits."
                )
                flask_session["success"] = True

            else:
                # Damage gear and penalize XP
                degrade_gear(squire_id, enemy.get("weakness"))
                squire = db.query(Squire).get(squire_id)
                squire.experience_points = max(
                    0,
                    squire.experience_points - enemy.get("xp_reward", 0)
                )
                db.commit()

                flask_session["combat_result"] = (
                    f"❌ Incorrect! You are defeated by "
                    f"{enemy.get('name')} and lose some experience points! \n"
                )
                flask_session["success"] = False

            return render_template(
                "combat_results.html",
                success=flask_session.pop("success", None),
                combat_result=flask_session.pop("combat_result", ""))
        except Exception as e:
            logging.error(f"There was a problem with the API MC submission: {e}")
        finally:
            db.close()


    toast =[]

    try:
        # 1) Load the MC question
        mcq = db.query(MultipleChoiceQuestion).get(question_id)
        if not mcq:
            flask_session["battle_summary"] = "Error: Question not found."
            return redirect(url_for("combat.combat_results"))

        # 2) Determine correctness
        correct = (user_answer == mcq.correctAnswer)

        # 3) Record attempt if correct
        if correct:
            # Upsert SquireQuestion
            sq = (
                db.query(SquireQuestion)
                  .filter_by(
                      squire_id=squire_id,
                      question_id=mcq.id,
                      question_type='multiple_choice'
                  )
                  .one_or_none()
            )
            if not sq:
                sq = SquireQuestion(
                    squire_id=squire_id,
                    question_id=mcq.id,
                    question_type='multiple_choice',
                    answered_correctly=True
                )
                db.add(sq)
            else:
                sq.answered_correctly = True
            db.commit()

            # 3a) Pending job payout
            if pending_job:
                squire = db.query(Squire).get(squire_id)
                level  = squire.level
                payout = random.randint(
                    pending_job["min_payout"],
                    pending_job["max_payout"]
                ) * level

                # Pay team
                team = db.query(Team).get(squire.team_id)
                team.gold += payout
                # Increment work sessions
                squire.work_sessions += 1

                db.commit()

                msg = (f"✅ You completed '{pending_job['job_name']}' "
                       f"and earned 💰 {payout} bits!")
                flask_session["job_message"] = msg

                toast.append (f"{flask_session['squire_name']} completed "
                         f"'{pending_job['job_name']}' and earned 💰 {payout} bits.")
                add_team_message(squire.team_id, toast)

                return redirect(url_for("town.visit_town"))

            # 3b) Combat reward
            flask_session["forced_combat"] = False
            xp_gain   = enemy.get("xp_reward", 0)
            gold_gain = enemy.get("gold_reward", 0)
            toast.append(update_squire_progress(squire_id, xp_gain, gold_gain))

            toast.append (
                f"{flask_session['squire_name']} defeated "
                f"{enemy.get('name')} and gained "
                f"{xp_gain} XP and {gold_gain} bits."
            )
            message = " ".join([str(m) for m in toast if m])
            add_team_message(flask_session['team_id'], message)
            db.commit()

            flask_session["combat_result"] = (
                f"✅ Correct! You have defeated the enemy "
                f"and earned {xp_gain} XP and {gold_gain} bits."
            )
            flask_session["success"] = True

            return redirect(url_for("combat.combat_results"))

        else:
            if question_id:
                question = db.query(MultipleChoiceQuestion).get(question_id)
                hint = question.hint if question else None
            else:
                hint = None

            if pending_job:
                flask_session["job_message"] = (
                    f"❌ Incorrect! You failed the task and earned nothing except this hint: {hint}."
                )
                return redirect(url_for("town.visit_town"))

            # Damage gear and penalize XP
            degrade_gear(squire_id, enemy.get("weakness"))
            squire = db.query(Squire).get(squire_id)
            squire.experience_points = max(
                0,
                squire.experience_points - enemy.get("xp_reward", 0)
            )
            db.commit()

            flask_session["combat_result"] = (
                f"❌ Incorrect! You are defeated by "
                f"{enemy.get('name')} and lose some experience points! \n"
                f"{hint}"
            )
            flask_session["success"] = False

        return render_template(
            "combat_results.html",
            success=flask_session.pop("success", None),
            combat_result=flask_session.pop("combat_result", ""))

    finally:
        db.close()
