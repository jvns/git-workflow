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
    try:
        cursor.execute("SELECT logfile FROM log WHERE id = ?", (num,));
        history = cursor.fetchone()[0]
        svg = create_svg(history, sparse=sparse)
        if svg is None:
            return "Graph is empty!", 404
        return Response(svg, mimetype='image/svg+xml')
    except:
        return "Sorry, there's no log file with that id.", 404

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
    return dot_draw(G, tmp_dir="./tmp")

@app.route('/graph', methods=["POST"])
def get_image():
    history = request.form["history"]
    sparse = request.form.get("sparse", False)
    svg = create_svg(history, sparse=sparse)
    row_id  = write_to_db(history)
    return redirect(url_for('display_graph', num=row_id))

def write_to_db(history):
    cursor = g.conn.cursor()
    nanoid = generate(alphabet="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", size=10)
    query = "INSERT INTO log (id, logfile) VALUES (?, ?);"
    try:
        cursor.execute(query, (nanoid, history))
        g.conn.commit()
        return nanoid
    except sqlite3.IntegrityError:
        g.conn.rollback()
        select_query = "SELECT id FROM log WHERE logfile = ?;"
        cursor.execute(select_query, (history,))
        row_id = cursor.fetchone()[0]
        print("Not adding data -- it already exists")
        return row_id

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

def get_statistics(text):
    df = pd.read_csv(text, sep=' ', header=None, names=["row", "command"], index_col="row")
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


