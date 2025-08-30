#!/usr/bin/env python3

import sys
from app import create_image

if __name__ == "__main__":
    entries = []
    for line in sys.stdin:
        if 'git ' in line:
            parts = line.strip().split()
            if len(parts) >= 3 and parts[1] == 'git':
                entries.append((int(parts[0]), parts[2]))

    if entries:
        svg = create_image(entries, format='svg', sparse=False)
        print(svg if svg else "<!-- No data to visualize -->")
