import random
import logging
import pymysql
import os
import decimal
import configparser
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
from db import (
    Squire, Course, Team, engine, db_session, Team, TravelHistory, Quest,
    SquireQuestion, SquireRiddleProgress, Riddle, Enemy, Inventory, WizardItem,
    Job, MapFeature, MultipleChoiceQuestion, TrueFalseQuestion, ShopItem, SquireQuestStatus,
    TeamMessage, TreasureChest, XpThreshold, ChestHint, SquireQuestionAttempt,
    MapNode, Skill, SquireSkillPoint, EnemySkillSusceptibility
    )

from sqlalchemy import or_, func, and_, asc, not_, desc, select, case
from sqlalchemy.orm import Session
from sqlalchemy.dialects.mysql import insert
from decimal import Decimal
import re
import math
from typing import Dict, Tuple
import json

def update_squire_progress(squire_id: int, xp_gain: int, gold_gain: int) -> list[str]:
    """
    Adds XP and gold to the squire (and their team), then checks for level-up.
    Returns a list of messages indicating what happened (e.g., level-up).
    """
    messages = []
    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return messages

        # Update XP
        squire.experience_points = (squire.experience_points or 0) + xp_gain
        # Update Team gold
        team = db.query(Team).get(squire.team_id)
        if team:
            team.gold = (team.gold or 0) + gold_gain
            team.reputation += 1

        db.commit()

        # Level-up check
        new_level = check_for_level_up(squire_id,db)
        if new_level is not None:
            session["leveled_up"] = True
            session["new_level"] = new_level

    finally:
        db.close()

def check_for_level_up(squire_id: int, db) -> int | None:
    squire = db.query(Squire).get(squire_id)
    xp = squire.experience_points or 0
    current_level = squire.level

    thresholds = ( db.query(XpThreshold)
        .order_by(XpThreshold.level.asc())
        .all()
        )

    for threshold in thresholds:
        if current_level < threshold.level and xp >= threshold.min:
            squire.level = threshold.level
            db.commit()
            return threshold.level
    return None
# Load environment variables
load_dotenv()

# ************************************
# This Python Script created 3/4/25 TF
# This script contains consolidated functions for use by the game play
# ************************************

# --------------------------------- Initialization Functions

def generate_random_coordinates(difficulty):
    """Assigns a treasure chest location based on riddle difficulty."""
    if difficulty == "Easy":
        return random.randint(-10, 10), random.randint(-10, 10)
    elif difficulty == "Medium":
        return random.randint(-20, 20), random.randint(-20, 20)
    else:  # Hard
        return random.randint(-35, 35), random.randint(-35, 35)

def generate_rewards(difficulty,level):
    """Assigns rewards based on riddle difficulty."""

    db = db_session()

    medium_special = (
        db.query(ShopItem.item_name)
        .filter(ShopItem.item_type.ilike('gear'))
        .filter(ShopItem.min_level <= level)
        .all()
    )
    medium_special = [item[0] for item in medium_special]
    print("Available medium special items:", medium_special)

    hard_special = (
        db.query(WizardItem.item_name)
        .filter(WizardItem.min_level <= level)
        .all()

    )

    hard_special = [item[0] for item in hard_special]

    if difficulty == "Easy":
        return random.randint(10, 20), random.randint(5, 15), random.randint(5, 10), None
    elif difficulty == "Medium":
        special = random.choice(medium_special + [None]) if medium_special else None
        return random.randint(25, 40), random.randint(15, 25), random.randint(10, 20), special
    else:  # Hard
        special = random.choice(hard_special + [None]) if hard_special else None
        return random.randint(50, 75), random.randint(30, 50), random.randint(15, 30), special


def insert_treasure_chests(quest_id: int, squire_quest_id: int, level: int) -> str:
    """
    Inserts a TreasureChest record for each Riddle in the given quest
    that doesn’t already have a chest for this squire_quest_id.
    Returns a status message.
    """
    db = db_session()
    message = "No new treasure chests created for this quest, Squire."
    try:
        # 1) Find riddle IDs already used for this squire’s quest
        existing = (
            db.query(TreasureChest.riddle_id)
              .filter(TreasureChest.squire_quest_id == squire_quest_id)
              .subquery()
        )
        # 2) Query all other riddles for this quest
        riddles = (
            db.query(Riddle.id, Riddle.difficulty)
              .filter(
                  Riddle.quest_id == quest_id,
                  not_(Riddle.id.in_(select(existing)))
              )
              .all()
        )

        # 3) Insert chests for each missing riddle
        for riddle_id, difficulty in riddles:
            x, y = generate_random_coordinates(difficulty)
            gold, xp, food, special_item = generate_rewards(difficulty, level)

            chest = TreasureChest(
                x_coordinate     = x,
                y_coordinate     = y,
                riddle_id        = riddle_id,
                gold_reward      = gold,
                xp_reward        = xp,
                food_reward      = food,
                special_item     = special_item,
                squire_quest_id  = squire_quest_id
            )
            db.add(chest)

        if riddles:
            db.commit()
            message = "✅ Treasure chests inserted successfully!"
        return message

    except Exception as e:
        db.rollback()
        logging.warning(f"Error inserting treasure chests for quest {quest_id}, squire_quest {squire_quest_id}: {e}")
        return f"⚠️ Failed to insert new treasure chests: {e}"
    finally:
        db.close()

# Example:
# msg = insert_treasure_chests_orm(quest_id=15, squire_quest_id=42)
# print(msg)
"""
This section is an enhancement to include road networks in the game design
and also to increase zoning of risks for players based on distance from home 0,0
"""

def calculate_feature_counts_advanced(
    level: int,
    quest_id: int,
    existing_features: Dict[str, int] = None,
    quest_destinations: list = None,
    force_generation: bool = False
) -> Tuple[int, int, int, dict]:
    """
    Advanced terrain scaling based on accessible area and optimal density.

    Returns: (forest_count, mountain_count, river_segments, zone_info)
    """
    if existing_features is None:
        existing_features = {'forest': 0, 'mountain': 0, 'river': 0}

    if quest_destinations is None:
        # Default quest destinations based on level
        quest_destinations = [
            (40 + level, 40 + level),      # Tournament
            (-35 - level, -35 - level),    # Dungeon
            (30 + level//2, -25 - level//2) # Boss fight
        ]

    # Calculate accessible radius based on level progression
    accessible_radius = min(50, 12 + level * 1.8)
    accessible_area = math.pi * accessible_radius * accessible_radius

    # Define optimal terrain density zones
    zone_definitions = {
        'town_center': {'radius': 8, 'forest': 0.01, 'mountain': 0.005, 'river': 0.02},
        'inner_safe': {'radius': 18, 'forest': 0.06, 'mountain': 0.03, 'river': 0.015},
        'middle_zone': {'radius': 30, 'forest': 0.12, 'mountain': 0.06, 'river': 0.01},
        'outer_zone': {'radius': 42, 'forest': 0.20, 'mountain': 0.12, 'river': 0.008},
        'frontier': {'radius': 50, 'forest': 0.28, 'mountain': 0.18, 'river': 0.005}
    }

    # Complexity multiplier based on quest progression (diminishing returns)
    complexity_factor = 1

    # Calculate target features for each accessible zone
    target_forests = 0
    target_mountains = 0
    target_rivers = 0
    zone_info = {}

    prev_radius = 0
    for zone_name, zone_data in zone_definitions.items():
        zone_radius = zone_data['radius']

        # Only process zones within accessible radius
        if prev_radius < accessible_radius:
            # Calculate area of this zone ring
            outer_area = math.pi * min(zone_radius, accessible_radius) ** 2
            inner_area = math.pi * prev_radius ** 2
            zone_area = max(0, outer_area - inner_area)

            if zone_area > 0:
                # Apply complexity scaling with caps
                forest_density = min(0.35, zone_data['forest'] * complexity_factor)
                mountain_density = min(0.25, zone_data['mountain'] * complexity_factor)
                river_density = zone_data['river']  # Rivers scale less

                zone_forests = int(zone_area * forest_density)
                zone_mountains = int(zone_area * mountain_density)
                zone_rivers = int(zone_area * river_density)

                target_forests += zone_forests
                target_mountains += zone_mountains
                target_rivers += zone_rivers

                zone_info[zone_name] = {
                    'area': zone_area,
                    'forests': zone_forests,
                    'mountains': zone_mountains,
                    'rivers': zone_rivers,
                    'density': forest_density + mountain_density
                }

        prev_radius = zone_radius

     # STABILIZATION LOGIC: Only add terrain when significantly under target
    current_forests = existing_features.get('forest', 0)
    current_mountains = existing_features.get('mountain', 0)
    current_rivers = existing_features.get('river', 0)

    # Define "deficit threshold" - only add terrain if we're significantly under target
    deficit_threshold = 0.15  # Only add if we're 15%+ below target

    forest_ratio = current_forests / max(target_forests, 1)
    mountain_ratio = current_mountains / max(target_mountains, 1)
    river_ratio = current_rivers / max(target_rivers, 1)

    # Calculate new terrain needed (with stabilization)
    if force_generation or forest_ratio < (1.0 - deficit_threshold):
        new_forests = max(0, target_forests - current_forests)
    else:
        new_forests = 0  # Sufficient terrain exists

    if force_generation or mountain_ratio < (1.0 - deficit_threshold):
        new_mountains = max(0, target_mountains - current_mountains)
    else:
        new_mountains = 0

    if force_generation or river_ratio < (1.0 - deficit_threshold):
        new_rivers = max(0, target_rivers - current_rivers)
    else:
        new_rivers = 0

    # Conservative caps to prevent runaway growth
    max_total_features = int(accessible_area * 0.20)  # Reduced from 25% to 20%
    current_total = current_forests + current_mountains + current_rivers
    new_total = new_forests + new_mountains + new_rivers

    if current_total + new_total > max_total_features:
        # We're at capacity - don't add more terrain
        scale_factor = max(0, (max_total_features - current_total) / max(new_total, 1))
        new_forests = int(new_forests * scale_factor)
        new_mountains = int(new_mountains * scale_factor)
        new_rivers = int(new_rivers * scale_factor)

    zone_info['summary'] = {
        'accessible_radius': accessible_radius,
        'accessible_area': accessible_area,
        'target_terrain': target_forests + target_mountains + target_rivers,
        'existing_terrain': current_total,
        'new_terrain': new_forests + new_mountains + new_rivers,
        'terrain_density': (current_total + new_forests + new_mountains + new_rivers) / accessible_area,
        'stabilization_active': not force_generation,
        'forest_ratio': forest_ratio,
        'mountain_ratio': mountain_ratio,
        'river_ratio': river_ratio,
        'quest_destinations': quest_destinations
    }

    return new_forests, new_mountains, new_rivers, zone_info

def should_generate_terrain(existing_features: Dict[str, int], level: int, last_terrain_generation_level: int = None) -> bool:
    """
    Determine if terrain generation is actually needed.
    Prevents unnecessary terrain generation on every quest.
    """
    # Always generate on first quest
    if not existing_features or sum(existing_features.values()) == 0:
        return True

    # Generate if player has leveled up significantly since last terrain generation
    if last_terrain_generation_level and level > last_terrain_generation_level + 2:
        return True

    # Generate if terrain is very sparse for current level
    accessible_radius = min(50, 12 + level * 1.8)
    accessible_area = math.pi * accessible_radius * accessible_radius
    current_density = sum(existing_features.values()) / accessible_area

    # Generate if density is below 5% (very sparse)
    return current_density < 0.05


def analyze_terrain_stability(existing_features: Dict[str, int], level: int, quest_id: int) -> dict:
    """
    Analyze current terrain state and recommend actions.
    """
    accessible_radius = min(50, 12 + level * 1.8)
    accessible_area = math.pi * accessible_radius * accessible_radius
    current_total = sum(existing_features.values())
    current_density = current_total / accessible_area

    # Calculate what density should be for this level
    target_density = min(0.20, 0.05 + level * 0.006)  # Gradual increase to 20% max

    analysis = {
        'current_density': current_density,
        'target_density': target_density,
        'is_stable': abs(current_density - target_density) < 0.05,
        'is_overcrowded': current_density > 0.25,
        'is_sparse': current_density < target_density * 0.7,
        'accessible_radius': accessible_radius,
        'recommendation': 'maintain'
    }

    if analysis['is_overcrowded']:
        analysis['recommendation'] = 'cleanup_old_terrain'
    elif analysis['is_sparse']:
        analysis['recommendation'] = 'add_terrain'
    elif analysis['is_stable']:
        analysis['recommendation'] = 'no_action_needed'

    return analysis

def enhanced_quest_start_with_stability_check(session, squire_id: int, squire_quest_id: int):
    """
    Improved quest start that only generates terrain when actually needed.
    """
    # Get current state
    level = session.query(Squire.level).filter(Squire.id == squire_id).scalar()
    existing_features = get_existing_features_from_db(session, squire_id)

    # Analyze if terrain generation is needed
    stability_analysis = analyze_terrain_stability(existing_features, level, squire_quest_id)

    print(f"Terrain Analysis for Level {level}:")
    print(f"  Current density: {stability_analysis['current_density']:.1%}")
    print(f"  Target density: {stability_analysis['target_density']:.1%}")
    print(f"  Recommendation: {stability_analysis['recommendation']}")

    # Only generate terrain if actually needed
    if stability_analysis['recommendation'] in ['add_terrain', 'cleanup_old_terrain']:

        if stability_analysis['recommendation'] == 'add_terrain':
            # Generate new terrain
            #quest_destinations = get_quest_destinations_from_db(session, squire_id, level)
            quest_destinations = {(40,40),(-35,-35),(-25,50)}
            new_forests, new_mountains, new_rivers, zone_info = calculate_feature_counts_advanced(
                level=level,
                quest_id=squire_quest_id,
                existing_features=existing_features,
                quest_destinations=None,
                force_generation=False  # Use stabilization logic
            )

            if new_forests + new_mountains + new_rivers > 0:
                print(f"Adding {new_forests + new_mountains + new_rivers} new terrain features")
                # Proceed with terrain generation...
            else:
                print("Terrain is adequate - no new features needed")

        elif stability_analysis['recommendation'] == 'cleanup_old_terrain':
            print("Terrain overcrowded - consider cleanup (not implemented yet)")
            # Could implement terrain cleanup here if needed

    else:
        print("Terrain is stable - skipping generation")

    return stability_analysis

def get_existing_features_from_db(session: Session, squire_id: int) -> Dict[str, int]:
    """
    Query MapFeature table and convert to dictionary format for terrain scaling.

    Returns: {'forest': count, 'mountain': count, 'river': count, 'road': count, ...}
    """
    # Query terrain type counts for this squire
    terrain_counts = session.query(
        MapFeature.terrain_type,
        func.count(MapFeature.id).label('count')
    ).filter(
        MapFeature.squire_id == squire_id
    ).group_by(
        MapFeature.terrain_type
    ).all()

    # Convert to dictionary with all terrain types initialized to 0
    existing_features = {
        'forest': 0,
        'mountain': 0,
        'river': 0,
        'road': 0,
        'bridge': 0,
        'waypoint': 0,
        # Add any other terrain types your game uses
    }

    # Update with actual counts from database
    for terrain_type, count in terrain_counts:
        existing_features[terrain_type] = count

    return existing_features

def calculate_destination_features(destinations: list, accessible_radius: float, level: int) -> dict:
    """
    Add strategic terrain features near quest destinations.
    Creates challenging approaches to important locations.
    """
    bonus_features = {'forests': 0, 'mountains': 0}

    for dest_x, dest_y in destinations:
        distance_from_town = math.sqrt(dest_x**2 + dest_y**2)

        # Only add features for destinations within accessible radius
        if distance_from_town <= accessible_radius:
            # Add defensive terrain around destinations
            if distance_from_town > 20:  # Don't add near town
                # Forests for ambush encounters near destinations
                bonus_features['forests'] += min(8, level // 3)
                # Mountains for challenging terrain
                bonus_features['mountains'] += min(5, level // 4)

    return bonus_features


def analyze_terrain_distribution(zone_info: dict) -> str:
    """
    Generate a summary of terrain distribution for debugging/balancing.
    """
    summary = zone_info.get('summary', {})

    analysis = f"""
Terrain Distribution Analysis:
============================
Accessible Radius: {summary.get('accessible_radius', 0):.1f} units
Accessible Area: {summary.get('accessible_area', 0):.0f} tiles
Total Features: {summary.get('total_features', 0)}
Terrain Density: {summary.get('terrain_density', 0):.1%}
Complexity Factor: {summary.get('complexity_factor', 1):.2f}

Zone Breakdown:
"""

    for zone_name, zone_data in zone_info.items():
        if zone_name != 'summary':
            analysis += f"  {zone_name}: {zone_data['forests']}F + {zone_data['mountains']}M in {zone_data['area']:.0f} tiles ({zone_data['density']:.1%} density)\n"

    return analysis


def get_expansion_strategy(level: int, quest_id: int) -> dict:
    """
    Returns strategic guidance for terrain placement.
    """
    accessible_radius = min(50, 12 + level * 1.8)

    if level <= 5:
        strategy = "Early Game: Focus on creating safe corridors with sparse strategic terrain"
        priorities = ["Clear roads to nearby areas", "Minimal forest clusters", "Safe river crossings"]
    elif level <= 15:
        strategy = "Mid Game: Expand terrain complexity, add challenge zones"
        priorities = ["Medium-density terrain rings", "Strategic barriers", "Quest destination approaches"]
    else:
        strategy = "Late Game: Full world complexity with dangerous frontier zones"
        priorities = ["High-density outer zones", "Challenging quest approaches", "Wilderness survival areas"]

    return {
        'strategy': strategy,
        'priorities': priorities,
        'accessible_radius': accessible_radius,
        'recommended_road_density': max(0.05, 0.15 - (accessible_radius - 15) * 0.002),
        'recommended_waypoint_spacing': 8 + level // 3
    }

def generate_terrain_features_with_roads(
    session: Session,
    squire_id: int,
    squire_quest_id: int,
    boss_locations: list = None,
    num_forest_clusters: int = 5,
    cluster_size: int = 10,
    max_forests: int = 75,
    num_mountain_ranges: int = 3,
    mountain_range_length: int = 9,
    max_mountains: int = 45,
):
    """
    Enhanced terrain generation that includes roads, bridges, and waypoints.
    Roads prefer open terrain and create bridges over rivers.
    Main roads head toward boss fight locations.
    """

    placed_in_cluster = 0
    forests_from_pinned = 0

    # Default boss locations if not provided
    if boss_locations is None:
        level = session.query(Squire.level).filter(Squire.id == squire_id).scalar()
        # Boss locations get further away with level
        boss_locations = [
            (40 + level * 2, 40 + level * 2),
            (-35 - level * 2, -35 - level * 2),
            (30 + level, -25 - level)
        ]

    # 1. Generate base terrain (existing code)
    level = session.query(Squire.level).filter(Squire.id == squire_id).scalar()
    placement_radius = 10 + level * 2

    # Build restricted coordinates
    restricted = set(
        session.query(MapFeature.x_coordinate, MapFeature.y_coordinate)
        .filter(MapFeature.squire_id == squire_id)
        .all()
    )
    treasure_coords = session.query(TreasureChest.x_coordinate, TreasureChest.y_coordinate)\
        .filter(
            TreasureChest.squire_quest_id == squire_quest_id,
            TreasureChest.is_opened == False
        ).all()
    restricted.update(treasure_coords)
    restricted.update({ (0, 0), (40, 40), (-35, -35), (-25,50) })

    to_add = []  # collect new MapFeature instances

    # 2. Generate river (existing code)
    river_coords = set()
    river_exists = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='river').count()
    if river_exists == 0:
        x = -placement_radius
        y = random.randint(-placement_radius, placement_radius)
        for _ in range(25 + level * 2):
            if (x, y) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=x,
                    y_coordinate=y,
                    squire_id=squire_id,
                    terrain_type='river'
                ))
                restricted.add((x, y))
                river_coords.add((x, y))
            x += 1
            y += random.choice([-1, 0, 1])

    # 3. Generate forests (existing code)
    forest_coords = set()
    existing_forests = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='forest').count()
    forests_needed = max_forests - existing_forests
    clusters = min(num_forest_clusters, forests_needed // cluster_size)

    # Pinned forest clusters
    pinned_clusters = [(-35, -35), (40, 40), (-25, 50)]
    for pinned_cluster_center in pinned_clusters:
        pinned_cluster_size = min(cluster_size, forests_needed)
        for _ in range(pinned_cluster_size):
            fx = pinned_cluster_center[0] + random.randint(-2, 2)
            fy = pinned_cluster_center[1] + random.randint(-2, 2)
            if (fx, fy) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=fx,
                    y_coordinate=fy,
                    squire_id=squire_id,
                    terrain_type='forest'
                ))
                restricted.add((fx, fy))
                placed_in_cluster += 1
                forests_from_pinned += 1
                forest_coords.add((fx, fy))

    # Random forest clusters
    for _ in range(clusters):
        cx = random.randint(-placement_radius, placement_radius)
        cy = random.randint(-placement_radius, placement_radius)
        for _ in range(cluster_size):
            fx = cx + random.randint(-2, 2)
            fy = cy + random.randint(-2, 2)
            if len([f for f in to_add if f.terrain_type=='forest']) >= forests_needed:
                break
            if (fx, fy) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=fx,
                    y_coordinate=fy,
                    squire_id=squire_id,
                    terrain_type='forest'
                ))
                restricted.add((fx, fy))
                forest_coords.add((fx, fy))

    # 4. Generate mountains (existing code)
    mountain_coords = set()
    existing_mountains = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='mountain').count()
    mountains_needed = max_mountains - existing_mountains
    ranges = min(num_mountain_ranges, mountains_needed // mountain_range_length)
    for _ in range(ranges):
        mx = random.randint(-placement_radius, placement_radius)
        my = random.randint(-placement_radius, placement_radius)
        horizontal = random.choice([True, False])
        for i in range(mountain_range_length):
            x = mx + (i if horizontal else 0)
            y = my + (0 if horizontal else i)
            if len([m for m in to_add if m.terrain_type=='mountain']) >= mountains_needed:
                break
            if (x, y) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=x,
                    y_coordinate=y,
                    squire_id=squire_id,
                    terrain_type='mountain'
                ))
                restricted.add((x, y))
                mountain_coords.add((x, y))

    # 5. NEW: Generate road network
    starting_town = (0, 0)
    roads_and_bridges = generate_road_network(
        starting_town,
        boss_locations,
        restricted,
        river_coords,
        forest_coords,
        mountain_coords,
        placement_radius
    )

    # Add roads to the features
    for road_segment in roads_and_bridges['roads']:
        to_add.append(MapFeature(
            x_coordinate=road_segment['x'],
            y_coordinate=road_segment['y'],
            squire_id=squire_id,
            terrain_type='road',
            metadata=road_segment.get('metadata', '{}')  # Store road type, safety level
        ))

    # Add bridges to the features
    for bridge in roads_and_bridges['bridges']:
        to_add.append(MapFeature(
            x_coordinate=bridge['x'],
            y_coordinate=bridge['y'],
            squire_id=squire_id,
            terrain_type='bridge',
            metadata=json.dumps({
                'danger_level': bridge['danger_level'],
                'encounter_type': 'troll_bridge',
                'road_type': bridge['road_type']
            })
        ))

    # Add waypoints
    for waypoint in roads_and_bridges['waypoints']:
        to_add.append(MapFeature(
            x_coordinate=waypoint['x'],
            y_coordinate=waypoint['y'],
            squire_id=squire_id,
            terrain_type='waypoint',
            metadata=json.dumps({
                'services': waypoint['services'],
                'waypoint_type': waypoint['type']
            })
        ))

    # 6. Persist all features
    session.add_all(to_add)
    session.commit()

    return roads_and_bridges


def generate_road_network(starting_town, boss_locations, restricted, rivers, forests, mountains, placement_radius):
    """
    Generate a road network that:
    1. Connects starting town to boss locations
    2. Prefers open terrain (avoids forests/mountains)
    3. Creates bridges over rivers
    4. Includes waypoints for rest
    """
    roads = []
    bridges = []
    waypoints = []

    def is_passable_terrain(x, y):
        """Check if a coordinate can have a road (not mountain/forest/existing feature)"""
        coord = (x, y)
        if coord in restricted:
            return False
        if coord in mountains:
            return False
        if coord in forests:
            return False  # Roads avoid forests
        return True

    def is_river(x, y):
        return (x, y) in rivers

    def calculate_terrain_cost(x, y):
        """Calculate movement cost for road pathfinding"""
        if (x, y) in mountains:
            return 1000  # Impassable
        if (x, y) in forests:
            return 50    # Very expensive (dangerous)
        if (x, y) in rivers:
            return 10    # Moderate cost (requires bridge)
        if (x, y) in restricted:
            return 20    # Existing features
        return 1         # Open terrain (preferred)

    def create_road_path(start, end, road_type='main'):
        """Create a road path using simplified A* pathfinding"""
        start_x, start_y = start
        end_x, end_y = end

        # Simple direct path with obstacle avoidance
        path = []
        current_x, current_y = start_x, start_y
        path.append({'x': current_x, 'y': current_y, 'road_type': road_type})

        # Calculate total distance
        total_distance = abs(end_x - start_x) + abs(end_y - start_y)
        max_steps = int(total_distance * 1.5)  # Allow for detours

        for step in range(max_steps):
            if current_x == end_x and current_y == end_y:
                break

            # Calculate direction to target
            dx = 1 if end_x > current_x else (-1 if end_x < current_x else 0)
            dy = 1 if end_y > current_y else (-1 if end_y < current_y else 0)

            # Try preferred direction first
            next_moves = [(current_x + dx, current_y + dy)]

            # Add alternative moves if preferred is blocked
            if dx != 0:
                next_moves.extend([(current_x + dx, current_y), (current_x, current_y + dy)])
            if dy != 0:
                next_moves.extend([(current_x, current_y + dy), (current_x + dx, current_y)])

            # Add fallback moves
            next_moves.extend([
                (current_x + 1, current_y), (current_x - 1, current_y),
                (current_x, current_y + 1), (current_x, current_y - 1)
            ])

            # Choose best move
            best_move = None
            best_cost = float('inf')

            for next_x, next_y in next_moves:
                # Skip if already in path (avoid loops)
                if any(p['x'] == next_x and p['y'] == next_y for p in path[-5:]):
                    continue

                cost = calculate_terrain_cost(next_x, next_y)

                # Add distance to target to prefer moves toward goal
                distance_cost = abs(next_x - end_x) + abs(next_y - end_y)
                total_cost = cost + distance_cost * 0.1

                if total_cost < best_cost:
                    best_cost = total_cost
                    best_move = (next_x, next_y)

            if best_move is None:
                break  # No valid moves

            current_x, current_y = best_move

            # Handle river crossings
            if is_river(current_x, current_y):
                bridges.append({
                    'x': current_x,
                    'y': current_y,
                    'road_type': road_type,
                    'danger_level': 'high',
                    'encounter_type': 'troll_bridge'
                })

            path.append({
                'x': current_x,
                'y': current_y,
                'road_type': road_type,
                'metadata': json.dumps({
                    'safety_level': 'high' if road_type == 'trade' else 'medium',
                    'road_type': road_type
                })
            })

        return path

    # Create main roads to boss locations
    for i, boss_location in enumerate(boss_locations):
        road_path = create_road_path(starting_town, boss_location, f'boss_road_{i}')
        roads.extend(road_path)

        # Add waypoints every 10-15 segments on long roads
        if len(road_path) > 15:
            for j in range(10, len(road_path), 12):
                if j < len(road_path):
                    waypoint = road_path[j]
                    waypoints.append({
                        'x': waypoint['x'],
                        'y': waypoint['y'],
                        'type': 'waystone',
                        'services': ['rest', 'directions', 'basic_healing'],
                        'road_id': f'boss_road_{i}'
                    })

    # Create safer trade routes to intermediate locations
    trade_destinations = [
        (placement_radius // 2, placement_radius // 3),
        (-placement_radius // 3, placement_radius // 2),
        (placement_radius // 3, -placement_radius // 3)
    ]

    for i, trade_dest in enumerate(trade_destinations):
        # Only create if destination is in open terrain
        if is_passable_terrain(trade_dest[0], trade_dest[1]):
            trade_path = create_road_path(starting_town, trade_dest, f'trade_route_{i}')
            roads.extend(trade_path)

            # Trade routes get more frequent waypoints (safer)
            for j in range(8, len(trade_path), 10):
                if j < len(trade_path):
                    waypoint = trade_path[j]
                    waypoints.append({
                        'x': waypoint['x'],
                        'y': waypoint['y'],
                        'type': 'trade_post',
                        'services': ['rest', 'trading', 'guard_patrol', 'supplies'],
                        'road_id': f'trade_route_{i}'
                    })

    return {
        'roads': roads,
        'bridges': bridges,
        'waypoints': waypoints
    }
"""
End Design Enhancement
"""

def generate_terrain_features_dynamic(
    session: Session,
    squire_id: int,
    squire_quest_id: int,
    num_forest_clusters: int = 5,
    cluster_size: int = 10,
    max_forests: int = 75,
    num_mountain_ranges: int = 3,
    mountain_range_length: int = 9,
    max_mountains: int = 45,
):
    """
    ORM-based rewrite of dynamic terrain generation:
    - Rivers, forest clusters, and mountain ranges are placed around the map center.
    - Avoids overlapping existing map features and unopened treasure chests.
    """
    # 1. Fetch squire level
    level = session.query(Squire.level).filter(Squire.id == squire_id).scalar()
    placement_radius = 10 + level * 2

    # 2. Build restricted set of coordinates
    restricted = set(
        session.query(MapFeature.x_coordinate, MapFeature.y_coordinate)
        .filter(MapFeature.squire_id == squire_id)
        .all()
    )
    treasure_coords = session.query(TreasureChest.x_coordinate, TreasureChest.y_coordinate)\
        .filter(
            TreasureChest.squire_quest_id == squire_quest_id,
            TreasureChest.is_opened == False
        ).all()
    restricted.update(treasure_coords)
    restricted.update({ (0, 0), (40, 40), (-35,-35) })

    to_add = []  # collect new MapFeature instances

    # 3. River
    river_exists = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='river').count()
    if river_exists == 0:
        x = -placement_radius
        y = random.randint(-placement_radius, placement_radius)
        for _ in range(25 + level * 2):
            if (x, y) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=x,
                    y_coordinate=y,
                    squire_id=squire_id,
                    terrain_type='river'
                ))
                restricted.add((x, y))
            x += 1
            y += random.choice([-1, 0, 1])

    # 4. Forest clusters
    existing_forests = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='forest').count()
    forests_needed = max_forests - existing_forests
    clusters = min(num_forest_clusters, forests_needed // cluster_size)

    # Ensure forest near (-35, -35)
    pinned_cluster_center = (-35, -35)
    pinned_cluster_size = min(cluster_size, forests_needed)
    for _ in range(pinned_cluster_size):
        fx = pinned_cluster_center[0] + random.randint(-2, 2)
        fy = pinned_cluster_center[1] + random.randint(-2, 2)
        if (fx, fy) not in restricted:
            to_add.append(MapFeature(
                x_coordinate=fx,
                y_coordinate=fy,
                squire_id=squire_id,
                terrain_type='forest'
            ))
            restricted.add((fx, fy))

    pinned_cluster_center = (40, 40)
    pinned_cluster_size = min(cluster_size, forests_needed)
    for _ in range(pinned_cluster_size):
        fx = pinned_cluster_center[0] + random.randint(-2, 2)
        fy = pinned_cluster_center[1] + random.randint(-2, 2)
        if (fx, fy) not in restricted:
            to_add.append(MapFeature(
                x_coordinate=fx,
                y_coordinate=fy,
                squire_id=squire_id,
                terrain_type='forest'
            ))
            restricted.add((fx, fy))

    pinned_cluster_center = (-25, 50)
    pinned_cluster_size = min(cluster_size, forests_needed)
    for _ in range(pinned_cluster_size):
        fx = pinned_cluster_center[0] + random.randint(-2, 2)
        fy = pinned_cluster_center[1] + random.randint(-2, 2)
        if (fx, fy) not in restricted:
            to_add.append(MapFeature(
                x_coordinate=fx,
                y_coordinate=fy,
                squire_id=squire_id,
                terrain_type='forest'
            ))
            restricted.add((fx, fy))

    for _ in range(clusters):
        cx = random.randint(-placement_radius, placement_radius)
        cy = random.randint(-placement_radius, placement_radius)
        for _ in range(cluster_size):
            fx = cx + random.randint(-2, 2)
            fy = cy + random.randint(-2, 2)
            if len([f for f in to_add if f.terrain_type=='forest']) >= forests_needed:
                break
            if (fx, fy) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=fx,
                    y_coordinate=fy,
                    squire_id=squire_id,
                    terrain_type='forest'
                ))
                restricted.add((fx, fy))

    # 5. Mountain ranges
    existing_mountains = session.query(MapFeature).filter_by(squire_id=squire_id, terrain_type='mountain').count()
    mountains_needed = max_mountains - existing_mountains
    ranges = min(num_mountain_ranges, mountains_needed // mountain_range_length)
    for _ in range(ranges):
        mx = random.randint(-placement_radius, placement_radius)
        my = random.randint(-placement_radius, placement_radius)
        horizontal = random.choice([True, False])
        for i in range(mountain_range_length):
            x = mx + (i if horizontal else 0)
            y = my + (0 if horizontal else i)
            if len([m for m in to_add if m.terrain_type=='mountain']) >= mountains_needed:
                break
            if (x, y) not in restricted:
                to_add.append(MapFeature(
                    x_coordinate=x,
                    y_coordinate=y,
                    squire_id=squire_id,
                    terrain_type='mountain'
                ))
                restricted.add((x, y))

    # 6. Persist all new features in one batch
    session.add_all(to_add)
    session.commit()


def generate_river_path(start_x, start_y, length, bendiness=0.6, restricted=set()):
    river = []
    x, y = start_x, start_y
    river.append((x, y))

    for _ in range(length):
        dx = random.choice([1, 0, -1]) if random.random() < bendiness else 1
        dy = random.choice([1, 0, -1]) if random.random() < bendiness else 0

        x += dx
        y += dy

        # Prevent overlap with other features
        while (x, y) in restricted:
            dx = random.choice([-1, 0, 1])
            dy = random.choice([-1, 0, 1])
            x += dx
            y += dy

        river.append((x, y))
        restricted.add((x, y))  # Mark river location as restricted too

    return river

import random
from typing import List, Tuple

Coord = Tuple[int, int]

def generate_dungeon(squire_id, quest_id=39, size=10, path_length=50) -> List[Tuple[int, int, str]]:
    """
    Non-overlapping random path in a square bounds: -size+1..size-1 on both axes.
    Robust against dead-ends via backtracking; never infinite-loops.
    Returns a list of (x, y, room_type), with the last one 'boss'.
    """
    # grid capacity; you can't visit more unique cells than this
    max_cells = (2 * size - 1) ** 2
    target_len = max(2, min(path_length, max_cells))  # at least start+boss

    start: Coord = (0, 0)
    path: List[Coord] = [start]
    visited = {start}

    # Backtracking random walk
    backtracks = 0
    max_backtracks = max(1000, target_len * 10)  # generous but finite

    while len(path) < target_len:
        x, y = path[-1]
        candidates = [(x+1, y), (x-1, y), (x, y+1), (x, y-1)]
        random.shuffle(candidates)

        moves = [(nx, ny) for (nx, ny) in candidates
                 if (nx, ny) not in visited and abs(nx) < size and abs(ny) < size]

        if moves:
            nx, ny = random.choice(moves)
            path.append((nx, ny))
            visited.add((nx, ny))
            continue

        # DEAD END → backtrack
        path.pop()
        backtracks += 1
        if not path:
            # reset to start if we backtracked all the way
            path = [start]
        if backtracks > max_backtracks:
            # bail out gracefully with whatever we have
            break

    # Ensure we have at least a start and an endpoint
    if len(path) == 1:
        # fabricate a neighbor if possible
        for dx, dy in [(1,0), (-1,0), (0,1), (0,-1)]:
            nx, ny = start[0]+dx, start[1]+dy
            if abs(nx) < size and abs(ny) < size:
                path.append((nx, ny))
                break

    # Build room list
    room_types = ['true_false', 'riddle', 'mcq', 'treasure', 'empty']
    weights    = [0.30,        0.20,     0.30,  0.10,       0.10]

    content_rooms = path[:-1]
    boss_room = path[-1]

    room_data: List[Tuple[int, int, str]] = []
    for x, y in content_rooms:
        room_type = random.choices(room_types, weights, k=1)[0]
        room_data.append((x, y, room_type))

    bx, by = boss_room
    room_data.append((bx, by, 'boss'))

    return room_data


#~~~~~~~~~~~~~~~~~~~~~~~~~~~ Update Question Data
def update_squire_question_attempt(db, squire_id, question_id, question_type, answered_correctly, quest_id):

    new_attempt = SquireQuestionAttempt(
        squire_id=squire_id,
        question_id=question_id,
        question_type=question_type,  # must match one of the ENUM values
        answered_correctly=answered_correctly,
        quest_id=quest_id
        )

    try:
        db.add(new_attempt)
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Error committing response to {question_type}: {e}")
        return False

def update_squire_question(db, squire_id, question_id, question_type, answered_correctly, is_api=False):

    sq = SquireQuestion(
        squire_id=squire_id,
        question_id=question_id,
        question_type=question_type,
        answered_correctly=answered_correctly,
        is_api=is_api
    )

    try:
        db.add(sq)
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Error committing response to {question_type}: {e}")
        return False

#~~~~~~~~~~~~~~~~~~~~~~~~~~~ Update Team Messaging Toasts
def add_team_message(team_id: int, message: str) -> TeamMessage:
    """
    Persist a new team message and flush it to the database.
    Returns the newly created TeamMessage instance.
    """
    db = db_session()
    try:
        tm = TeamMessage(team_id=team_id, message=message)
        db.add(tm)
        db.commit()        # you can also session.flush() if you want bulk commits later
        db.refresh(tm)     # ensure tm.id and created_at are populated
        return tm
    finally:
        db.close()


#~~~~~~~~~~~~~~~~~~~~~~~~~~~ Map Functions

def can_enter_tile_slow(db_session, squire_id, new_x, new_y):
    """
    Check terrain in priority order without complex SQL.
    """
    # Check for non-blocking terrain first (fast exit)
    non_blocking = (
        db_session.query(MapFeature.terrain_type)
        .filter_by(squire_id=squire_id, x_coordinate=new_x, y_coordinate=new_y)
        .filter(MapFeature.terrain_type.in_(['waypoint', 'bridge', 'road']))
        .first()
    )

    if non_blocking:
        if non_blocking.terrain_type in ['waypoint', 'bridge']:
            return True
        if non_blocking.terrain_type == 'road':
            # Check if there's also a mountain
            has_mountain = db_session.query(MapFeature).filter_by(
                squire_id=squire_id, x_coordinate=new_x, y_coordinate=new_y, terrain_type='mountain'
            ).first() is not None
            return not has_mountain or has_hiking_boots(db_session, squire_id)

    # Check for blocking terrain
    blocking_terrain = (
        db_session.query(MapFeature.terrain_type)
        .filter_by(squire_id=squire_id, x_coordinate=new_x, y_coordinate=new_y)
        .filter(MapFeature.terrain_type.in_(['mountain', 'river']))
        .first()
    )

    if not blocking_terrain:
        return True

    if blocking_terrain.terrain_type == 'mountain':
        return has_hiking_boots(db_session, squire_id)
    if blocking_terrain.terrain_type == 'river':
        return has_boat(db_session, squire_id)

    return True

def can_enter_tile(db_session, squire_id, new_x, new_y):
    # Only check for terrain that might block movement
    blocking_terrain = (
        db_session.query(MapFeature.terrain_type)
        .filter_by(squire_id=squire_id, x_coordinate=new_x, y_coordinate=new_y)
        .filter(MapFeature.terrain_type.in_(['mountain', 'river']))
        .first()
    )

    if not blocking_terrain:
        return True

    # Check if there's infrastructure that overrides blocking terrain
    has_infrastructure = (
        db_session.query(MapFeature.terrain_type)
        .filter_by(squire_id=squire_id, x_coordinate=new_x, y_coordinate=new_y)
        .filter(MapFeature.terrain_type.in_(['bridge', 'waypoint']))
        .first()
    ) is not None

    if has_infrastructure:
        return True

    # Handle blocking terrain
    if blocking_terrain.terrain_type == 'mountain':
        return has_hiking_boots(db_session, squire_id)
    if blocking_terrain.terrain_type == 'river':
        return has_boat(db_session, squire_id)

    return True

def check_terrain_requirements(db_session, squire_id, terrain_types):
    """
    Check inventory requirements for a set of terrain types.
    Applies the most restrictive requirement.
    """
    # Mountains require hiking boots
    if 'mountain' in terrain_types:
        if not has_hiking_boots(db_session, squire_id):
            return False

    # Rivers require boats (unless there's a bridge, handled above)
    if 'river' in terrain_types:
        if not has_boat(db_session, squire_id):
            return False

    # Forests are passable by default (but might have encounter consequences)
    # Add other terrain requirements here as needed

    return True


def has_hiking_boots(db_session, squire_id):
    """Check if squire has hiking boots in inventory."""
    return (
        db_session.query(Inventory)
        .filter(
            Inventory.squire_id == squire_id,
            Inventory.item_name.ilike('%Boots%')
        )
        .count() > 0
    )


def has_boat(db_session, squire_id):
    """Check if squire has boat in inventory."""
    return (
        db_session.query(Inventory)
        .filter(
            Inventory.squire_id == squire_id,
            Inventory.item_name.ilike('%Boat%')
        )
        .count() > 0
    )


def get_terrain_movement_cost(db_session, squire_id, x, y):
    """
    Optional: Calculate movement cost/time for different terrain combinations.
    This could be used for a more sophisticated movement system.
    """
    terrain_features = (
        db_session.query(MapFeature.terrain_type)
        .filter_by(squire_id=squire_id, x_coordinate=x, y_coordinate=y)
        .all()
    )

    terrain_types = {feature.terrain_type for feature in terrain_features}

    if not terrain_types:
        return 1.0  # Base movement cost

    # Infrastructure reduces movement cost
    if 'road' in terrain_types:
        return 0.8  # Roads are faster
    if 'bridge' in terrain_types:
        return 1.0  # Bridges are normal speed
    if 'waypoint' in terrain_types:
        return 0.9  # Waypoints are slightly faster (well-marked)

    # Difficult terrain increases movement cost
    movement_cost = 1.0
    if 'mountain' in terrain_types:
        movement_cost *= 1.5  # Mountains are slower
    if 'forest' in terrain_types:
        movement_cost *= 1.2  # Forests are somewhat slower
    if 'river' in terrain_types:
        movement_cost *= 2.0  # Rivers without boats are very slow/dangerous

    return movement_cost


def get_tile_display_priority(terrain_types):
    """
    Determine which terrain icon to display when multiple types overlap.
    Returns the highest priority terrain type for map display.
    """
    # Priority order (highest to lowest)
    priority_order = [
        'waypoint',   # Always show waypoints (important for navigation)
        'bridge',     # Show bridges (important crossing points)
        'road',       # Show roads (infrastructure)
        'mountain',   # Show mountains (major obstacles)
        'forest',     # Show forests (moderate obstacles)
        'river',      # Show rivers (water features)
        # Add other terrain types as needed
    ]

    # Return the first terrain type found in priority order
    for terrain_type in priority_order:
        if terrain_type in terrain_types:
            return terrain_type

    # Fallback to first terrain type if none match priority list
    return list(terrain_types)[0] if terrain_types else None


# Example usage and testing
def test_terrain_combinations():
    """
    Test different terrain combinations to verify logic.
    """
    test_cases = [
        {'terrain': {'road'}, 'expected': True, 'description': 'Road on open ground'},
        {'terrain': {'mountain'}, 'expected': False, 'description': 'Mountain without boots'},
        {'terrain': {'road', 'mountain'}, 'expected': False, 'description': 'Road through mountain, no boots'},
        {'terrain': {'bridge', 'river'}, 'expected': True, 'description': 'Bridge over river'},
        {'terrain': {'river'}, 'expected': False, 'description': 'River without boat'},
        {'terrain': {'forest', 'road'}, 'expected': True, 'description': 'Road through forest'},
        {'terrain': {'waypoint'}, 'expected': True, 'description': 'Waypoint (always accessible)'},
        {'terrain': {'bridge', 'river', 'mountain'}, 'expected': False, 'description': 'Bridge over river through mountain, no boots'},
    ]

    print("Terrain Logic Test Cases:")
    print("=" * 50)
    for i, case in enumerate(test_cases, 1):
        print(f"{i}. {case['description']}")
        print(f"   Terrain: {case['terrain']}")
        print(f"   Expected passable: {case['expected']}")
        print()


# Integration with viewport_map function
def get_display_terrain_for_viewport(db_session, squire_id, x, y):
    """
    Helper function for viewport_map to get the correct terrain icon
    when multiple terrain types overlap.
    """
    terrain_features = (
        db_session.query(MapFeature.terrain_type)
        .filter_by(squire_id=squire_id, x_coordinate=x, y_coordinate=y)
        .all()
    )

    if not terrain_features:
        return None

    terrain_types = {feature.terrain_type for feature in terrain_features}
    return get_tile_display_priority(terrain_types)


def load_terrain_area(db, squire_id, center_x, center_y, radius=7):
    """
    Pre-load terrain for viewport area with single database query.
    Much faster than 225 individual queries!
    """
    min_x, max_x = center_x - radius, center_x + radius
    min_y, max_y = center_y - radius, center_y + radius

    # Single query for entire viewport area
    area_terrain = (
        db.query(MapFeature.x_coordinate, MapFeature.y_coordinate, MapFeature.terrain_type)
        .filter(
            MapFeature.squire_id == squire_id,
            MapFeature.x_coordinate.between(min_x, max_x),
            MapFeature.y_coordinate.between(min_y, max_y)
        )
        .all()
    )

    # Group by coordinate
    terrain_map = {}
    for x, y, terrain_type in area_terrain:
        if (x, y) not in terrain_map:
            terrain_map[(x, y)] = set()
        terrain_map[(x, y)].add(terrain_type)

    return terrain_map


def get_display_terrain_priority(terrain_types):
    """
    Determine which terrain icon to display when multiple types overlap.
    Returns the highest priority terrain type for map display.
    """
    if not terrain_types:
        return None

    # Priority order (highest to lowest)
    priority_order = [
        'waypoint',   # Always show waypoints (important for navigation)
        'bridge',     # Show bridges (important crossing points)
        'road',       # Show roads (infrastructure)
        'mountain',   # Show mountains (major obstacles)
        'forest',     # Show forests (moderate obstacles)
        'river',      # Show rivers (water features)
    ]

    # Return the first terrain type found in priority order
    for terrain_type in priority_order:
        if terrain_type in terrain_types:
            return terrain_type

    # Fallback to first terrain type if none match priority list
    return list(terrain_types)[0] if terrain_types else None

def get_viewport_map(db, squire_id: int, quest_id: int, viewport_size: int = 15) -> str:
    """
    Builds a little HTML table (15×15 by default) around the player’s position,
    showing visited dots, terrain icons, and the player marker.
    """
    logging.debug(f"squire_id={squire_id}, quest_id={quest_id}")
    try:
        # ———————— find the linking row ————————
        sqs = (
            db.query(SquireQuestStatus)
              .filter_by(squire_id=squire_id, quest_id=quest_id, status='active')
              .order_by(desc(SquireQuestStatus.id))
              .first()
        )


        if not sqs:
            msg = f"<p>⚠️ Error: No active quest status found for squire {squire_id} on quest {quest_id}.</p>"
            print(f"[DEBUG] Missing SquireQuestStatus: squire_id={squire_id}, quest_id={quest_id}")
            return msg

        # now we actually have the PK to filter treasure & hints
        squire_quest_id = sqs.id

        # 0) All treasure chests for this quest
        chests = db.query(TreasureChest) \
                   .filter_by(squire_quest_id=squire_quest_id) \
                   .all()
        chest_coords = {(c.x_coordinate, c.y_coordinate): c for c in chests}
        # Of those, split out which are opened vs. just discovered
        opened_coords = {coord for coord, c in chest_coords.items() if c.is_opened}

        hints = db.query(ChestHint) \
                  .filter_by(squire_quest_id=squire_quest_id) \
                  .all()
        hint_coords = {(h.chest_x, h.chest_y) for h in hints}

        ICONS = {
          'player': "📍",
          'home':   "🏰",
          'forest': "🌲", 'mountain': "🏔️", 'river': "🌊",
          'visited': "•",
          'unseen':  "⬜",
          "road": "═",      # Perfect choice!
          "bridge": "🌉",     # Bridge over water - fits the troll theme
          "waypoint": "🪧",   # Good for waymarkers
          # treasure states:
          'closed_chest': "🎁",
          'opened_chest': "🗝️",
          'hint_marker':  "❓",
        }



        # 1) All visited coords
        visited = {
            (h.x_coordinate, h.y_coordinate)
            for h in db.query(TravelHistory)
                       .filter_by(squire_id=squire_id)
                       .all()
        }

        # 2) Player pos
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return "<p>⚠️ Error: Player position not found.</p>"
        x, y = squire.x_coordinate, squire.y_coordinate

        # 3) All terrain features for this squire
        #features = db.query(MapFeature).filter_by(squire_id=squire_id).all()
        #feature_map = {
        #    (f.x_coordinate, f.y_coordinate): f.terrain_type
        #    for f in features
        #}

        # 4) Compute bounds
        #half = viewport_size // 2
        #x_min, x_max = x - half, x + half
        #y_min, y_max = y - half, y + half

        # 3) OPTIMIZED: Pre-load ALL terrain for viewport area (single query!)
        half = viewport_size // 2
        x_min, x_max = x - half, x + half
        y_min, y_max = y - half, y + half

        viewport_terrain = load_terrain_area(db, squire_id, x, y, half)

        # 5) Build HTML
        # 4) Build HTML
        out = ['<table class="game-map" style="border-collapse: collapse;">']
        for ry in range(y_max, y_min - 1, -1):
            out.append("<tr>")
            for cx in range(x_min, x_max + 1):
                if (cx, ry) == (x, y):
                    char = "📍"
                elif (cx, ry) == (0, 0):
                    char = "🏰"
                elif (cx, ry) == (40, 40):
                    char = "🧌"
                elif (cx, ry) == (-35,-35):
                    char = "🏇"
                elif (cx, ry) == (-25,50):
                    char = "🕳️"
                # 3) Already opened chest?
                elif (cx,ry) in opened_coords:
                    char = ICONS['opened_chest']
                # 4) Chest you've discovered (visited but not yet opened)
                elif (cx,ry) in chest_coords and (cx,ry) in hint_coords:
                    char = ICONS['closed_chest']
                elif (cx, ry) in viewport_terrain:
                    # Get terrain with priority logic (no database call!)
                    terrain_types = viewport_terrain[(cx, ry)]
                    terrain_type = get_display_terrain_priority(terrain_types)
                    char = {
                        "forest": "🌲",
                        "mountain": "🏔️",
                        "river": "🌊",
                        "road": "═",
                        "bridge": "🌉",
                        "waypoint": "🪧",
                    }.get(terrain_type, "⬜")
                elif (cx, ry) in visited:
                    char = "•"
                else:
                    char = "⬜"
                out.append(
                    f'<td style="width:30px;height:30px;text-align:center;'
                    f'border:1px solid #333">{char}</td>'
                )
            out.append("</tr>")
        out.append("</table>")
        out.append(
            """<p>📍=You | •=Visited | 🏰=Home | 🌲=Forest | 🏔️=Mountain | 🌊=River | ═ Road | 🎁 Chest | 🗝️ Solved Chest</p>"""
        )
        return "\n".join(out)

    except Exception as e:
        print(f"viewport map {e}")

def display_travel_map(squire_id: int, quest_id: int) -> str:
    """
    Generates an HTML-based map showing forests, visited locations, and the player,
    using ORM queries instead of raw SQL.
    """
    db = db_session()
    try:
        # 1) Gather visited coordinates
        visited_rows = (
            db.query(TravelHistory.x_coordinate, TravelHistory.y_coordinate)
              .filter(TravelHistory.squire_id == squire_id)
              .all()
        )
        visited = {(r.x_coordinate, r.y_coordinate) for r in visited_rows}

        # 2) Load player’s current position
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return "<p>⚠️ Error: Player position not found.</p>"
        x, y = squire.x_coordinate, squire.y_coordinate

        # 3) Fetch all terrain features for this squire
        feature_objs = (
            db.query(MapFeature)
              .filter(MapFeature.squire_id == squire_id)
              .all()
        )
        feature_map = {
            (f.x_coordinate, f.y_coordinate): f.terrain_type
            for f in feature_objs
        }

    finally:
        db.close()

    # 4) Determine dynamic grid bounds
    all_points = visited | set(feature_map.keys()) | {(x, y), (0, 0)}
    if all_points:
        min_x = min(px for px, _ in all_points)
        max_x = max(px for px, _ in all_points)
        min_y = min(py for _, py in all_points)
        max_y = max(py for _, py in all_points)
    else:
        # fallback grid
        min_x, max_x, min_y, max_y = -4, 4, -4, 4

    # 5) Build HTML table
    html = ['<table class="game-map" style="border-collapse: collapse;">']
    for row in range(max_y, min_y - 1, -1):
        html.append("<tr>")
        for col in range(min_x, max_x + 1):
            if (col, row) == (x, y):
                char = "📍"
            elif (col, row) == (0, 0):
                char = "🏰"
            elif (col, row) in feature_map:
                terr = feature_map[(col, row)]
                char = {
                    "forest":   "🌲",
                    "mountain": "🏔️",
                    "river":    "🌊"
                }.get(terr, "⬜")
            elif (col, row) in visited:
                char = "•"
            else:
                char = "⬜"

            html.append(
                f'<td style="width:30px;height:30px;text-align:center;'
                f'border:1px solid #333">{char}</td>'
            )
        html.append("</tr>")
    html.append("</table>")

    # 6) Legend
    html.append("""
    <p>📍 = You &nbsp; | &nbsp; • = Visited &nbsp; | &nbsp; 🏰 = Home Village
    &nbsp; | &nbsp; 🌲 = Forest &nbsp; | &nbsp; 🏔️ = Mountain &nbsp; | &nbsp; ⬜ = Unexplored</p>
    """)

    return "\n".join(html)


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~ TREASURE! AAAARRRRRRRRRRRRR.
def ishint(db_session, squire_id):
    """Returns True if the squire has any item with a name containing 'Scroll' (e.g., hint scrolls)"""
    return (
        db_session.query(func.count(Inventory.id))
        .filter(
            Inventory.squire_id == squire_id,
            or_(
                Inventory.item_name.ilike('%banishment%'),
                Inventory.item_name.ilike('%decoder%')
            )
        )
        .scalar() > 0
    )


def iswordlengthhint(db_session, squire_id):
    """Returns True if the squire can see word length hints"""
    return (
        db_session.query(func.count(Inventory.id))
                  .filter(
                      Inventory.squire_id == squire_id,
                      Inventory.item_name == 'four-leaf clover'
                  )
                  .scalar() > 0
    )


def iswordcounthint(db_session, squire_id):
    """Returns True if the squire can see word count hints"""
    return (
        db_session.query(func.count(Inventory.id))
                  .filter(
                      Inventory.squire_id == squire_id,
                      Inventory.item_name.ilike('%Keys to the Kingdom%')
                  )
                  .scalar() > 0
    )

def generate_first_letter_hint(answer):
    """Generate first letter hint for each word in the answer."""
    try:
        logging.info(f"Generating first letter hint for: {answer}")
        words = answer.lower().strip().split()
        first_letters = []
        for word in words:
            # Remove punctuation for cleaner hints
            clean_word = ''.join(char for char in word if char.isalpha())
            if clean_word:
                first_letters.append(clean_word[0].upper() + ('_' * (len(clean_word) - 1)))
        result = ' '.join(first_letters)
        logging.info(f"First letter hint result: {result}")
        return result
    except Exception as e:
        logging.error(f"Error in generate_first_letter_hint: {e}")
        return "Error generating hint"

def check_partial_match(user_input, correct_answer):
    """Check which words the user got right and return feedback."""
    try:
        logging.info(f"Checking partial match: '{user_input}' vs '{correct_answer}'")

        # Clean and split both inputs
        user_words = re.findall(r'\b\w+\b', user_input.lower())
        answer_words = re.findall(r'\b\w+\b', correct_answer.lower())

        logging.info(f"User words: {user_words}")
        logging.info(f"Answer words: {answer_words}")

        found_words = []
        missing_words = []

        for i, answer_word in enumerate(answer_words):
            if answer_word in user_words:
                found_words.append((i, answer_word))
            else:
                missing_words.append((i, answer_word))

        result = {
            'found_words': found_words,
            'missing_words': missing_words,
            'total_words': len(answer_words),
            'found_count': len(found_words)
        }

        logging.info(f"Partial match result: {result}")
        return result
    except Exception as e:
        logging.error(f"Error in check_partial_match: {e}")
        return {
            'found_words': [],
            'missing_words': [],
            'total_words': 0,
            'found_count': 0
        }

def check_for_treasure_at_location(
    squire_id: int,
    x: int,
    y: int,
    quest_id: int,
    squire_quest_id: int
) -> TreasureChest | None:
    """
    Returns the unopened TreasureChest at (x,y) for this squire & quest,
    only if the associated riddle has not yet been solved by this squire.
    """
    db = db_session()
    try:
        chest = (
            db.query(TreasureChest)
              # join to Riddle to filter by quest
              .join(Riddle, TreasureChest.riddle_id == Riddle.id)
              # left‐outer join to progress so we can require “no progress row”
              .outerjoin(
                  SquireRiddleProgress,
                  and_(
                      SquireRiddleProgress.riddle_id == Riddle.id,
                      SquireRiddleProgress.squire_id  == squire_id
                  )
              )
              .filter(
                  Riddle.quest_id             == quest_id,
                  TreasureChest.x_coordinate  == x,
                  TreasureChest.y_coordinate  == y,
                  TreasureChest.squire_quest_id == squire_quest_id,
                  SquireRiddleProgress.riddle_id == None
              )
              .first()
        )
        return chest
    finally:
        db.close()

"""
def check_for_treasure(squire_id: int, quest_id: int):

#    Checks if a treasure chest exists at the player's current location
#    for the given quest, and returns the ORM TreasureChest instance or None.
#    This appears to no longer be in use in the game and was superseded by check_for_treasure_at_location

    db = db_session()
    try:
        # 1) Retrieve player's current position
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return None
        x, y = squire.x_coordinate, squire.y_coordinate

        # 2) Look for an unopened chest whose riddle belongs to this quest
        chest = (
            db.query(TreasureChest)
              .join(Riddle, TreasureChest.riddle_id == Riddle.id)
              .outerjoin(
                  SquireRiddleProgress,
                  and_(
                      SquireRiddleProgress.riddle_id == Riddle.id,
                      SquireRiddleProgress.squire_id  == squire_id
                  )
              )
              .filter(
                  Riddle.quest_id              == quest_id,
                  TreasureChest.x_coordinate   == x,
                  TreasureChest.y_coordinate   == y,
                  TreasureChest.squire_quest_id == quest_id,
                  SquireRiddleProgress.riddle_id == None
              )
              .first()
        )
        return chest
    finally:
        db.close()

# Example usage:
# chest = check_for_treasure(2, 15)
# if chest:
#     print(f"Found chest at ({chest.x_coordinate}, {chest.y_coordinate}) with riddle ID {chest.riddle_id}")
# else:
#     print("No chest here.")

def open_treasure_chest(squire_id: int, chest_id: int) -> str:

#    Handles the treasure chest interaction in a console flow, using SQLAlchemy ORM.
#    Returns a summary message indicating rewards or failure.

    db = db_session()
    try:
        # Load chest and riddle
        chest = db.query(TreasureChest).get(chest_id)
        if not chest:
            return "❌ Chest not found."

        riddle = db.query(Riddle).get(chest.riddle_id)
        if not riddle:
            return "❌ Riddle not found for this chest."

        # Display riddle
        print("\n🎁 You have discovered a Treasure Chest!")
        print("🔒 The chest is locked... Solve the riddle to open it!")
        print(f"\n📜 Riddle: {riddle.riddle_text}")

        # Check for lexiconis hint item
        magic_count = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_name.ilike("%lexiconis%")
              )
              .count()
        )
        if magic_count > 0:
            print(f"💡 Clue: {riddle.word_length_hint} (Number of letters in each word)")

        # Prompt for answer
        answer = input("Enter your answer: ").strip().lower()
        correct = (answer == riddle.answer.strip().lower())

        if not correct:
            return "❌ Incorrect! The chest remains locked. Try again later."

        # Begin rewards
        msgs = ["✅ Correct! The chest unlocks, revealing its treasures!"]

        # 1) Mark progress
        progress = SquireRiddleProgress(
            squire_id=squire_id,
            riddle_id=riddle.id,
            quest_id=riddle.quest_id,
            answered_correctly=True
        )
        db.add(progress)
        # Also upsert SquireQuestion
        sq = db.query(SquireQuestion).filter_by(
            squire_id=squire_id,
            question_id=riddle.id,
            question_type='riddle'
        ).one_or_none()
        if not sq:
            db.add(SquireQuestion(
                squire_id=squire_id,
                question_id=riddle.id,
                question_type='riddle',
                answered_correctly=True
            ))
        else:
            sq.answered_correctly = True

        # 2) Award gold
        team = db.query(Team).get(db.query(Squire).get(squire_id).team_id)
        if chest.gold_reward > 0:
            team.gold += chest.gold_reward
            team.reputation += 2
            msgs.append(f"💰 You found {chest.gold_reward} bitcoin!")

        # 3) Award XP
        squire = db.query(Squire).get(squire_id)
        if chest.xp_reward > 0:
            squire.experience_points += chest.xp_reward
            msgs.append(f"🎖️ You gained {chest.xp_reward} XP!")

        # 4) Award food
        if chest.food_reward > 0:
            inv_food = Inventory(
                squire_id=squire_id,
                item_name="Magic Pizza",
                description="Restores hunger",
                uses_remaining=chest.food_reward,
                item_type="food"
            )
            db.add(inv_food)
            msgs.append(f"🍖 You found {chest.food_reward} special food items!")

        # 5) Award special gear
        if chest.special_item:
            uses_map = {"Easy": 10, "Medium": 25, "Hard": 50}
            uses = uses_map.get(riddle.difficulty, 10)
            inv_gear = Inventory(
                squire_id=squire_id,
                item_name=chest.special_item,
                description="A special item that affects gameplay",
                uses_remaining=uses,
                item_type="gear"
            )
            db.add(inv_gear)
            msgs.append(f"🛡️ You discovered a rare item: {chest.special_item}!")

        # 6) Mark chest opened
        chest.is_opened = True

        db.commit()
        return " ".join(msgs)

    except Exception as e:
        db.rollback()
        logging.error(f"Error in open_treasure_chest: {e}")
        return "❌ An error occurred while opening the treasure."
    finally:
        db.close()

# Example invocation:
# message = open_treasure_chest(squire_id=2, chest_id=5)
# print(message)
"""

def calculate_riddle_reward(squire_id: int, riddle_id: int) -> str:
    """
    Selects a random wizard item appropriate to the squire's level,
    adjusts its uses by riddle difficulty, awards it in Inventory, and
    returns the item name (or a default string if none).
    """
    db = db_session()
    try:
        # 1) Get the squire and their level
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return "nothing because knowledge is its own reward."
        level = squire.level
        logging.debug(f"Calc Riddle Reward: level={level}")

        # 2) Pick a random WizardItem up to that level
        item = (
            db.query(WizardItem)
              .filter(WizardItem.min_level <= level)
              .order_by(func.random())
              .first()
        )
        if not item:
            return "nothing because knowledge is its own reward."

        special_item = item.item_name
        uses = item.uses
        logging.debug(f"Calc Riddle Reward: picked {special_item} with base uses {uses}")

        # 3) Adjust uses based on riddle difficulty
        r = db.query(Riddle).get(riddle_id)
        diff = r.difficulty if r else "Easy"
        logging.debug(f"Calc Riddle Reward: difficulty={diff}")

        if diff == "Medium":
            uses += 10
        elif diff == "Hard":
            uses += 25

        # 4) Insert into Inventory
        inv = Inventory(
            squire_id       = squire_id,
            item_name       = special_item,
            description     = "magical item affecting game play",
            uses_remaining  = uses,
            item_type       = "gear"
        )
        db.add(inv)
        db.commit()

        return special_item

    except Exception as e:
        db.rollback()
        logging.error(f"Error in calculate_riddle_reward: {e}")
        return "nothing because knowledge is its own reward."
    finally:
        db.close()



# battle of the beasties

def flee_safely(e,p, hit_chance):

    e = int(e)
    p = int(p)

    if p == 0:
        p = 1

    damage_probability = (e / p) * ((100 - hit_chance) / 100 )
    damage_probability = min(max(damage_probability,0),1)

    logging.debug(f"Flee Safely damage probability: {damage_probability}")

    if random.randint(0, 1) < damage_probability:
        return False
    else:
        return True

def calc_flee_safely(e, p, hit_chance):
    e = int(e)
    p = int(p)

    if p == 0:
        p = 1

    damage_probability = 100 - (round(((e / p) * ((100 - hit_chance) / 100)) * 100))
    damage_probability = min(max(damage_probability, 0), 100)

    return damage_probability

def calculate_enemy_encounter_probability(
    squire_id: int,
    quest_id: int,  # unused, kept for signature compatibility
    current_x: int,
    current_y: int,
    squire_quest_id: int,
    proximity: int = 2
) -> float:
    """
    Calculates the probability of encountering an enemy based on nearby features,
    using SQLAlchemy ORM instead of raw SQL.
    """
    db = db_session()
    try:
        base_probability = 0.05

        # 1) Count nearby terrain features by type
        terrain_counts = (
            db.query(
                MapFeature.terrain_type,
                func.count().label("count")
            )
            .filter(
                func.abs(MapFeature.x_coordinate - current_x) <= proximity,
                func.abs(MapFeature.y_coordinate - current_y) <= proximity,
                MapFeature.squire_id == squire_id
            )
            .group_by(MapFeature.terrain_type)
            .all()
        )

        # 2) Adjust based on feature type
        for terrain, count in terrain_counts:
            if terrain == "forest":
                base_probability += 0.02 * count
            elif terrain == "mountain":
                base_probability += 0.03 * count
            elif terrain == "river":
                base_probability += 0.04 * count

        # 3) Count nearby unopened treasure chests
        chest_count = (
            db.query(func.count(TreasureChest.id))
            .filter(
                func.abs(TreasureChest.x_coordinate - current_x) <= proximity,
                func.abs(TreasureChest.y_coordinate - current_y) <= proximity,
                TreasureChest.squire_quest_id == squire_quest_id,
                TreasureChest.is_opened == False
            )
            .scalar()
        )

        if chest_count:
            base_probability += 0.04 * chest_count

        # 4) Clamp probability
        probability = min(max(base_probability, 0.0), 0.9)
        return probability

    finally:
        db.close()

# Example usage:
# prob = calculate_enemy_encounter_probability(2, 15, 10, 5, 7)
# print(f"Encounter chance: {prob:.2%}")

def calculate_hit_chance(squire_id: int, level: int) -> float:
    """
    Calculates hit chance based on the total number of True/False questions
    and riddles, and how many the squire has answered correctly.
    Returns a percentage capped at 95%.
    """
    db = db_session()
    try:
        # 1) Total T/F questions
        total_tf = db.query(func.count(TrueFalseQuestion.id)).scalar() or 0

        # 2) Total riddles
        total_r = db.query(func.count(Riddle.id)).scalar() or 0

        allqs = total_tf + total_r
        if allqs == 0:
            return 0.0  # no questions means no bonus

        # 3) Distinct correctly answered questions
        correct = (
            db.query(func.count(func.distinct(SquireQuestion.question_id)))
              .filter(
                  SquireQuestion.squire_id == squire_id,
                  SquireQuestion.answered_correctly == True
              )
              .scalar() or 0
        )

        # 4) Compute combat modifier
        combatmod = correct / allqs

        # 5) Base hit chance: 2% per level plus combatmod
        base_hit = (level * 2) + combatmod

        # 6) Cap at 95%
        return min(base_hit, 95.0)
    finally:
        db.close()

# Example usage:
# hit_chance = calculate_hit_chance(squire_id=2, level=3)
# print(f"Hit chance: {hit_chance:.2f}%")

def calculate_skill_bonus(squire_id: int, enemy_name: str, db) -> int:
    """
    Calculate combat bonus from skill points allocated to skills that are effective
    against the given enemy.

    Returns an integer bonus based on:
    - Squire's allocated skill points for relevant skills
    - Enemy's susceptibility weight for those skills (typically 50-150, default 100)

    Formula: sum of (skill_points * (weight / 100)) for each applicable skill
    """
    # Get the enemy record
    enemy = db.query(Enemy).filter(Enemy.name == enemy_name).one_or_none()
    if not enemy:
        return 0

    # Get all skill susceptibilities for this enemy
    susceptibilities = (
        db.query(EnemySkillSusceptibility)
        .filter(EnemySkillSusceptibility.enemy_id == enemy.id)
        .all()
    )

    if not susceptibilities:
        return 0

    # Get squire's allocated skill points
    squire_skills = (
        db.query(SquireSkillPoint)
        .filter(SquireSkillPoint.squire_id == squire_id)
        .all()
    )

    # Create a map of skill_id -> points
    skill_points_map = {sp.skill_id: sp.points for sp in squire_skills}

    # Calculate total bonus
    total_bonus = 0
    for susceptibility in susceptibilities:
        skill_id = susceptibility.skill_id
        weight = susceptibility.weight  # typically 50-150, default 100
        points = skill_points_map.get(skill_id, 0)

        if points > 0:
            # Each skill point adds (weight/100) to the bonus
            # e.g., 5 points in a skill with weight 150 = 5 * 1.5 = 7.5 -> 7
            bonus = int(points * (weight / 100.0))
            total_bonus += bonus
            logging.debug(
                f"Skill bonus: skill_id={skill_id}, points={points}, "
                f"weight={weight}, bonus={bonus}"
            )

    return total_bonus


def combat_mods(squire_id: int, enemy_name: str, level: int) -> int:
    """
    Calculates combat modifiers:
      - +1 per 'gear' item with uses remaining
      - +5 per 'special' item effective against the given enemy
      - +2 per player level
      - Bonus based on skill points allocated to skills effective against this enemy
    """
    db = db_session()
    try:
        # 1) Count usable gear items
        base_mod = (
            db.query(func.count(Inventory.id))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'gear',
                  Inventory.uses_remaining > 0
              )
              .scalar()
            or 0
        )

        # 2) Count special items effective against this enemy
        enemy_mod = (
            db.query(func.count(Inventory.id))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'special',
                  Inventory.effective_against == enemy_name
              )
              .scalar()
            or 0
        )

        # 3) Level contribution
        level_mod = 2 * level

        # 4) Team rank contribution
        team_rank_mod = 0
        team = (
            db.query(Team)
              .join(Squire, Team.id == Squire.team_id)
              .filter(Squire.id == squire_id)
              .one_or_none()
        )

        if team:
            # Get all teams ranked by reputation descending
            ranked_teams = db.query(Team.id).order_by(Team.reputation.desc()).all()
            team_ids = [t.id for t in ranked_teams]
            rank = team_ids.index(team.id) + 1  # 1-based rank

            # Apply tiered bonuses
            if rank <= 3:
                team_rank_mod = 5
            elif rank <= 8:
                team_rank_mod = 3
            elif rank <= 18:
                team_rank_mod = 1
            else:
                team_rank_mod = 0

            logging.debug(f"Team {team.id} rank={rank}, bonus={team_rank_mod}")

        # 5) Skill-based bonus
        skill_mod = calculate_skill_bonus(squire_id, enemy_name, db)

        # Final total mods
        total_mods = base_mod + (enemy_mod * 5) + level_mod + team_rank_mod + skill_mod

        logging.debug(
            f"combat_mods → squire={squire_id}, enemy={enemy_name}, "
            f"gear={base_mod}, special={enemy_mod}, level={level_mod}, "
            f"team_rank_mod={team_rank_mod}, skill_mod={skill_mod}, total={total_mods}"
        )

        return total_mods

    finally:
        db.close()

def question_accuracy(squire_id):
    db = db_session()

    # Calculate question accuracy
    attempts = (
        db.query(func.count(SquireQuestionAttempt.id))
        .filter(SquireQuestionAttempt.squire_id == squire_id)
        .scalar()
    )

    correct = (
        db.query(func.count(SquireQuestionAttempt.id))
        .filter(SquireQuestionAttempt.squire_id == squire_id, SquireQuestionAttempt.answered_correctly == True)
        .scalar()
    )

    accuracy = round((correct / attempts) * 100, 1) if attempts > 0 else 0
    return accuracy

# Example usage:
# mods = combat_mods(squire_id=2, enemy_name='Goblin', level=3)
# print(f"Total combat modifier: {mods}")

def hunger_mods(squire_id: int) -> int:
    """
    Returns the count of 'gold coin pouch' items for the squire,
    which modify the player's hunger level.
    """
    db = db_session()
    try:
        count = (
            db.query(func.count(Inventory.id))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_name == 'gold coin pouch'
              )
              .scalar()
            or 0
        )
        logging.debug(f"hunger_mods → squire={squire_id}, count={count}")
        return count
    finally:
        db.close()

def degrade_gear(squire_id: int, weapon: str) -> bool:
    """
    Decrements uses of the specified weapon and all non-exempt gear,
    deleting any inventory rows whose uses drop below 1.
    """
    db = db_session()
    try:
        # 1) Degrade the specific weapon
        inv = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_name == weapon
              )
              .order_by(Inventory.uses_remaining.asc())
              .first()
        )
        if inv:
            inv.uses_remaining -= 1
            if inv.uses_remaining < 1:
                db.delete(inv)
        db.commit()

        # 2) Degrade all regular gear (except the exempt list)
        exempt = ['Pen', 'Calculator', 'Law Book', 'Stamp']
        gear_items = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'gear',
                  not_(Inventory.item_name.in_(exempt))
              )
              .all()
        )
        for g in gear_items:
            g.uses_remaining -= 1
            if g.uses_remaining < 1:
                db.delete(g)
        db.commit()
        logging.debug(f"degrade_gear → squire={squire_id}, weapon_degraded={bool(inv)}, gear_degraded={len(gear_items)}")
        return True
    except Exception as e:
        db.rollback()
        logging.error(f"Error in degrade_gear: {e}")
        return False
    finally:
        db.close()

def update_work_for_combat(squire_id: int) -> bool:
    """
    Resets the squire's work_sessions to zero before combat.
    Always returns False to indicate no further 'work' is allowed immediately.
    """
    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if squire:
            squire.work_sessions = 0
            db.commit()
            logging.debug(f"update_work_for_combat → squire={squire_id}, work_sessions reset")
        return False
    except Exception as e:
        db.rollback()
        logging.error(f"Error in update_work_for_combat: {e}")
        return False
    finally:
        db.close()

def get_player_max_hunger(squire_id: int):
    """
    Returns:
      - max_hunger: total sum of food uses the squire has.
      - next_food: first available food Inventory instance or None.
    """
    db = db_session()
    try:
        max_hunger = (
            db.query(func.coalesce(func.sum(Inventory.uses_remaining), 0))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'food'
              )
              .scalar()
        )

        next_food = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'food',
                  Inventory.uses_remaining > 0
              )
              .first()
        )

        return max_hunger, next_food
    finally:
        db.close()

def mod_enemy_hunger(mod, enemy, forest, mountain):
    #calculates the max hunger of the enemy based on distance from village + terrain modifier
    emh = enemy

    #harder to defeat enemy in forests or mountains
    if forest == True:
        emh += 2
    elif mountain == True:
        emh +=3

    #harder to defeat enemy based on overall distance from village
    if 51 <= mod <= 150:
        emh += 1
    elif 151 <= mod <= 500:
        emh += 2
    elif 501 <= mod <= 1000:
        emh += 3
    elif mod > 1000:
        emh += 5

    return emh

def get_squire_stats(squire_id: int) -> tuple[int, int]:
    """
    Fetches the player's current XP and gold using ORM models.
    Returns (experience_points, gold).
    """
    db = db_session()
    try:
        squire = db.query(Squire).get(squire_id)
        if not squire:
            return 0, 0
        team = db.query(Team).get(squire.team_id)
        xp = squire.experience_points or 0
        gold = team.gold if team else 0
        return xp, gold
    finally:
        db.close()

def get_inventory(squire_id: int):
    """
    Returns a list of inventory summaries for the given squire:
    each entry contains item_name, item_type, description,
    total uses_remaining, and count of stacks (effect).
    """
    db = db_session()
    try:
        results = (
            db.query(
                Inventory.item_name,
                Inventory.item_type,
                Inventory.description,
                func.sum(Inventory.uses_remaining).label("uses_remaining"),
                func.count().label("effect")
            )
            .filter(Inventory.squire_id == squire_id)
            .group_by(
                Inventory.item_name,
                Inventory.item_type,
                Inventory.description
            )
            .order_by(
                Inventory.item_type,
                Inventory.item_name
            )
            .all()
        )
        return results  # List of named tuples
    finally:
        db.close()

def get_hunger_bar(squire_id: int) -> str:
    """
    Generates a hunger bar displaying up to 8 segments:
      🟩 for available food uses and 🟥 for hunger.
    """
    db = db_session()
    try:
        total_uses = (
            db.query(func.coalesce(func.sum(Inventory.uses_remaining), 0))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'food'
              )
              .scalar()
        )
        total_uses = int(total_uses)  # 🛡️ Ensure it's an int before min()
    finally:
        db.close()

    full_count = min(total_uses, 8)
    hunger_count = 8 - full_count
    hunger_bar = " ".join(["🟩"] * full_count + ["🟥"] * hunger_count)
    return hunger_bar


# Example usage:
# inv = get_inventory(2)
# for row in inv:
#     print(row)
# print(get_hunger_bar(2))


def check_quest_progress(squire_id: int, quest_id: int) -> tuple[int, int, float]:
    """
    Returns (answered_count, total_required, progress_percentage).
    """

    db = db_session()
    try:
        total_hard = (
            db.query(func.count(Riddle.id))
              .filter(
                  Riddle.quest_id == quest_id,
                  Riddle.difficulty == 'Hard'
              )
              .scalar() or 0
        )
        total_required = int(total_hard) + 6  # ✅ cast to int

        answered = (
            db.query(func.count(SquireRiddleProgress.id))
              .filter(
                  SquireRiddleProgress.squire_id == squire_id,
                  SquireRiddleProgress.quest_id == quest_id,
                  SquireRiddleProgress.answered_correctly == True
              )
              .scalar() or 0
        )
        answered = int(answered)  # ✅ just to be safe

        progress = float(answered / total_required * 100) if total_required else 0.0

        return answered, total_required, progress
    finally:
        db.close()


def display_progress_bar(percentage):
    """Generates a text-based progress bar."""
    percentage = float(percentage)  # ✨ Cast once, rule all
    bar_length = 20
    filled_length = int(bar_length * (percentage / 100))
    bar = "█" * filled_length + "-" * (bar_length - filled_length)
    return f"[{bar}] {percentage:.1f}% Complete"



#quest & riddle related actions

def update_riddle_hints() -> str:
    """
    Updates the word_length_hint and word_count fields for any Riddle
    where those are currently null, based on the answer.
    """
    db = db_session()
    try:
        # 1) Fetch riddles missing hints or word counts
        riddles = (
            db.query(Riddle)
              .filter(
                  or_(
                      Riddle.word_length_hint.is_(None),
                      Riddle.word_count.is_(None)
                  )
              )
              .all()
        )

        # 2) Generate and apply new hints
        for r in riddles:
            r.word_length_hint = generate_word_length_hint(r.answer)
            r.word_count        = generate_word_count(r.answer)

        # 3) Commit changes
        db.commit()
        return "✅ Riddle hints updated successfully!"
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Example invocation:
# message = update_riddle_hints()
# print(message)


def generate_word_length_hint(answer):
    """Generates a hint based on the number of characters in each word of the answer."""
    words = answer.split()  # Split the answer into words
    hint = " ".join(str(len(word)) for word in words)  # Replace each word with its length
    return hint
"""
def generate_word_count(answer):
    word_count = len(answer.split())
    return word_count
"""

"""
def save_correct_answer(squire_id: int, quest_id: int, riddle_id: int) -> None:

#    Records that the squire has correctly answered a riddle.
#    If an entry already exists, it ensures answered_correctly is True.

    db = db_session()
    try:
        # Upsert logic: try to fetch existing progress
        progress = (
            db.query(SquireRiddleProgress)
              .filter_by(
                  squire_id=squire_id,
                  quest_id=quest_id,
                  riddle_id=riddle_id
              )
              .one_or_none()
        )
        if progress:
            progress.answered_correctly = True
        else:
            progress = SquireRiddleProgress(
                squire_id=squire_id,
                quest_id=quest_id,
                riddle_id=riddle_id,
                answered_correctly=True
            )
            db.add(progress)
        db.commit()
    except:
        db.rollback()
        raise
    finally:
        db.close()

"""

from sqlalchemy import exists, and_

def is_boss_quest(db, quest_id: int) -> bool:

     return db.query(
         exists().where(and_(MapNode.quest_id == quest_id))
     ).scalar()


def check_quest_completion(squire_id: int, quest_id: int) -> bool:
    """
    Returns True if the squire has completed the quest by answering
    all required riddles: (# of HARD riddles + 6).
    """
    #BOSS_QUESTS = {0, 14, 28, 32, 39}

    db = db_session()


    try:
        if is_boss_quest(db,quest_id):
            return False

        # Total 'Hard' riddles for this quest
        total_hard = (
            db.query(func.count(Riddle.id))
              .filter(
                  Riddle.quest_id == quest_id,
                  Riddle.difficulty == 'Hard'
              )
              .scalar() or 0
        )
        total_required = total_hard + 6

        # Count correctly answered riddles for this quest
        answered = (
            db.query(func.count(SquireRiddleProgress.id))
              .filter(
                  SquireRiddleProgress.squire_id == squire_id,
                  SquireRiddleProgress.quest_id == quest_id,
                  SquireRiddleProgress.answered_correctly == True
              )
              .scalar() or 0
        )
        logging.debug(f"{total_required} {answered}")
        return answered >= total_required
    finally:
        db.close()

# Example usage:
# save_correct_answer(2, 15, 42)
# completed = check_quest_completion(2, 15)
# print("Quest complete:", completed)

def complete_quest(squire_id: int, quest_id: int) -> tuple[bool, list[str]]:
    """
    Handles quest completion:
      - Checks if all riddles are solved.
      - Grants special item reward.
      - Clears travel history.
      - Marks quest as completed.
      - Unlocks the next quest (sets its status to 'active').
    Returns a tuple: (was_completed, messages).
    """
    db = db_session()

    BOSS_QUESTS = (
        db.query(MapNode).filter(MapNode.quest_id == quest_id).scalar() or 0
    )

    messages: list[str] = []
    logging.debug(f"⚔️ complete_quest start: squire={squire_id}, quest={quest_id}")
    try:
        # 1) Check completion via ORM helper
        if not is_boss_quest(db,quest_id) and not check_quest_completion(squire_id, quest_id):
            logging.debug("🔎 Quest not yet complete (riddles remain). Exiting.")
            return False, ["🔎 You still have more riddles to solve in this quest!"]

        messages.append("🎉 Congratulations! You have completed this quest!")

        # 2) Grant special reward from Quest table
        quest = db.query(Quest).get(quest_id)
        if quest and quest.reward:
            inv = Inventory(
                squire_id=squire_id,
                item_name=quest.reward,
                description=f"Special reward for completing quest {quest_id}.",
                item_type='special',
                effective_against=quest.effective_against
            )
            db.add(inv)
            messages.append(f"🏆 You have received a special item: {quest.reward}!")

        # 3) Clear travel history
        db.query(TravelHistory).filter(TravelHistory.squire_id == squire_id).delete()

        # 4) Upsert SquireQuestStatus to 'completed'
        status = (
            db.query(SquireQuestStatus)
              .filter_by(squire_id=squire_id, quest_id=quest_id).first()

        )
        if status:
            status.status = 'completed'
        else:
            status = SquireQuestStatus(
                squire_id=squire_id,
                quest_id=quest_id,
                status='completed'
            )
            db.add(status)

        # 5) Unlock next quest
        next_q = (
            db.query(Quest)
              .filter(Quest.id > quest_id)
              .order_by(Quest.id.asc())
              .first()
        )
        if next_q:
            next_q.status = 'active'
            messages.append(f"🛡️ A new quest has been unlocked: Quest {next_q.id}!")
        else:
            messages.append("⚠️ No more quests available!")

        # 6) Commit all changes
        db.commit()
        return True, messages

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Example usage:
# completed, msgs = complete_quest(squire_id=2, quest_id=15)
# for line in msgs:
#     print(line)

def get_random_riddle(quest_id: int, squire_id: int):
    """
    Returns a single random unanswered Riddle for the given quest and squire,
    choosing difficulty based on how many they've already solved:
      <3 → Easy, <6 → Medium, else Hard.
    Returns a dict with riddle fields or None.
    """
    db = db_session()
    try:
        # 1) Count how many riddles they've answered correctly
        answered_count = (
            db.query(func.count(SquireRiddleProgress.id))
              .filter(
                  SquireRiddleProgress.squire_id == squire_id,
                  SquireRiddleProgress.quest_id == quest_id,
                  SquireRiddleProgress.answered_correctly == True
              )
              .scalar() or 0
        )

        # 2) Determine difficulty
        if answered_count < 3:
            difficulty = "Easy"
        elif answered_count < 6:
            difficulty = "Medium"
        else:
            difficulty = "Hard"

        # 3) Build a subquery of already answered riddle IDs
        answered_subq = (
            db.query(SquireRiddleProgress.riddle_id)
              .filter(SquireRiddleProgress.squire_id == squire_id)
        )

        # 4) Fetch one random unanswered riddle of that difficulty
        riddle = (
            db.query(
                Riddle.id,
                Riddle.riddle_text,
                Riddle.difficulty,
                Riddle.answer,
                Riddle.hint,
                Riddle.word_length_hint
            )
            .filter(
                Riddle.quest_id == quest_id,
                Riddle.difficulty == difficulty,
                ~Riddle.id.in_(answered_subq)
            )
            .order_by(func.rand())
            .first()
        )

        # 5) Return as dict or None
        return dict(riddle._asdict()) if riddle else None

    finally:
        db.close()

# Example:
# r = get_random_riddle(quest_id=17, squire_id=2)
# if r:
#     print("Random Riddle:", r)

"""
def encounter_riddle(quest_id: int, squire_id: int) -> str:

#    Console-based riddle encounter:
#      - Fetches a random unanswered riddle
#      - Optionally shows a lexicon clue if the squire has a 'Lexicon' item
#      - Prompts for an answer and handles correct/incorrect logic
#    Returns a result message.

    db = db_session()
    try:
        # 1) Get a random riddle via ORM helper
        riddle = get_random_riddle(quest_id, squire_id)
        if not riddle:
            return "🏆 You've mastered all riddles for this quest! No more questions remain."

        # 2) Display the riddle
        print(f"\n📜 Riddle ({riddle['difficulty']}): {riddle['riddle_text']}")

        # 3) Check for 'Lexicon' in inventory to show word-length hint
        magic_count = (
            db.query(func.count(Inventory.id))
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_name.ilike("%Lexicon%")
              )
              .scalar() or 0
        )
        if magic_count > 0:
            print(f"💡 Clue: {riddle['word_length_hint']} (Number of letters in each word)")

        # 4) Prompt for answer
        answer = input("Enter your answer: ").strip().lower()

        # 5) Validate
        if answer == riddle["answer"].strip().lower():
            # Correct!
            # Determine rewards by difficulty
            xp_reward = 10 if riddle["difficulty"] == "Easy" else 20 if riddle["difficulty"] == "Medium" else 30
            gold_reward = 5 if riddle["difficulty"] == "Easy" else 15 if riddle["difficulty"] == "Medium" else 50

            # Apply progress and capture any level-up messages
            levelup_msgs = update_squire_progress(squire_id, xp_reward, gold_reward)

            # Record that the riddle was answered correctly
            save_correct_answer(squire_id, quest_id, riddle["id"])

            # Build result string
            msg = f"✅ Correct! You gain {xp_reward} XP and {gold_reward} bits!"
            if levelup_msgs:
                msg += " " + " ".join(levelup_msgs)
            return msg

        else:
            # Incorrect: show hint
            return f"❌ Incorrect! Hint: {riddle['hint']}"

    finally:
        db.close()

# Example usage:
# result = encounter_riddle(quest_id=17, squire_id=2)
# print(result)
"""

def check_riddle_answer(user_answer: str, riddle_id: int) -> bool:
    """
    Returns True if the provided user_answer matches the stored answer for the given riddle_id.
    """
    db = db_session()
    try:
        riddle = db.query(Riddle).get(riddle_id)
        if not riddle or not riddle.answer:
            return False
        return user_answer.lower().strip() == riddle.answer.lower().strip()
    finally:
        db.close()

def get_active_quests(squire_id: int) -> list[dict]:
    """
    Returns a list of one available quest (id, quest_name, description) for the squire
    that has not yet been completed.
    """
    db = db_session()
    try:
        # Subquery to find completed quest IDs
        completed_ids = (
            db.query(SquireQuestStatus.quest_id)
              .filter(
                  SquireQuestStatus.squire_id == squire_id,
                  SquireQuestStatus.status == 'completed'
              )
        )
        # Fetch the first active quest not in completed_ids
        quest = (
            db.query(Quest.id, Quest.quest_name, Quest.description)
              .filter(~Quest.id.in_(completed_ids))
              .order_by(Quest.id.asc())
              .first()
        )
        if quest:
            return [dict(quest._asdict())]
        return []
    finally:
        db.close()

# Example usage:
# result = check_riddle_answer("offer", 42)
# active = get_active_quests(squire_id=2)
# print("Answer correct:", result)
# print("Available quests:", active)


# Display available quests
def chooseq(conn, squire_id):
    quests = get_active_quests(conn, squire_id)

    print("\n🏰 Available Quests:")
    for q in quests:
        print(f"[{q['id']}] {q['quest_name']}: {q['description']}")

    quest_id = int(input("\nEnter the Quest ID to embark on your journey: "))
    return quest_id

def get_riddles_for_quest(quest_id: int) -> list[dict]:
    """
    Returns all riddles for a given quest as a list of dicts containing:
    id, riddle_text, answer, hint.
    """
    db = db_session()
    try:
        riddles = (
            db.query(Riddle)
              .filter(Riddle.quest_id == quest_id)
              .all()
        )
        return [
            {
                'id': r.id,
                'riddle_text': r.riddle_text,
                'answer': r.answer,
                'hint': r.hint
            }
            for r in riddles
        ]
    finally:
        db.close()

"""
def visit_shop(squire_id: int, level: int) -> None:

#    Console-based shop interaction using ORM:
#      - Lists available ShopItem entries up to the player's level.
#      - Shows current gold from the squire's Team.
#      - Prompts purchase choice; updates Team.gold and Inventory.

    db = db_session()
    try:
        # 1) Fetch shop items available at this level
        items = (
            db.query(ShopItem)
              .filter(ShopItem.min_level <= level)
              .all()
        )
        print("\n🛒 Welcome to the Bit Mall! Here's what we have:")
        for item in items:
            print(f"  [{item.id}] {item.item_name} - {item.description} "
                  f"(💰 {item.price} bits, 🍴 {item.uses} uses)")

        # 2) Get squire's team and current gold
        squire = db.query(Squire).get(squire_id)
        team = db.query(Team).get(squire.team_id) if squire else None
        player_gold = team.gold if team and team.gold is not None else 0
        print(f"\n💰 You have {player_gold} Bitcoin.")

        choice = input("Enter the item ID to buy or 'Q' to exit: ").strip().upper()
        if choice == "Q":
            print("🏪 You leave the shop.")
            return

        # 3) Attempt purchase
        try:
            item_id = int(choice)
        except ValueError:
            print("❌ Invalid input. Please enter a number or 'Q'.")
            return

        shop_item = db.query(ShopItem).get(item_id)
        if not shop_item:
            print("❌ Invalid selection.")
            return
        if player_gold < shop_item.price:
            print("❌ You don't have enough gold!")
            return

        # 4) Deduct gold and add to inventory
        team.gold = player_gold - shop_item.price
        new_inv = Inventory(
            squire_id=squire_id,
            item_name=shop_item.item_name,
            description=shop_item.description,
            item_type=shop_item.item_type,
            uses_remaining=shop_item.uses
        )
        db.add(new_inv)
        db.commit()

        print(f"✅ You bought {shop_item.item_name}!")
    finally:
        db.close()

# Example usage:
# print(get_riddles_for_quest(quest_id=15))
# visit_shop(squire_id=2, level=1)
"""

def consume_food(squire_id: int) -> tuple[bool, str]:
    """
    Uses up food from the squire's inventory when traveling.
    - Applies a level-based chance to avoid consumption.
    - Deducts one use from the first available food item or removes it.
    Returns (success, message).
    """
    db = db_session()
    try:
        # 1) Fetch squire level
        squire = db.query(Squire).get(squire_id)
        level = squire.level if squire else 1

        # 2) Define reduction chances

        avoid_chance = min(level*3, 75)

        # 3) Random roll to skip consumption
        if random.randint(1, 100) <= avoid_chance:
            return True, "🌟 Your experience helps you travel efficiently! You avoid hunger this time."

        # 4) Find an available food item
        food_item = (
            db.query(Inventory)
              .filter(
                  Inventory.squire_id == squire_id,
                  Inventory.item_type == 'food',
                  Inventory.uses_remaining > 0
              )
              .first()
        )

        if not food_item:
            return False, "🚫 No food available! You feel the pangs of hunger."

        # 5) Consume one use
        food_item.uses_remaining -= 1
        item_name = food_item.item_name

        if food_item.uses_remaining <= 0:
            db.delete(food_item)
            message = f"🗑️ You finished your {item_name}."
        else:
            message = f"🍽️ You used your {item_name}. Remaining uses: {food_item.uses_remaining}."

        try:
            db.commit()
        except Exception as e:
            logging.warning(f"Failed to consume food, dude: {e}")

        return True, message

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Example usage:
# success, msg = consume_food(squire_id=2)
# print(msg)
