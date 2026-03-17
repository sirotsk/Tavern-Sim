"""
Standalone portrait generation tool for Peasant Simulator: Tavern Edition.
Calls Gemini API to produce 1024x1024 pixel art portraits for patron and barkeep archetypes.

Usage:
    py tools/generate_portrait.py --archetype <id> --gender <male|female> --type <patron|barkeep>
    py tools/generate_portrait.py --list
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path so `game.*` imports work when invoked as
# `py tools/generate_portrait.py` from the project root directory.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

from game.gemini_image_utils import generate_image_from_prompt, resize_and_save

# ---------------------------------------------------------------------------
# Shared pixel art style block appended to every generation prompt
# ---------------------------------------------------------------------------
STYLE_BLOCK = (
    "Pixel art portrait. Bust-length composition, subject centered, looking toward viewer.\n"
    "Background: medieval tavern interior, warm candlelit amber and orange tones, wooden beams visible.\n"
    "Style: 2D pixel art RPG character portrait, limited warm color palette (ambers, browns, earthy reds),\n"
    "visible pixellation, hand-crafted sprite aesthetic, no anti-aliasing, no photo-realism, no 3D rendering.\n"
    "Square canvas."
)

# ---------------------------------------------------------------------------
# Character prompts — (archetype_id, gender) -> description string
# ---------------------------------------------------------------------------
CHARACTER_PROMPTS: dict[tuple[str, str], str] = {
    # -----------------------------------------------------------------------
    # Patron archetypes
    # -----------------------------------------------------------------------

    # madman (dual-gender) — paranoid, erratic, sees plots everywhere
    ("madman", "male"): (
        "A local conspiracy ranter in a medieval tavern. Paranoid, erratic, surprisingly lucid at odd moments. "
        "Wild-eyed man with disheveled unkempt hair, tattered dirt-stained clothes, unshaven hollow face. "
        "He leans forward intensely, gripping a scrap of parchment, wide unfocused eyes darting sideways. "
        "He looks genuinely unsettling and frightening. "
        "A dark shadowy corner of the tavern behind him, flickering candlelight casting long shadows."
    ),
    ("madman", "female"): (
        "A local conspiracy ranter in a medieval tavern. Paranoid, erratic, surprisingly lucid at odd moments. "
        "Wild-eyed woman with tangled matted hair half-covering her gaunt face, patched ragged dress. "
        "She leans in too close, expression manic and unsettling, eyes gleaming with feverish intensity. "
        "She looks genuinely frightening and unhinged. "
        "A dark shadowy corner of the tavern behind her, flickering candlelight casting long shadows."
    ),

    # friar (male only) — smooth-talking, suspiciously well-fed, worldly beneath the piety
    ("friar", "male"): (
        "A wandering mendicant friar in a medieval tavern. Smooth-talking, suspiciously well-fed, "
        "worldly beneath the piety. Quotes scripture before ordering the better cut of meat. "
        "Portly man in his 50s in plain brown robes with a rope belt, tonsured head with grey-fringed hair, "
        "round ruddy face with knowing eyes and an unctuous smile. He sits at a tavern table with a cup of wine "
        "and a generous plate of food. Warm tavern interior behind him."
    ),

    # pilgrim (dual-gender) — devout, road-worn, quietly resolute
    ("pilgrim", "male"): (
        "A pilgrim resting at a medieval tavern. Devout, road-worn, quietly resolute. "
        "Weathered man in a dusty traveling cloak and broad-brimmed hat, wooden walking staff leaning beside him. "
        "His face is wind-burned and deeply lined from the road, eyes carrying quiet resolve. "
        "He sits at a rough tavern table with a simple meal. Warm tavern interior behind him."
    ),
    ("pilgrim", "female"): (
        "A pilgrim resting at a medieval tavern. Devout, road-worn, quietly resolute. "
        "Road-weary woman in a dusty traveling cloak and broad-brimmed hat, mud-splashed boots. "
        "Wooden walking staff leans at her side. Her face is tanned and weathered, "
        "tired but determined eyes. She sits at a rough tavern table. Warm tavern interior behind her."
    ),

    # cutpurse (dual-gender) — evasive, quick-witted, acutely observant
    ("cutpurse", "male"): (
        "A petty thief and pickpocket sitting in a medieval tavern. Evasive, quick-witted, acutely observant. "
        "Keeps careful track of everyone who comes through the door. "
        "Sharp-eyed man in his 30s in a dark hooded cloak, leather gloves, one eyebrow raised in a sly calculating smirk. "
        "He sits in a shadowy corner of the tavern, eyes scanning the room. Coin pouches at his belt. "
        "Warm but dim tavern interior behind him."
    ),
    ("cutpurse", "female"): (
        "A petty thief and pickpocket sitting in a medieval tavern. Evasive, quick-witted, acutely observant. "
        "Keeps careful track of everyone who comes through the door. "
        "Sharp-featured woman in her 20s in a hooded cloak with clever darting eyes and a sly half-smile. "
        "Fingerless leather gloves, one hand hidden under her cloak. She sits in a shadowy tavern corner. "
        "Warm but dim tavern interior behind her."
    ),

    # blacksmith (dual-gender) — strong, practical, takes pride in the craft
    ("blacksmith", "male"): (
        "A blacksmith visiting a medieval tavern after work. Strong, practical, takes pride in the craft. "
        "Broad-shouldered man with a strong jaw, soot-stained skin, heavy leather apron still on. "
        "Muscular arms rest on the tavern table, hands calloused and scarred from the forge. "
        "A tankard of ale in front of him. Warm tavern interior behind him."
    ),
    ("blacksmith", "female"): (
        "A blacksmith visiting a medieval tavern after work. Strong, practical, takes pride in the craft. "
        "Sturdy woman with powerful arms, soot marks on her face, leather apron, close-cropped hair under a cloth cap. "
        "Her expression is confident and competent, calloused hands wrapped around a tankard. "
        "Warm tavern interior behind her."
    ),

    # beggar (dual-gender) — deferential on surface, surprisingly sharp, patient observer
    ("beggar", "male"): (
        "A displaced person and beggar in a medieval tavern. Deferential on the surface but surprisingly sharp. "
        "Lost his family's land after the plague. Knows things nobody intended him to know. "
        "Thin gaunt man with hollow cheeks, sunken but watchful eyes, deeply patched ragged clothing. "
        "He sits hunched at the edge of a tavern bench, battered wooden bowl on the table. "
        "Dim quiet corner of the tavern behind him."
    ),
    ("beggar", "female"): (
        "A displaced person and beggar in a medieval tavern. Deferential on the surface but surprisingly sharp. "
        "Was comfortable once, not so long ago. Knows things nobody intended her to know. "
        "Frail woman with lank hair, deeply lined face, tired but watchful eyes, ragged heavily mended clothes. "
        "She sits hunched at the edge of a tavern bench, bony hands cupped around a wooden bowl. "
        "Dim quiet corner of the tavern behind her."
    ),

    # duder (male only) — sturdy Jewish hustler, full of life
    ("duder", "male"): (
        "A sturdy jovial Jewish man in his 30s in a medieval tavern, full of life and laughter. "
        "Thick brown beard, neatly kept but full — not overly long. Brown curly hair. Thick round spectacles. Warm brown eyes sparkling with mischief. "
        "Rosy cheeks, broad confident grin. Wearing thick cowhide gauntlets resting on the tavern table. "
        "Stocky build, gregarious energy. Looks like he is about to pitch you on a deal. "
        "A tankard of ale in front of him. Warm tavern interior behind him."
    ),

    # plague_doctor (male only) — clinically detached, eerily calm
    ("plague_doctor", "male"): (
        "A physician and plague doctor in a medieval tavern. Clinically detached, eerily calm, "
        "comfortable with things others find disturbing. "
        "Classic full costume: long dark leather coat, wide-brimmed black hat, "
        "the unmistakable long beaked bird mask with glass-lensed eye pieces. Heavy leather gloves. "
        "He sits at a tavern table. The background is darker and moody, faint candlelight giving an eerie amber rim."
    ),

    # soldier (male only) — disciplined, blunt, uneasy in peacetime
    ("soldier", "male"): (
        "A soldier or former soldier in a medieval tavern. Disciplined, blunt, loyal to comrades, uneasy in peacetime. "
        "Returned from the French campaigns with nothing but scars and a few coins. "
        "Broad-shouldered man in his 30s in a worn gambeson and leather bracers, weathered face with old scars. "
        "He sits at a tavern table with a tankard, eyes steady and watchful. "
        "Warm tavern interior behind him."
    ),

    # laborer (dual-gender) — straightforward, tired, proud of their work
    ("laborer", "male"): (
        "A laborer at a medieval tavern after a hard day's work. Straightforward, tired, proud of his work. "
        "Spending part of the wages on a decent meal. Plain speech, no fancy words. "
        "Sturdy broad-shouldered man with rough calloused hands, simple work clothes stained with labor. "
        "He sits at a tavern table with a tankard and a plate of food, expression tired but content. "
        "Warm tavern interior behind him."
    ),
    ("laborer", "female"): (
        "A laborer at a medieval tavern after a hard day's work. Straightforward, tired, proud of her work. "
        "Spending part of the wages on a decent meal. Plain speech, no fancy words. "
        "Sturdy woman with rough calloused hands, simple work dress and apron stained with labor, "
        "cloth tied in her hair. She sits at a tavern table with a tankard, expression tired but capable. "
        "Warm tavern interior behind her."
    ),

    # scholar (dual-gender) — curious, verbose, socially awkward
    ("scholar", "male"): (
        "A scholar or clerk in a medieval tavern. Curious, verbose, socially awkward, quick to correct errors. "
        "Researching something specific that brought him to this town. "
        "Thin man in his 40s in neat scholarly robes, ink-stained fingers, a quill tucked behind his ear. "
        "He sits at a tavern table with an open book and a cup, absorbed in thought. "
        "Warm tavern interior behind him."
    ),
    ("scholar", "female"): (
        "A scholar or clerk in a medieval tavern. Curious, verbose, socially awkward, quick to correct errors. "
        "Carrying documents that make her nervous in public. "
        "Sharp-featured woman in her 30s in neat scholarly robes, round spectacles on her nose, "
        "ink-stained fingers, hair pinned back neatly. She sits at a tavern table with an open book and quill. "
        "Warm tavern interior behind her."
    ),

    # farmer (dual-gender) — patient, suspicious of city folk, deeply practical
    ("farmer", "male"): (
        "A farmer or rural smallholder in a medieval tavern. Patient, suspicious of city folk, deeply practical. "
        "In town to sell goods at market, treating himself before the road home. "
        "Weathered man in his 40s in simple rough-spun clothes, sun-browned face with deep lines, "
        "large calloused hands wrapped around a tankard. He sits at a tavern table. "
        "Warm tavern interior behind him."
    ),
    ("farmer", "female"): (
        "A farmwoman in a medieval tavern. Patient, quietly proud, deeply practical. "
        "In town to sell goods at market. Lost half the household to the pestilence. "
        "Weathered woman in her 40s in a wide sun hat pushed back, practical apron, "
        "sun-bronzed face with laugh lines around her eyes. She sits at a tavern table with a cup. "
        "Warm tavern interior behind her."
    ),

    # herbalist (dual-gender) — calm, unsettling to the superstitious, matter-of-fact
    ("herbalist", "male"): (
        "A herbalist and healer in a medieval tavern. Calm, unsettling to the superstitious, "
        "matter-of-fact about strange things. Pauses before speaking. "
        "Lean man in his 50s with knowing eyes, wearing a simple tunic with pouches of dried herbs at his belt. "
        "He sits at a tavern table with a small mortar and pestle, bundles of herbs beside him. "
        "Warm tavern interior behind him."
    ),
    ("herbalist", "female"): (
        "A herbalist, healer, and hedge-witch in a medieval tavern. Calm, unsettling to the superstitious, "
        "matter-of-fact about strange things. Carries herbs people associate with the old practices. "
        "Woman in her 40s with braided hair woven through with dried flowers and herbs, "
        "green-tinted work apron, knowing calm eyes. She sits at a tavern table with a mortar and pestle. "
        "Warm tavern interior behind her."
    ),

    # bard (dual-gender) — charming, observant, fond of an audience
    ("bard", "male"): (
        "A traveling bard and storyteller in a medieval tavern. Charming, observant, fond of an audience. "
        "Collecting stories and gossip to weave into future performances. Laughs at his own jokes. "
        "Expressive man in his 30s in colorful traveler's clothes with a feathered cap, "
        "holding a lute, animated expression, eyes bright with mischief. "
        "He sits at a tavern table. Warm tavern interior behind him."
    ),
    ("bard", "female"): (
        "A traveling bard and storyteller in a medieval tavern. Charming, observant, fond of an audience. "
        "Has a new song almost finished that could make or break her reputation. "
        "Vivacious woman in her 20s in flowing colorful traveler's clothes, feathered cap tilted rakishly, "
        "holding a small tambourine, expression animated and expressive. "
        "She sits at a tavern table. Warm tavern interior behind her."
    ),

    # noble (dual-gender) — accustomed to deference, easily bored, unexpectedly perceptive
    ("noble", "male"): (
        "A minor noble slumming it incognito in a medieval tavern. Accustomed to deference, easily bored, "
        "unexpectedly perceptive. Polished but never quite knows how to talk to common people. "
        "Well-dressed man in his 30s trying to look ordinary but failing — fine cloth, clean hands, "
        "straight posture that betrays breeding. He looks slightly out of place. "
        "A cup of wine in front of him. Warm tavern interior behind him."
    ),
    ("noble", "female"): (
        "A minor noblewoman in a medieval tavern, fleeing an arranged marriage or family embarrassment. "
        "Accustomed to deference, unexpectedly perceptive. "
        "Well-dressed woman in her 20s trying to look ordinary but failing — fine embroidered clothes, "
        "clean soft hands, composed bearing that betrays noble upbringing. She looks slightly out of place. "
        "A cup of wine in front of her. Warm tavern interior behind her."
    ),

    # traveling_merchant (dual-gender) — shrewd, worldly, politely suspicious
    ("traveling_merchant", "male"): (
        "A traveling merchant in a medieval tavern. Shrewd, worldly, guarded with money, politely suspicious. "
        "Recently arrived from a long journey through difficult roads. "
        "Weathered man in his 40s in practical but quality traveling clothes, a leather satchel at his side, "
        "calculating eyes above a carefully neutral expression. "
        "He sits at a tavern table with a cup. Warm tavern interior behind him."
    ),
    ("traveling_merchant", "female"): (
        "A traveling merchant in a medieval tavern. Shrewd, worldly, guarded with money, politely suspicious. "
        "Considering whether to expand into more profitable but riskier goods. "
        "Sharp-eyed woman in her 30s in practical but quality traveling clothes, leather satchel at her side, "
        "assessing gaze and carefully composed expression. "
        "She sits at a tavern table with a cup. Warm tavern interior behind her."
    ),

    # -----------------------------------------------------------------------
    # Barkeep archetypes — 13 entries (9 new + 4 remade)
    # -----------------------------------------------------------------------

    # lay_brother (male only)
    ("lay_brother", "male"): (
        "A mature adult monastery lay brother and guesthouse keeper in his 40s. Quiet, devout, deliberate, "
        "faintly disapproving of excess. He took his vows late in life and brews the monastery ale himself. "
        "Wearing a plain brown habit with rope belt, tonsured head, weathered lined face with deep-set serious eyes. "
        "He stands behind a simple wooden bar counter wiping a tankard with a cloth. "
        "Sparse stone monastery walls and warm candlelight in the background."
    ),

    # scarred_survivor (dual-gender)
    ("scarred_survivor", "male"): (
        "A wary, battle-hardened male barkeep at a remote waystation. Deep scars across one side of his face, "
        "a milky clouded eye. Few words, watches the door, calm under pressure. "
        "He wears a worn leather vest over a rough linen shirt with an ale-stained apron. "
        "He stands behind the bar counter, thick scarred arms resting on the bar top, tankards and bottles "
        "on rough shelves behind him. A weapon is half-hidden behind the bar."
    ),
    ("scarred_survivor", "female"): (
        "A wary, tough woman working as barkeep at a remote waystation. Prominent battle scars across her face, "
        "one eye slightly milky. Few words, always watching the room, calm under pressure. "
        "She wears a leather vest and ale-stained apron over a rough shirt. "
        "She stands behind a wooden bar counter, one hand resting on a tankard. "
        "Bottles and mugs on rough shelves behind her. A weapon handle is visible behind the bar."
    ),

    # retired_soldier (male only)
    ("retired_soldier", "male"): (
        "A former soldier turned barkeep in his 50s. Runs a tight ship, direct, respects rank and competence, "
        "little patience for disorder. Greying, broad-shouldered, military posture. "
        "He wears a simple tunic with an ale-stained apron, old chain mail visible at the collar. "
        "He stands behind the bar counter, brisk and authoritative. "
        "A shield and faded campaign banner hang on the tavern wall behind him. Mugs and bottles on the shelves."
    ),

    # dour_monk (male only)
    ("dour_monk", "male"): (
        "A monastic barkeep and guesthouse warden. Stern, disapproving of excess, duty-bound, grimly honest. "
        "Assigned to guesthouse duty as penance and has been doing it for eleven years. "
        "Gaunt, severe-looking monk in dark robes with hollow ascetic cheeks and deeply shadowed eyes. "
        "He stands behind a plain wooden bar counter with prayer beads looped over one wrist. "
        "Expression perpetually disapproving. Stone monastery walls and sparse candlelight behind him."
    ),

    # jovial_brewer (dual-gender)
    ("jovial_brewer", "male"): (
        "A barkeep and amateur brewer. Genuinely enthusiastic about ale, talkative, generous. "
        "Once won a small local brewing competition and has not moved past it. "
        "Rotund, red-cheeked man in his 40s with a broad grin and ale-stained apron. "
        "He stands behind the bar counter holding a foaming wooden mug, eyes crinkling with laughter. "
        "Rows of barrels and brewing equipment stacked on shelves behind him."
    ),
    ("jovial_brewer", "female"): (
        "A barkeep and amateur brewer. Genuinely enthusiastic about ale, talkative, generous with her pours. "
        "She experiments with new ingredients every season and always wants your opinion. "
        "Plump, ruddy-faced woman in her 40s with bright eyes and a flour-dusted apron. "
        "She stands behind the bar counter holding a foaming mug, laughing warmly. "
        "Barrels and brew equipment stacked on shelves behind her."
    ),

    # gruff_veteran (male only — regenerate to match new style)
    ("gruff_veteran", "male"): (
        "A barkeep and innkeeper. No-nonsense, observant, dry humor, fair but not soft. "
        "Owns the place outright and doesn't let anyone forget it. Has heard everything already. "
        "Broad-shouldered, weathered man in his 50s with a stern, lined face and thick forearms. "
        "He stands behind a scarred oak bar counter wearing an ale-stained leather apron. "
        "Bottles and tankards on rough wooden shelves behind him."
    ),
    ("motherly_alewife", "female"): (
        "A middle-aged alewife and barkeep. Imperturbable, sharp-eyed, tough but genuinely caring. "
        "Plump and sturdy with weathered hands, wearing a practical ale-stained apron. "
        "Her face is warm but knowing — she's survived something and made peace with it. "
        "She stands behind the bar, pouring generously from a jug. "
        "A cozy tavern with hanging pots and wooden shelves behind her."
    ),

    # sly_merchant (dual-gender)
    ("sly_merchant", "male"): (
        "A barkeep and establishment manager. Professional, discreet, quietly ambitious, reads people quickly. "
        "Manages the establishment for an absent owner. Has a network of contacts. "
        "Well-groomed man in his 40s with calculating eyes and a thin, practiced smile. "
        "He stands behind the bar counter in fine but understated clothes with an apron, coin purse at belt. "
        "An open ledger and abacus sit on the bar beside him. Bottles on neat shelves behind."
    ),
    ("sly_merchant", "female"): (
        "A barkeep and establishment manager. Professional, discreet, quietly ambitious, reads people quickly. "
        "Remembers what regulars order and suggests the better option when asked. "
        "Sharp-featured woman in her 30s with assessing eyes and a polished, courteous smile. "
        "She stands behind the bar counter in well-tailored clothes with an apron, coin purse at belt. "
        "A ledger and quill rest on the bar beside her. Bottles on neat shelves behind."
    ),
}

# ---------------------------------------------------------------------------
# Output directories relative to project root
# ---------------------------------------------------------------------------
PATRON_DIR = Path("static/portraits/patrons")
BARKEEP_DIR = Path("static/portraits/barkeeps")

DEFAULT_MODEL = "gemini-2.0-flash-exp-image-generation"


def generate_portrait(
    archetype_id: str,
    gender: str,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
) -> Path:
    """
    Generate a portrait for the given archetype/gender and save it to output_dir.

    Args:
        archetype_id: The archetype identifier (e.g. "madman", "friar").
        gender: "male" or "female".
        output_dir: Directory where the PNG will be saved.
        model: Gemini model ID for image generation.

    Returns:
        Path to the saved PNG file.

    Raises:
        KeyError: If the archetype/gender combo is not in CHARACTER_PROMPTS.
        RuntimeError: If Gemini returns no image in the response.
    """
    key = (archetype_id, gender)
    if key not in CHARACTER_PROMPTS:
        raise KeyError(
            f"No prompt defined for ({archetype_id!r}, {gender!r}). "
            f"Run --list to see available combinations."
        )

    character_desc = CHARACTER_PROMPTS[key]
    prompt = f"{character_desc}\n\n{STYLE_BLOCK}"

    load_dotenv()

    print(f"Generating portrait: {archetype_id}_{gender} via {model}...")
    image_bytes = generate_image_from_prompt(prompt, model)
    if image_bytes is None:
        raise RuntimeError(
            f"No image returned by Gemini for ({archetype_id!r}, {gender!r})."
        )

    out_path = output_dir / f"{archetype_id}_{gender}.png"
    resize_and_save(image_bytes, out_path, 1024, 1024)
    print(f"Saved: {out_path}")
    return out_path


def list_combinations() -> None:
    """Print all available archetype/gender combinations."""
    patron_entries = sorted(
        (k, v) for k, v in CHARACTER_PROMPTS.items()
        if k[0] in {
            "madman", "friar", "pilgrim", "cutpurse", "blacksmith", "beggar",
            "duder", "plague_doctor", "laborer", "scholar", "farmer", "herbalist", "bard",
        }
    )
    barkeep_entries = sorted(
        (k, v) for k, v in CHARACTER_PROMPTS.items()
        if k[0] in {
            "lay_brother", "scarred_survivor", "retired_soldier", "dour_monk",
            "jovial_brewer", "gruff_veteran", "motherly_alewife", "sly_merchant",
        }
    )

    print(f"Available portrait combinations ({len(CHARACTER_PROMPTS)} total):\n")
    print("PATRONS:")
    for (archetype_id, gender), _ in patron_entries:
        print(f"  {archetype_id:<20} {gender}")
    print(f"\nBARKEEPS:")
    for (archetype_id, gender), _ in barkeep_entries:
        print(f"  {archetype_id:<20} {gender}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a pixel art portrait via Gemini API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  py tools/generate_portrait.py --list\n"
            "  py tools/generate_portrait.py --archetype madman --gender male --type patron\n"
            "  py tools/generate_portrait.py --archetype gruff_veteran --gender female --type barkeep\n"
            "  py tools/generate_portrait.py --archetype sly_merchant --gender male --type barkeep "
            "--model gemini-2.5-flash-image\n"
        ),
    )
    parser.add_argument(
        "--archetype",
        metavar="ID",
        help="Archetype identifier (e.g. madman, friar, gruff_veteran).",
    )
    parser.add_argument(
        "--gender",
        choices=["male", "female"],
        help="Gender variant to generate.",
    )
    parser.add_argument(
        "--type",
        dest="portrait_type",
        choices=["patron", "barkeep"],
        help='Portrait category — determines output directory ("patron" or "barkeep").',
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        metavar="MODEL_ID",
        help=f"Gemini model to use (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available archetype/gender combinations and exit.",
    )

    args = parser.parse_args()

    if args.list:
        list_combinations()
        return

    # Validate required args when not using --list
    missing = [
        flag for flag, val in [
            ("--archetype", args.archetype),
            ("--gender", args.gender),
            ("--type", args.portrait_type),
        ]
        if val is None
    ]
    if missing:
        parser.error(f"The following arguments are required: {', '.join(missing)}")

    archetype_id = args.archetype.strip().lower()
    gender = args.gender.strip().lower()
    key = (archetype_id, gender)

    if key not in CHARACTER_PROMPTS:
        print(
            f"Error: No prompt defined for archetype={archetype_id!r}, gender={gender!r}.\n"
            f"Run --list to see available combinations.",
            file=sys.stderr,
        )
        sys.exit(1)

    output_dir = PATRON_DIR if args.portrait_type == "patron" else BARKEEP_DIR

    try:
        out_path = generate_portrait(archetype_id, gender, output_dir, model=args.model)
        print(f"Portrait saved to: {out_path}")
        # Rate limit courtesy — free tier is 10 RPM
        time.sleep(6)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
