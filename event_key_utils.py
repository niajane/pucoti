import pygame.locals as pg
import pygame

NUMBER_KEYS = [pg.K_0, pg.K_1, pg.K_2, pg.K_3, pg.K_4, pg.K_5, pg.K_6, pg.K_7, pg.K_8, pg.K_9]

def shift_is_pressed():
    return pygame.key.get_mods() & pg.KMOD_SHIFT

def get_number_from_key(key):
    return int(pygame.key.name(key))
