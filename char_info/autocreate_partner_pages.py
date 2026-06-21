from string import Template

from pywikibot import Page
from pywikibot.pagegenerators import PreloadingGenerator

from char_info.partners import parse_partner_info
from utils.wiki_utils import save_wikitext_page, s


def partner_pages() -> list[Page]:
    pages = [Page(s, info["name"]) for info in parse_partner_info().values()]
    return list(PreloadingGenerator(pages))


def auto_create_partner_pages():
    template = Template("""{{Partner Infobox|name=$name}}

'''$name''' is a partner in Chaos Zero Nightmare.

==Game Description==
{{Partner Description|name=$name}}

==Ego Skill==
{{Partner Ego Skill|name=$name}}

==Passive Skill==
{{Partner Passive Skill|name=$name}}

==Gallery==
{{Partner Gallery|name=$name}}

==Voice==

==Navigation==
{{Partner Navbox}}""")

    pages = {p.title(with_ns=False): p for p in partner_pages()}
    for info in sorted(parse_partner_info().values(), key=lambda partner: partner["id"]):
        p = pages[info["name"]]
        if p.exists():
            continue

        text = template.safe_substitute(name=info["name"])
        save_wikitext_page(p, text, summary="auto-create partner page")


def main():
    auto_create_partner_pages()


if __name__ == "__main__":
    main()
