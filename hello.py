from flask import Flask, render_template, jsonify, request, g
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

@app.route('/graph', methods=["POST"])
def get_image():
    import os
    try:
        os.mkdir("tmp")
    except OSError:
        pass
    history = StringIO(request.form["history"])
    pair_counts, node_totals = get_statistics(history)
    G = create_graph(pair_counts[pair_counts['count'] >= 3], node_totals)
    response = jsonify({'graph': dot_draw(G, tmp_dir="./tmp")})
    try:
        write_to_db(history)
    except:
        pass
    return response

def write_to_db(history):
    cursor = g.conn.cursor()
    query = "INSERT INTO log (logfile) VALUES (%s);"
    cursor.execute(query, (history,))

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
    G = nx.DiGraph()
    node_colors = get_colors(list(node_totals.index))
    for (frm, to), count in pair_counts.iterrows():
        G.add_edge(frm, to, penwidth=float(count) / 8, color=node_colors[frm])
    for node in G.nodes():
        G.node[node]['width'] = getwidth(node, node_totals)
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

if __name__ == "__main__":
    app.run(port=5001)

@app.before_request
def before_request():
    print "Connection!"
    g.conn = db_connect()

@app.teardown_request
def teardown_request(exception):
    db = getattr(g, 'db', None)
    if db is not None:
        db.close()

def db_connect():
    urlparse.uses_netloc.append("postgres")
    db_url = os.environ["DATABASE_URL"]
    url = urlparse.urlparse(db_url)

    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    return conn
