from flask import Flask, render_template, jsonify, request, g, abort
import pandas as pd
import networkx as nx
import pygraphviz as pgv
import json
import tempfile
import numpy as np
import brewer2mpl
from StringIO import StringIO
import psycopg2
import urlparse
import os


app = Flask(__name__)
app.config['DEBUG'] = True


@app.route('/')
def hello():
    return render_template('index.html')

@app.route('/display/<num>')
def display_graph(num=None, sparse=False):
    cursor = g.conn.cursor()
    try:
        cursor.execute("SELECT logfile FROM log WHERE id = %s", (num,));
        history = cursor.fetchone()[0]
        svg = create_svg(history, sparse=sparse)
        if svg is None:
            svg = "Graph is empty!"
    except:
        svg = "Sorry, there's no log file with that id."
    return render_template("display_graph.html", svg=svg, num=num)

@app.route('/display/<num>/sparse')
def display_graph_sparse(num=None):
    return display_graph(num, True)

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
    response = jsonify({'graph': svg, 'id': row_id})
    return response

def write_to_db(history):
    cursor = g.conn.cursor()
    query = "INSERT INTO log (logfile) VALUES (%s) RETURNING id;"
    try:
        cursor.execute(query, (history,))
        row_id = cursor.fetchone()[0]
        g.conn.commit()
    except psycopg2.IntegrityError:
        g.conn.rollback()
        select_query = "SELECT id FROM log WHERE logfile = %s;"
        cursor.execute(select_query, (history,))
        row_id = cursor.fetchone()[0]
        print "Not adding data -- it already exists"
    return row_id

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
    urlparse.uses_netloc.append("postgres")
    db_url = os.environ["HEROKU_POSTGRESQL_CYAN_URL"]
    url = urlparse.urlparse(db_url)

    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    return conn

if __name__ == "__main__":
    app.run(port=5001)


