# utils/filters.py

def chance_image(chance):
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
