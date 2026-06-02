from char_info.cards import save_cards
from char_info.characters import save_character_info
from char_info.counseling import save_counseling
from char_info.ego_manifestation import save_ego_manifestations


def main():
    save_character_info()
    save_ego_manifestations()
    save_cards()
    save_counseling()


if __name__ == "__main__":
    main()
