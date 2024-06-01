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
import re


BELL = Path("./bell.mp3")
RING_INTERVAL = 20
PURPOSE_COLOR = (183, 255, 183)
TIMER_COLOR = (255, 224, 145)
TEXT_TIMES_UP_COLOR = (255, 0, 0)
TOTAL_TIME_COLOR = (183, 183, 255)
BACKGROUND_COLOR = (0, 0, 0)
HELP_COLOR = TIMER_COLOR
WINDOW_SCALE = 1.2
POSITIONS = [(-5, -5), (5, 5), (5, -5), (-5, 5)]
INITIAL_SIZE = (180, 70)

HELP = """
DTimer

j/k: -/+ 1 minute
r: reset timer
p: reposition window
RETURN: enter purpose
-/=: (in/de)crease window size
h/?: show this help

Press any key to dismiss this message.
""".strip()


os.environ["SDL_VIDEODRIVER"] = "x11"


def fmt_time(seconds):
    if seconds < 0:
        return "-" + fmt_time(-seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    else:
        return "%02d:%02d" % (minutes, seconds)


@lru_cache(maxsize=40)
def font(size: int, big: bool = True):
    name = "./Wellbutrin.ttf" if big else "./Wellbutrin.ttf"
    f = pygame.font.Font(name, size)
    f.align = FONT_CENTER
    return f


@lru_cache(maxsize=100)
def text(
    text: str,
    size: int | tuple[int, int],
    color: tuple,
    big: bool = True,
    monospaced_time: bool = False,
):
    if not isinstance(size, int):
        if monospaced_time:
            # Use the font size that fits a text equivalent to the time.
            # We use 0s to make sure the text is as wide as possible and doesn't jitter.
            size = auto_size(re.sub(r"\d", "0", text), size, big)
        else:
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


def size_with_newlines(text: str, size: int, big: bool = True):
    """Return the size of the text with newlines."""
    lines = text.split("\n")
    line_height = font(size, big).get_linesize()
    return (max(font(size, big).size(line)[0] for line in lines), len(lines) * line_height)


def auto_size(text: str, max_rect: tuple[int, int], big_font: bool = True):
    """Find the largest font size that will fit text in max_rect."""
    # Use dichotomy to find the largest font size that will fit text in max_rect.

    min_size = 1
    max_size = max_rect[1]
    while min_size < max_size:
        font_size = (min_size + max_size) // 2
        text_size = size_with_newlines(text, font_size, big_font)

        if text_size[0] <= max_rect[0] and text_size[1] <= max_rect[1]:
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
    return [
        pygame.Rect(rect.left, ys[i], rect.width, ys[i + 1] - ys[i]) for i in range(len(ratios))
    ]


def mk_layout(screen_size: tuple[int, int]) -> dict[str, pygame.Rect]:
    width, height = screen_size
    screen = pygame.Rect((0, 0), screen_size)

    if height < 60:
        return {"time": screen}
    elif height < 120:
        purpose, time = vsplit(screen, 1, 2)
        return {"purpose": purpose, "time": time}
    else:
        purpose, time, bottom = vsplit(screen, 1, 2, 1)
        return {"purpose": purpose, "time": time, "total_time": bottom}


def main(initial_timer: int = 120):
    pygame.init()
    pygame.mixer.init()
    pygame.key.set_repeat(300, 20)

    pygame.print_debug_info()
    window = sdl2.Window("DTimer", INITIAL_SIZE, borderless=True, always_on_top=True)
    window.get_surface().fill((0, 0, 0))
    window.flip()

    screen = window.get_surface()
    clock = pygame.time.Clock()

    position = 0
    place_window(window, *POSITIONS[position])

    start = time()
    timer = initial_timer
    last_rung = 0

    purpose = ""
    entering_purpose = False

    show_help = False
    layout = mk_layout(window.size)

    while True:
        for event in pygame.event.get():
            if event.type == QUIT:
                sys.exit()
            elif event.type == VIDEORESIZE:
                layout = mk_layout(window.size)
            elif event.type == KEYDOWN:
                show_help = False
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
                elif event.key == K_r:
                    # +1 to more likely show visually round time -> more satisfying
                    timer = initial_timer + (time() - start) + 1
                elif event.key == K_MINUS:
                    window.size = (window.size[0] / WINDOW_SCALE, window.size[1] / WINDOW_SCALE)
                    layout = mk_layout(window.size)
                elif event.key == K_EQUALS:
                    window.size = (window.size[0] * WINDOW_SCALE, window.size[1] * WINDOW_SCALE)
                    layout = mk_layout(window.size)
                elif event.key == K_p:
                    position = (position + 1) % len(POSITIONS)
                    place_window(window, *POSITIONS[position])
                elif event.key in (K_h, K_QUESTION):
                    show_help = not show_help

        screen.fill(BACKGROUND_COLOR)

        # Render purpose, if there is space.
        if purpose_rect := layout.get("purpose"):
            t = text(purpose, purpose_rect.size, PURPOSE_COLOR)
            r = screen.blit(t, t.get_rect(center=purpose_rect.center))
            if entering_purpose and (time() % 1) < 0.7:
                if r.height == 0:
                    r.height = purpose_rect.height
                if r.right >= purpose_rect.right:
                    r.right = purpose_rect.right - 3
                pygame.draw.line(screen, PURPOSE_COLOR, r.topright, r.bottomright, 2)

        # Render time.
        if time_rect := layout.get("time"):
            remaining = timer - (time() - start)
            color = TEXT_TIMES_UP_COLOR if remaining < 0 else TIMER_COLOR
            t = text(fmt_time(abs(remaining)), time_rect.size, color, monospaced_time=True)
            screen.blit(t, t.get_rect(center=time_rect.center))

        if total_time_rect := layout.get("total_time"):
            t = text(
                fmt_time(time() - start),
                total_time_rect.size,
                TOTAL_TIME_COLOR,
                monospaced_time=True,
            )
            screen.blit(t, t.get_rect(center=total_time_rect.center))

        if show_help:
            screen.fill(BACKGROUND_COLOR)
            t = text(HELP, screen.get_size(), HELP_COLOR, big=False)
            screen.blit(t, t.get_rect(center=screen.get_rect().center))

        # Ring the bell if the time is up.
        if remaining < 0 and time() - last_rung > RING_INTERVAL:
            play(BELL)
            last_rung = time()

        window.flip()
        clock.tick(60)


if __name__ == "__main__":
    main()
