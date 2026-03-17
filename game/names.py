"""
Medieval name generation.

Faker has no built-in medieval name pools — fake.first_name() returns modern names
like 'Tyler Anderson'. Use fake.random_element() with custom medieval lists instead.
"""
import random
from faker import Faker

fake = Faker()

MEDIEVAL_FIRST_NAMES_MALE: list[str] = [
    "Aldric", "Baldwin", "Conrad", "Dorian", "Edmund", "Fletcher",
    "Gareth", "Harold", "Ingram", "Jasper", "Kendrick", "Leofric",
    "Magnus", "Nigel", "Oswald", "Percival", "Quentin", "Roland",
    "Siward", "Tobias", "Ulric", "Vaughn", "Walter", "Cormac",
    "Dunstan", "Eadric", "Fulke", "Godfrey", "Humphrey", "Ivar",
]

MEDIEVAL_FIRST_NAMES_FEMALE: list[str] = [
    "Agnes", "Beatrice", "Cecily", "Dorothea", "Elspeth", "Frideswide",
    "Gwenllian", "Hawise", "Isolde", "Juliana", "Katherine", "Lettice",
    "Mabel", "Nichola", "Orabel", "Petronilla", "Richenda", "Sybil",
    "Thomasine", "Ursula", "Winifred", "Aldith", "Benedicta", "Clarice",
    "Denise", "Emmeline", "Felicia", "Gunnhild", "Heloise",
]

MEDIEVAL_SURNAMES: list[str] = [
    "Ashford", "Blackwood", "Crane", "Dunmore", "Edgeworth", "Fenwick",
    "Greymantle", "Halewood", "Ironside", "Juniper", "Kestrel", "Longstride",
    "Marsh", "Nighthollow", "Oakenshield", "Proudfoot", "Quickthorn", "Ravenmoor",
    "Silverleaf", "Thorn", "Underhill", "Vane", "Whitmore", "Yarrow",
    "Coldwater", "Dawnwood", "Emberton", "Flint", "Goldenrod", "Hartwell",
]

TAVERN_PREFIXES: dict[str, list[str]] = {
    "rustic": ["The Muddy", "The Tattered", "The Crooked", "The Weary", "The Leaky", "The Stumbling"],
    "merchant": ["The Golden", "The Silver", "The Gilded", "The Velvet", "The Prosperous"],
    "harbor": ["The Salted", "The Anchor's", "The Drowned", "The Barnacled", "The Gull's"],
}

TAVERN_NOUNS: list[str] = [
    "Flagon", "Hearth", "Boar", "Lantern", "Wheel", "Anchor", "Crow", "Kettle",
    "Barrel", "Hound", "Sparrow", "Hammer", "Bell", "Ox", "Rooster", "Plough",
]


def generate_patron_name(gender: str = "any") -> str:
    """Generate a medieval-style patron name.

    Args:
        gender: "male", "female", or "any" (random)
    """
    if gender == "male":
        first = fake.random_element(MEDIEVAL_FIRST_NAMES_MALE)
    elif gender == "female":
        first = fake.random_element(MEDIEVAL_FIRST_NAMES_FEMALE)
    else:
        pool = MEDIEVAL_FIRST_NAMES_MALE + MEDIEVAL_FIRST_NAMES_FEMALE
        first = fake.random_element(pool)
    last = fake.random_element(MEDIEVAL_SURNAMES)
    return f"{first} {last}"


def generate_tavern_name(theme: str) -> str:
    """Generate a tavern name based on the tavern template's name_theme field.

    Args:
        theme: Template's name_theme value (e.g. "rustic", "merchant", "harbor")
    """
    prefix_list = TAVERN_PREFIXES.get(theme, TAVERN_PREFIXES["rustic"])
    prefix = fake.random_element(prefix_list)
    noun = fake.random_element(TAVERN_NOUNS)
    return f"{prefix} {noun}"
