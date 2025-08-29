#!/usr/bin/env python3

import sys
from app import create_svg

if __name__ == "__main__":
    history = []
    for line in sys.stdin:
        if 'git ' in line:
            parts = line.strip().split()
            if len(parts) >= 3 and parts[1] == 'git':
                history.append(f"{parts[0]} {parts[2]}")

    if history:
        svg = create_svg('\n'.join(history))
        print(svg if svg else "<!-- No data to visualize -->")
