"""
build_seeds.py — Generate data/voices/seed/{warm_club,hype,data_led}.json
by running the inducer over realistic exemplar posts.

Run once during build:
  python build_seeds.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make sure imports work from project root
sys.path.insert(0, str(Path(__file__).parent))

from voice.learned.induce import induce_voice
from voice.learned.store import load_voice_from_path

SEED_DIR = Path(__file__).parent / "data" / "voices" / "seed"
SEED_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Seed 1: Warm Club voice
# ---------------------------------------------------------------------------

WARM_CLUB_EXEMPLARS = [
    """Huge well done to Emily Davies on her stunning PB in the 100m Butterfly last night at Cardiff Open! 🦋
Emily touched the wall in 1:02.45 — knocking nearly two seconds off her previous best.
So proud of the hard work she has put in this season!
Well done Emily — the whole club is behind you 💙
#SwimSwansea #ButterflyGirl #ClubProud""",

    """Congratulations to our Junior Boys relay team for a brilliant performance at Welsh Age Groups! 🏊
The lads went 3:34.12 in the 4×100 Medley — a new club record!
Massive effort from Rhys, Callum, Tom and Jack — you all deserve this result 🙌
So proud of every single one of you!
#SwimSwansea #TeamSwim #ClubRecord""",

    """A huge shout-out to Sophie Williams who claimed a fantastic silver medal in the 200m Breaststroke at the Welsh Championships today! 🥈
Sophie swam 2:41.76 — another PB to add to her growing collection!
We love watching you race, Sophie — keep it going! 💙
#SwimSwansea #WelshChamps #Breaststroke""",

    """What a night at the club gala! 🌟
Special mention to young Ollie, 11 years old, who smashed his PB in the 50m Freestyle with a time of 29.88 — breaking the 30-second barrier for the first time!
Big things ahead for this lad 💪
Proud of all our swimmers tonight — every single one of you worked hard and it showed!
#SwimSwansea #YoungSwimmers #FutureStars""",

    """Brilliant results for our masters swimmers at the South Wales Short Course Open last weekend!
Special mention to Margaret Jones, who set three personal bests and won gold in the W55 100m Backstroke in 1:24.33! 🥇
Proof that hard work pays off at any age — incredible stuff Margaret!
#SwimSwansea #MastersSwimming #NeverStopSwimming""",
]

# ---------------------------------------------------------------------------
# Seed 2: Hype voice
# ---------------------------------------------------------------------------

HYPE_EXEMPLARS = [
    """🔥🔥 YESSS!! BIG PB ALERT 🚨
Josh Carpenter absolutely DESTROYS his 100m Freestyle time at the National Age Groups!!
NEW PB: 51.34 — DOWN FROM 53.01 💥
THIS LAD IS UNSTOPPABLE RIGHT NOW 🤯
Been building all season and today he DELIVERED. Elite performance, elite swimmer 👑
#NationalAgeGroups #100mFree #PBSzn #SwimHard #SwimFast""",

    """GOLD GOLD GOLD 🥇🥇🥇
Mia Torres WINS the 200m IM at South of England Champs AND goes UNDER 2:20 FOR THE FIRST TIME 🔥
2:19.81 — WHAT A SWIM 🏊💨
This girl is on another level right now. Put some RESPECT on her name 👏👏👏
#SOE #200IM #GoldMedal #SheGoesOff""",

    """TEAM RELAY GOES OFF 🚀🚀
4×100 Mixed Medley → NEW CLUB RECORD 3:52.44 💥💥
Four of our best doing what they do. That last leg was INSANE — the comeback was REAL 😤
Tags on the squad who WENT FOR IT today 🙌
#RelayNation #ClubRecord #MixedMedley #LFG""",

    """POV: you just watched your swimmer drop THREE seconds in the 200m Fly 🦋🔥
Zara Ahmed → 2:17.08 🤯 (was 2:20.31)
THE HARD WORK IS PAYING OFF. NOTHING STOPPING HER NOW 💪💪
Loud for Zara in the comments 👇👇
#200Fly #DropTime #ButterflyQueen #SwimSeason""",

    """NATIONALS PODIUM 🏅🏅🏅
Three of our swimmers on the medal table this weekend — WE ARE THAT CLUB 🔥
Results are IN, and they are ELITE:
🥇 Leo Carter — 50m Back — 27.11 (NR!)
🥈 Nina Walsh — 400m Free — 4:22.06 (PB)
🥉 Josh Carpenter — 100m Free — 51.34 (PB)
INCREDIBLE stuff from these three. FIRED UP for the rest of the season 🚀🚀
#Nationals #PodiumAlert #SwimClub #ProudCoach""",
]

# ---------------------------------------------------------------------------
# Seed 3: Data-led voice
# ---------------------------------------------------------------------------

DATA_LED_EXEMPLARS = [
    """Welsh Age Groups | Day 2 Recap

200m Freestyle — Senior Women
1st: Harriet Clarke — 2:05.43 (PB, −1.22s)
3rd: Lucy Parry — 2:09.87 (season best)

100m Backstroke — Junior Men
2nd: Daniel Owen — 58.01 (PB, −0.94s)

Strong day across the distance events. Clarke's 200m Freestyle time now places her 14th on the senior Welsh rankings. Owen's backstroke split is a notable improvement; his relay leg target for March is sub-57.50.

Full splits available in the club portal.
#SwimData #AgeGroups #PerformanceAnalysis""",

    """British Championships — Day 1 Results

Event: 400m IM — Open Women
Swimmer: Jess Hammond
Time: 4:51.07 | PB: 4:51.07 (−3.44s from previous best)
Split breakdown:
  Fly  65.3 | Back  74.1 | Breast  86.2 | Free  65.47

Observation: breaststroke split was the rate-limiter (previous avg: 83.1). Fly and backstroke both season-best halves. Free leg consistent with Jan taper.

Action: focus breaststroke race-pace sets in mesocycle 4.
#BritishChamps #SplitAnalysis #400IM""",

    """Short Course Open | Club Performance Summary

Entries: 47 swims across 22 athletes
PBs recorded: 14 (29.8% of swims)
Season bests (non-PB): 9

Top improvements by percentage drop:
  1. Ryan Bowen  50m Fly  −2.8% (26.03 → 25.30)
  2. Amy Chen    100m Breast −2.1% (1:18.44 → 1:16.79)
  3. Sam Patel   200m Free  −1.9% (1:58.23 → 1:54.48)

Podium finishes: 6 (3 gold, 2 silver, 1 bronze)
Average improvement across all swims: −0.7%
#MeetSummary #SwimAnalytics #PerformanceData""",

    """Training Block 7 — Taper Week Check-in

Target race: National Short Course Champs (3 weeks)

Athlete status by event group:
  Distance (400–1500m): 4 athletes on target, 1 behind on volume
  Sprint (50–100m): 6 athletes on target; dry-land peak load completed
  Middle distance (200m): 3 on target, 1 ahead of curve (monitor for overpeak)

Key metrics — this week vs. taper week last season:
  Avg session RPE: 6.2 (vs. 6.8 prior year)
  Avg 100m pace in main sets: 1:04.3 (vs. 1:05.1 prior year)

Conclusion: squad trending slightly ahead of prior-season taper profile.
#TrainingData #TaperWeek #SwimPerformance""",

    """Post-Meet Analysis | City of Bath Open

Club entries: 31 | Finalists: 18 | Medallists: 5

Performance vs. qualifying time:
  Beat qualifying time: 21 swims (67.7%)
  Within 1%: 6 swims (19.4%)
  Outside 1%: 4 swims (12.9%)

Split efficiency index (actual vs. ideal pacing):
  Best rated: Clara Hooper 200 Back — 0.97 (near-perfect negative split)
  Worst rated: Group C 100 Breast — avg 1.09 (too fast first 50m)

Notes: warm-up pool availability was limited. Factoring into next block planning.
#SplitEfficiency #DataSwim #MeetAnalysis""",
]


# ---------------------------------------------------------------------------
# Induce and write seeds
# ---------------------------------------------------------------------------

def build_seed(filename: str, voice_id: str, display_name: str,
               description: str, exemplars: list) -> None:
    profile = induce_voice(
        voice_id=voice_id,
        display_name=display_name,
        exemplars=exemplars,
        description=description,
    )
    out_path = SEED_DIR / filename
    out_path.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Written: {out_path}")
    # Verify round-trip
    reloaded = load_voice_from_path(out_path)
    assert reloaded.voice_id == voice_id
    assert reloaded.features.avg_sentence_len > 0
    print(f"  → round-trip OK | avg_sentence_len={reloaded.features.avg_sentence_len}")


if __name__ == "__main__":
    build_seed(
        filename="warm_club.json",
        voice_id="warm_club",
        display_name="Warm Club Voice",
        description="Supportive, community-focused club voice with warmth and encouragement.",
        exemplars=WARM_CLUB_EXEMPLARS,
    )
    build_seed(
        filename="hype.json",
        voice_id="hype",
        display_name="Hype Voice",
        description="High-energy, exclamation-heavy voice celebrating every swim loudly.",
        exemplars=HYPE_EXEMPLARS,
    )
    build_seed(
        filename="data_led.json",
        voice_id="data_led",
        display_name="Data-Led Voice",
        description="Analytical, results-focused voice with split data and performance metrics.",
        exemplars=DATA_LED_EXEMPLARS,
    )
    print("\nAll seed files built successfully.")
