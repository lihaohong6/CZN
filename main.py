from cards import save_cards
from characters import save_character_info
from ego_manifestation import save_ego_manifestations


def main():
    save_character_info()
    save_ego_manifestations()
    save_cards()


if __name__ == "__main__":
    main()
