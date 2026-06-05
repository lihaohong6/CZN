from string import Template

from char_info.characters import combatant_pages, parse_characters, parse_character_info
from char_info.favourite_gifts import parse_favourite_gifts
from utils.wiki_utils import save_wikitext_page


def possessive_pronoun(gender: str) -> str:
    return {
        "Female": "her",
        "Male": "his",
    }.get(gender, "their")


def auto_create_combatant_pages():
    template = Template("""{{Combatant Tab}}
{{Combatant Infobox
|name             = $name
|image            = Combatant $name Splash Art.png
|type             = Playable

<!--Playable Character Information-->
|rarity           = $rarity
|class            = $class_
|attribute        = $attribute

<!--Playable Character Release Information-->
|releaseVersion   =
|releaseDate      =

<!--Character Information-->
|title            =
|otherName        = $otherName
|gender           = $gender
|species          = $species
|birthDate        = $birthDate
|affiliation      = $affiliation
|gift             = $gift

<!-- VAs -->
|voiceJP          = $voiceJP
|voiceKR          = $voiceKR
|voiceCN          = $voiceCN
}}
'''$name''' is a playable character in Chaos Zero Nightmare.

== Game Description ==
{{CharacterInfo}}

== Promotion ==
{{Combatant Promotion|class=$class_}}

== Ego Manifestation ==
{{EgoManifestation}}

== Affinity ==
=== Gifts ===
{{FavouriteGifts}}

=== Affinity rewards ===
{{AffinityRewards}}

==Gallery==
{{GallerySection|{{ROOTPAGENAME}}}}

==Navigation==
{{Combatant Navbox}}
""")

    characters = parse_characters()
    char_info = parse_character_info()
    favourite_gifts = parse_favourite_gifts()
    pages = {p.title(with_ns=False): p for p in combatant_pages()}

    for char in characters.values():
        if not char.playable:
            continue
        info = char_info.get(char.id, {})
        gifts = favourite_gifts.get(char.id, [])

        birth_day = info.get("birth_day", "")
        birth_month = info.get("birth_month", "")
        birth_date = f"{birth_month} {birth_day}".strip() if birth_day or birth_month else ""

        def clean_cv(val):
            return "" if not val or val == "Not included" else val

        text = template.safe_substitute(
            name=char.name,
            rarity=char.rarity,
            class_=char.class_,
            attribute=char.attribute,
            otherName=char.english_name,
            gender=char.gender,
            affiliation=char.affiliation,
            species=info.get("race_type", ""),
            birthDate=birth_date,
            gift=gifts[0] if gifts else "",
            voiceJP=clean_cv(info.get("cv_ja")),
            voiceKR=clean_cv(info.get("cv_ko")),
            voiceCN=clean_cv(info.get("cv_zhs")),
        )

        p = pages[char.name]
        if p.exists():
            continue
        save_wikitext_page(p, text, summary="auto-create combatant page")


def auto_create_counseling_pages():
    template = Template("""{{Combatant NavTab}}
This page is about $name's counseling to relieve $pronoun trauma.
----
{{Counseling|$name}}
[[Category:Counseling pages]]
""")

    characters = parse_characters()
    pages = {p.title(with_ns=False): p for p in combatant_pages("/counseling")}

    for char in characters.values():
        if not char.playable:
            continue

        page_title = f"{char.name}/counseling"
        p = pages[page_title]
        if p.exists():
            continue

        text = template.safe_substitute(
            name=char.name,
            pronoun=possessive_pronoun(char.gender),
        )
        save_wikitext_page(p, text, summary="auto-create counseling page")


def main():
    auto_create_combatant_pages()
    auto_create_counseling_pages()


if __name__ == '__main__':
    main()
