#!/usr/bin/env python
from functools import lru_cache
import os
import subprocess
import sys
from time import time
import pygame
from pygame.locals import *
import pygame._sdl2 as sdl2
from pathlib import Path
from pygame.math import Vector2


BELL = Path("./bell.mp3")
RING_INTERVAL = 20
PURPOSE_COLOR = (183, 255, 183)
TIMER_COLOR = (255, 224, 145)
TEXT_TIMES_UP_COLOR = (255, 0, 0)
BACKGROUND_COLOR = (0, 0, 0)
WINDOW_SCALE = 1.2
POSITIONS = [(-5, -5), (5, 5), (5, -5), (-5, 5)]


os.environ['SDL_VIDEODRIVER'] = 'x11'

def fmt_time(seconds):
    if seconds < 0:
        return "-" + fmt_time(-seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    else:
        return "%02d:%02d" % (minutes, seconds)


@lru_cache(maxsize=10)
def font(size: int, big: bool = True):
    name = "./Wellbutrin.ttf" if big else "./Wellbutrin.ttf"
    return pygame.font.Font(name, size)


@lru_cache(maxsize=1000)
def text(text: str, size: int | tuple[int, int], color: tuple, big: bool = True,
         monospaced_time: bool = False):
    if not isinstance(size, int):
        size = auto_size(text, size, big)

    if not monospaced_time:
        return font(size, big).render(text, True, color)
    else:
        digits = "0123456789"
        # We render each char independently to make sure they are monospaced.
        chars = [font(size, big).render(c, True, color) for c in text]
        # Make each digit the size of a 0.
        width = font(size, big).size("0")[0]
        full_width = sum(s.get_width() if c not in digits else width for c, s in zip(text, chars))
        # Create a surface with the correct width.
        surf = pygame.Surface((full_width, chars[0].get_height()))
        # Blit each char at the correct position.
        x = 0
        for c, s in zip(text, chars):
            if c in digits:
                blit_x = x + (width - s.get_width()) // 2
            else:
                blit_x = x
            surf.blit(s, (blit_x, 0))
            x += s.get_width() if c not in digits else width
        return surf


def auto_size(text: str, max_rect: pygame.Rect | tuple[int, int], big_font: bool = True):
    """Find the largest font size that will fit text in max_rect."""
    # Use dichotomy to find the largest font size that will fit text in max_rect.
    if not isinstance(max_rect, pygame.Rect):
        max_rect = pygame.Rect((0, 0), max_rect)

    min_size = 1
    max_size = max_rect.height
    while min_size < max_size:
        font_size = (min_size + max_size) // 2
        text_size = font(font_size, big_font).size(text)

        if text_size[0] <= max_rect.width and text_size[1] <= max_rect.height:
            min_size = font_size + 1
        else:
            max_size = font_size
    return min_size - 1


def place_window(window, x: int, y: int):
    """Place the window at the desired position using sway."""

    # size = subprocess.check_output("swaymsg -t get_outputs | jq '.[] | select(.active) | .current_mode.width, .current_mode.height'", shell=True)
    # size = tuple(map(int, size.split()))
    info = pygame.display.Info()
    size = info.current_w, info.current_h

    if x < 0:
        x = size[0] + x - window.size[0]
    if y < 0:
        y = size[1] + y - window.size[1]

    try:
        cmd = f'swaymsg "[title=\\"DTimer\\"] move absolute position {x} {y}"'
        subprocess.check_output(cmd, shell=True)
    except subprocess.CalledProcessError as e:
        print(e.output)

def play(sound):
    pygame.mixer.music.load(sound)
    pygame.mixer.music.play()


def vsplit(rect, *ratios):
    """Split a rect vertically in ratios."""
    total_ratio = sum(ratios)
    ratios = [r / total_ratio for r in ratios]
    cummulative_ratios = [0] + [sum(ratios[:i]) for i in range(1, len(ratios) + 1)]
    ys = [int(rect.height * r) for r in cummulative_ratios]
    return [pygame.Rect(rect.left, ys[i], rect.width, ys[i + 1] - ys[i]) for i in range(len(ratios))]


def main():
    size = (180, 70)
    pygame.init()
    pygame.mixer.init()
    pygame.key.set_repeat(300, 20)

    pygame.print_debug_info()
    window = sdl2.Window("DTimer", size, borderless=True)
    window.get_surface().fill((0, 0, 0))
    window.flip()

    position = 0
    place_window(window, *POSITIONS[position])

    screen = window.get_surface()

    font_size = auto_size("00:00", screen.get_rect())
    clock = pygame.time.Clock()

    start = time()
    timer = 120
    last_rung = 0

    purpose = ""
    entering_purpose = False

    while True:
        for event in pygame.event.get():
            if event.type == QUIT:
                sys.exit()
            elif event.type == VIDEORESIZE:
                size = event.dict['size']
                font_size = auto_size("00:00", screen.get_rect())
            elif event.type == KEYDOWN:
                if event.key == K_RETURN:
                    entering_purpose = not entering_purpose
                elif entering_purpose:
                    if event.key == K_BACKSPACE:
                        purpose = purpose[:-1]
                    elif event.unicode:
                        purpose += event.unicode
                elif event.key == K_j:
                    timer -= 60
                elif event.key == K_k:
                    timer += 60
                elif event.key == K_MINUS:
                    size = (int(size[0] / WINDOW_SCALE), int(size[1] / WINDOW_SCALE))
                    window.size = size
                    font_size = auto_size("00:00", screen.get_rect())
                elif event.key == K_EQUALS:
                    size = (int(size[0] * WINDOW_SCALE), int(size[1] * WINDOW_SCALE))
                    window.size = size
                    font_size = auto_size("00:00", screen.get_rect())
                elif event.key == K_p:
                    position = (position + 1) % len(POSITIONS)
                    place_window(window, *POSITIONS[position])

        screen.fill(BACKGROUND_COLOR)

        if window.size[1] > 60:
            # Split the window in three areas: top,25%,purpose - middle,50%,time - bottom,25%,controls
            purpose_rect, time_rect, controls_rect = vsplit(screen.get_rect(), 1, 2, 1)

            t = text(purpose, purpose_rect.size, PURPOSE_COLOR)
            r = screen.blit(t, t.get_rect(center=purpose_rect.center))
            if entering_purpose and (time() % 1) < 0.7:
                if r.height == 0:
                    r.height = purpose_rect.height
                if r.right >= purpose_rect.right:
                    r.right = purpose_rect.right - 3
                pygame.draw.line(screen, PURPOSE_COLOR, r.topright, r.bottomright, 2)


        else:
            # Only show the time.
            time_rect = screen.get_rect()


        remaining = timer - (time() - start)
        color = TEXT_TIMES_UP_COLOR if remaining < 0 else TIMER_COLOR
        t = text(fmt_time(abs(remaining)), time_rect.size, color, monospaced_time=True)
        screen.blit(t, t.get_rect(center=time_rect.center))

        if remaining < 0 and time() - last_rung > RING_INTERVAL:
            play(BELL)
            last_rung = time()

        window.flip()
        clock.tick(60)





if __name__ == '__main__':
    main()