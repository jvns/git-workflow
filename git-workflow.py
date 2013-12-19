# from hello.py
# this code could be re-factored out of hello.py and moved to a library

# STDIN: the output of the history(3) command
# STDOUT: a SVG file, with a representation of git workflow

import pandas as pd
import networkx as nx
import pygraphviz as pgv
import json
import tempfile
import numpy as np
import brewer2mpl
from StringIO import StringIO
import os
import sys
import re


def create_svg(history, sparse=False):
    pair_counts, node_totals = get_statistics(StringIO(history))
    total_count = float(np.sum(pair_counts['count']))
    # Only look at transitions that happen at least 1% of the time
    if sparse:
        counts = pair_counts[pair_counts['count'] >= total_count / 100]
    else:
        if total_count >= 300:
            min_count = 3
        else:
            min_count = 1
        counts = pair_counts[pair_counts['count'] >= min_count]
    if len(counts) == 0:
        return
    G = create_graph(counts, node_totals)
    return dot_draw(G, tmp_dir="/tmp")

def dot_draw(G, prog="dot", tmp_dir="/tmp"):
    # Hackiest code :)
    tmp_dot = tempfile.mktemp(dir=tmp_dir, suffix=".dot")
    tmp_image = tempfile.mktemp(dir=tmp_dir, suffix=".svg")
    nx.write_dot(G, tmp_dot)
    dot_graph = pgv.AGraph(tmp_dot)
    dot_graph.draw(tmp_image, prog=prog)
    with open(tmp_image) as f:
        data = f.read()
    return data

def getwidth(node, node_totals):
    count = np.sqrt(node_totals[node])
    count /= float(sum(np.sqrt(node_totals)))
    count *= 6
    count = max(count, 0.1)
    count = min(count, 4)
    return count

def get_colors(nodes):
    n_colors = 8
    colors = {}
    set2 = brewer2mpl.get_map('Dark2', 'qualitative', n_colors).hex_colors
    for i, node in enumerate(nodes):
        colors[node] = set2[i % n_colors]
    return colors

def create_graph(pair_counts, node_totals):
    """
    The graph layout options are here. If you wanted to change
    how the graph looks, you'd change this
    """
    G = nx.DiGraph()
    node_colors = get_colors(list(node_totals.index))
    total_count = np.sum(pair_counts['count'])
    for (frm, to), count in pair_counts.iterrows():
        G.add_edge(frm, to,
            penwidth=float(count) / total_count * 60,
            color=node_colors[frm])
    for node in G.nodes():
        G.node[node]['width'] = getwidth(node, node_totals)
        G.node[node]['penwidth'] = 2
        G.node[node]['height'] = G.node[node]['width']
        G.node[node]['fontsize'] = 10
        G.node[node]['color'] = node_colors[node]
        G.node[node]['label'] = "%s (%d%%)" % (node, int(node_totals[node] / float(sum(node_totals)) * 100) )
    return G

def get_statistics(text):
    df = pd.read_csv(text, sep=' ', header=None, names=["row", "command"], index_col="row")
    pairs = pd.DataFrame(index=range(len(df) - 1))
    pairs['dist'] = df.index[1:].values - df.index[:-1].values
    pairs['from'] = df['command'][:-1].values
    pairs['to'] = df['command'][1:].values
    node_totals = df['command'].value_counts()
    close_pairs = pairs[pairs.dist == 1]
    pair_counts = close_pairs.groupby(['from', 'to']).aggregate(len).rename(columns= {'dist': 'count'})
    pair_counts = pair_counts.sort('count', ascending=False)
    return pair_counts, node_totals

# https://gist.github.com/mwhite/7509467
# Outputs history with bash and git aliases expanded.
from subprocess import check_output
 
BASH_ALIASES = {}
for line in check_output('bash -i -c "alias -p"', shell=True).split('\n'):
    if not line.strip():
        continue
    match = re.match(r"^alias (.+?)='(.+?)'\n*$", line)
    BASH_ALIASES[match.group(1)] = match.group(2)
 
 
GIT_ALIASES = {}
try:
    for line in check_output('git config --get-regexp alias*', shell=True).split('\n'):
        if not line.strip():
            continue
 
        match = re.match(r"^alias\.(.+?) (.+)$", line)
        GIT_ALIASES[match.group(1)] = match.group(2)
except:
    # git config will return a non-zero exit status if there are no aliases
    pass
 
 
def expand(cmd):
    try:
        number, cmd = cmd.strip().split(' ', 1)
        cmd = cmd.strip()
    except ValueError:
        # empty line
        return cmd
 
    for alias, expansion in BASH_ALIASES.items():
        cmd = re.sub(r"^" + re.escape(alias) + '(\s|$)', expansion + ' ', cmd)
    for alias, expansion in GIT_ALIASES.items():
        cmd = re.sub(r"^git " + re.escape(alias) + "(\s|$)", "git %s " % expansion, cmd)
 
    return " %s  %s" % (number, cmd)
 
 
if __name__ == "__main__":

    history = []
    for line in sys.stdin.readlines(): 
        line = expand(line)
        if line.find('  git ') > 0:
            parts = re.split(r'\s+', line.strip())
            if len(parts) >= 3 and parts[2].find('|') < 0:
                history.append("%s %s" % (parts[0], parts[2]))

    print create_svg('\n'.join(history))
