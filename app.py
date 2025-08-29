from flask import Flask, render_template, jsonify, request, g, redirect, url_for, Response
import pandas as pd
import networkx as nx
import graphviz
import numpy as np
from io import StringIO
import sqlite3
import os
from nanoid import generate


app = Flask(__name__)
app.config['DEBUG'] = True

def load_valid_commands():
    with open('commands.txt', 'r') as f:
        return set(line.strip() for line in f)

VALID_GIT_COMMANDS = load_valid_commands()

@app.route('/')
def hello():
    return render_template('index.html')

@app.route('/display/<num>')
def display_graph(num=None):
    return render_template("display_graph.html", num=num)

@app.route('/svg/<num>')
def serve_svg(num=None):
    sparse = request.args.get('sparse', False)
    cursor = g.conn.cursor()
    cursor.execute("SELECT row_number, command FROM entries WHERE log_id = ? ORDER BY row_number", (num,))
    entries = cursor.fetchall()
    if not entries:
        return "Graph is empty!", 404
    svg = create_svg(entries, sparse=sparse)
    return Response(svg, mimetype='image/svg+xml')

def create_svg(entries, sparse=False):
    pair_counts, node_totals = get_statistics(entries)
    if pair_counts.empty:
        return None
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
    return dot_draw(G, tmp_dir="./tmp")

@app.route('/graph', methods=["POST"])
def get_image():
    history = request.form["history"]
    log_id = save_history(history)
    return redirect(url_for('display_graph', num=log_id))

def save_history(history):
    cursor = g.conn.cursor()
    log_id = generate(alphabet="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", size=10)
    cursor.execute("INSERT INTO logs (id) VALUES (?);", (log_id,))

    lines = [l for l in history.split('\n') if len(l.strip()) > 0]
    for line in lines:
        parts = line.strip().split(' ', 1)
        if len(parts) != 2:
            continue
        row_number, command = parts
        cursor.execute(
            "INSERT INTO entries (log_id, row_number, command, valid) VALUES (?, ?, ?, ?);",
            (log_id, int(row_number), command, command in VALID_GIT_COMMANDS)
        )

    g.conn.commit()
    return log_id

def dot_draw(G, prog="dot", tmp_dir="/tmp"):
    dot_string = nx.nx_pydot.to_pydot(G).to_string()
    dot_graph = graphviz.Source(dot_string, engine=prog)
    return dot_graph.pipe(format='svg', encoding='utf-8')

def getwidth(node, node_totals):
    count = np.sqrt(node_totals[node])
    count /= float(sum(np.sqrt(node_totals)))
    count *= 6
    count = max(count, 0.1)
    count = min(count, 4)
    return count

def get_colors(nodes):
    # colorbrewer Dark2 color scheme
    color_palette = ['#1b9e77', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02', '#a6761d', '#666666']
    colors = {}
    for i, node in enumerate(nodes):
        colors[node] = color_palette[i % len(color_palette)]
    return colors

def create_graph(pair_counts, node_totals):
    """
    The graph layout options are here. If you wanted to change
    how the graph looks, you'd change this
    """
    G = nx.DiGraph()
    node_colors = get_colors(list(node_totals.index))
    total_count = np.sum(pair_counts['count'])
    for (frm, to), row in pair_counts.iterrows():
        count = row['count']
        G.add_edge(frm, to,
            penwidth=float(count) / total_count * 60,
            color=node_colors[frm])
    for node in G.nodes():
        G.nodes[node]['width'] = getwidth(node, node_totals)
        G.nodes[node]['penwidth'] = 2
        G.nodes[node]['height'] = G.nodes[node]['width']
        G.nodes[node]['fontsize'] = 10
        G.nodes[node]['color'] = node_colors[node]
        G.nodes[node]['label'] = "%s (%d%%)" % (node, int(node_totals[node] / float(sum(node_totals)) * 100) )
    return G

def get_statistics(entries):
    df = pd.DataFrame(entries, columns=['row', 'command']).set_index('row')
    pairs = pd.DataFrame(index=range(len(df) - 1))
    pairs['dist'] = df.index[1:].values - df.index[:-1].values
    pairs['from'] = df['command'][:-1].values
    pairs['to'] = df['command'][1:].values
    node_totals = df['command'].value_counts()
    close_pairs = pairs[pairs.dist == 1]
    pair_counts = close_pairs.groupby(['from', 'to']).aggregate(len).rename(columns= {'dist': 'count'})
    pair_counts = pair_counts.sort_values('count', ascending=False)
    return pair_counts, node_totals

@app.before_request
def before():
    try:
        os.mkdir("tmp")
    except OSError:
        pass
    g.conn = db_connect()

@app.teardown_request
def teardown_request(exception):
    db = getattr(g, 'db', None)
    if db is not None:
        db.close()

def db_connect():
    db_path = os.environ.get("DATABASE_PATH", "git_workflow.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

if __name__ == "__main__":
    app.run(port=5001)


